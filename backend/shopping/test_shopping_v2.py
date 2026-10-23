import json
from copy import deepcopy
from unittest.mock import patch,Mock
from django.test import TestCase,SimpleTestCase,override_settings
from django.core.cache import cache
from rest_framework.test import APIClient
from .services.intent import infer
from .services.preferences import missing_questions,variant_matches
from .services.live import normalize_live_product,search_live_in_person,LiveSearchError
from .services.places import neshan_search,neshan_detail,google_places,reverse,ProviderError,links,selectable,selected_place
from .services.web_research import google_search
from .services.pages import extract_page,public_url,public_text,PageUnavailable
from .test_live_agent import fixture,PID

READY={'category':'گوشی موبایل','query':'a55','budget_max':120000000,'color_any':True,'needs':'عکاسی'}

@override_settings(LLM_ENABLED=False,SERPER_API_KEY='',GOOGLE_PLACES_API_KEY='',NESHAN_SERVICE_KEY='')
class ConversationV2Tests(TestCase):
    def setUp(self):cache.clear();self.client=APIClient()
    def test_first_broad_message_asks_before_searching(self):
        with patch('shopping.views.search_live_in_person') as search:
            data=self.client.post('/api/chat/',{'message':'یک گوشی میخوام'},format='json').json()
        self.assertEqual(data['source'],'clarification');self.assertEqual(data['questions'][0]['key'],'budget');search.assert_not_called()
    def test_answers_do_not_repeat_budget_or_type_questions(self):
        with patch('shopping.views.search_live_in_person',return_value={'products':[],'matched_count':0,'source':'torob_live'}):
            data=self.client.post('/api/chat/',{'message':'مشکی','preferences':{**READY,'color_any':False}},format='json').json()
        self.assertNotEqual(data.get('stage'),'clarify')
        self.assertFalse(any(q['key'] in ('budget','color') for q in data['questions']))
    def test_unknown_product_request_asks_product(self):
        data=self.client.post('/api/chat/',{},format='json').json()
        self.assertEqual(data['questions'][0]['key'],'product')
    def test_known_budget_and_model_only_ask_color(self):
        with patch('shopping.views.search_live_in_person') as search:
            data=self.client.post('/api/chat/',{'message':'گوشی سامسونگ A55 تا ۱۲۰ میلیون تومان'},format='json').json()
        self.assertEqual(data['questions'][0]['key'],'color');self.assertEqual(data['preferences']['budget_max'],120000000);search.assert_not_called()
    def test_store_intent_preserves_previous_product_and_reports_missing_keys(self):
        data=self.client.post('/api/chat/',{'message':'الان داخل پاساژ چارسو هستم','preferences':READY},format='json').json()
        self.assertEqual(data['source'],'store_research');self.assertEqual(data['preferences']['query'],'a55')
        self.assertEqual(data['stores']['providers']['google_places'],'not_configured')
        self.assertEqual(data['stores']['candidates'],[]);self.assertIn('GPS',data['indoor_note'])
    def test_visit_context_is_not_claimed_as_verified_floor(self):
        data=self.client.post('/api/chat/',{'preferences':{'task':'store','store_query':'آزمایشی'},'visit':{'store_name':'آزمایشی','floor':'۴','unit':'۸','stage':'checkout'}},format='json').json()
        self.assertEqual(data['visit_context']['floor'],'۴');self.assertTrue(data['shopping_checklist']);self.assertEqual(data['stores']['candidates'],[])
    def test_map_config_exposes_only_public_map_key(self):
        with override_settings(NESHAN_MAP_KEY='public-web',NESHAN_SERVICE_KEY='private-service',SERPER_API_KEY='private-search'):
            data=self.client.get('/api/map-config/').json()
        self.assertEqual(data['map_key'],'public-web');self.assertNotIn('private',json.dumps(data))
    def test_invalid_price_range_is_rejected_before_provider_call(self):
        r=self.client.post('/api/live-search/',{'preferences':{**READY,'budget_min':200000000}},format='json')
        self.assertEqual(r.status_code,400)
    def test_market_endpoint_uses_the_same_preferences_and_location(self):
        with patch('shopping.views.search_live_in_person',return_value={'market':{'products':[],'filters_applied':True}}) as search:
            r=self.client.post('/api/live-search/',{'preferences':{**READY,'installment':True,'condition':'new','size':'42','model':'a55'},'location':{'lat':35.7,'lon':51.4}},format='json')
        self.assertEqual(r.status_code,200);prefs,loc=search.call_args.args
        self.assertTrue(prefs['installment']);self.assertEqual(prefs['model'],'a55');self.assertEqual(loc['lat'],35.7)
    def test_provider_failure_does_not_become_no_stock(self):
        with patch('shopping.views.search_live_in_person',side_effect=LiveSearchError('upstream')):
            r=self.client.post('/api/live-search/',{'preferences':READY},format='json')
        self.assertEqual(r.status_code,502);self.assertFalse(r.json()['available'])

class FilterV2Tests(SimpleTestCase):
    def test_persian_decimal_and_rial_are_converted_to_toman(self):
        self.assertEqual(infer('تا ۲٫۵ میلیون تومان')['budget_max'],2500000)
        self.assertEqual(infer('تا ۳۰۰۰۰۰۰۰ ریال')['budget_max'],3000000)
        p=infer('بین ۲۰ تا ۳۰ میلیون ریال');self.assertEqual((p['budget_min'],p['budget_max']),(2000000,3000000))
    def test_new_category_clears_stale_color_model_size_condition(self):
        p=infer('یک لپ تاپ برای برنامه نویسی میخوام',{**READY,'color':'مشکی','model':'a55','size':'42','condition':'used'})
        self.assertEqual(p['model'],'');self.assertEqual(p['color'],'');self.assertEqual(p['size'],'');self.assertEqual(p['condition'],'any')
    def test_installment_uses_persian_spelling_and_negation(self):
        self.assertTrue(infer('اقساطی میخوام')['installment']);self.assertFalse(infer('بدون قسط')['installment'])
    def test_unknown_seller_color_cannot_match_general_product_colors(self):
        raw=fixture();raw['sellers']=[raw['sellers'][0]];raw['sellers'][0]['name2']='گارانتی'
        raw['base']['structural_specs']={'headers':[{'specs':{'رنگ':'مشکی و سفید'}}]}
        self.assertIsNone(normalize_live_product(raw,{**READY,'color':'مشکی'}))
    def test_condition_size_are_hard_filters(self):
        self.assertTrue(variant_matches('آکبند؛ مشکی؛ سایز 42',{'color':'مشکی','condition':'new','size':'42'}))
        self.assertFalse(variant_matches('کارکرده مشکی',{'condition':'new'}));self.assertFalse(variant_matches('مدل نامشخص',{'condition':'used'}))
    def test_market_price_is_same_matching_seller_price_not_base_minimum(self):
        market={'products':[{'id':PID,'title':'گوشی سامسونگ A55','price_toman':1}],'status':'ok'}
        with patch('shopping.services.live.search_live',return_value=market),patch('shopping.services.live.raw_product',return_value=fixture()):
            data=search_live_in_person({**READY,'sort':'price'})
        self.assertEqual(data['market']['products'][0]['price_toman'],data['products'][0]['best_offer']['price_toman'])
        self.assertGreater(data['market']['products'][0]['price_toman'],1)
    def test_no_repeated_questions_for_explicit_any_preferences(self):
        self.assertEqual(missing_questions({**READY,'query':'','needs':'کار روزمره','color_any':True,'budget_any':True}),[])

@override_settings(NESHAN_SERVICE_KEY='private-neshan',GOOGLE_PLACES_API_KEY='private-google',PUBLISH_PHONE_CONTACTS=True)
class PlaceV2Tests(SimpleTestCase):
    def test_neshan_v3_request_encodes_q_and_does_not_swap_lat_lon(self):
        with patch('shopping.services.places.api_json',return_value={'items':[{'title':'فروشگاه','poiHash':'abc_123','location':{'x':51.4,'y':35.7}}]}) as call:
            rows=neshan_search('فروشگاه',{'lat':35.7,'lon':51.4})
        q=json.loads(call.call_args.kwargs['params']['q']);self.assertEqual(q['center']['latitude'],35.7)
        self.assertEqual(rows[0]['lat'],35.7);self.assertEqual(rows[0]['lon'],51.4);self.assertEqual(rows[0]['contacts'],[])
    def test_neshan_details_phone_stays_with_selected_business(self):
        fixture={'name':'فروشگاه الف','phoneNumber':'۰۲۱۱۲۳۴۵۶۷۸','website':'example.com','address':'واحد ۷','workHours':[{'day':'جمعه','ranges':[]}],'location':{'x':51.4,'y':35.7}}
        with patch('shopping.services.places.api_json',return_value=fixture) as call:p=neshan_detail('abc_123')
        self.assertEqual(call.call_args.args[2],'https://api.neshan.org/v1/point');self.assertEqual(p['name'],'فروشگاه الف')
        self.assertEqual(p['contacts'][0]['display_number'],'02112345678');self.assertEqual(p['weekly_hours']['fri']['status'],'closed')
    def test_no_contact_is_invented_when_provider_does_not_have_it(self):
        with patch('shopping.services.places.api_json',return_value={'name':'فروشگاه','phoneNumber':None,'website':'javascript:alert(1)'}):p=neshan_detail('abc123')
        self.assertEqual(p['contacts'],[]);self.assertEqual(p['website_url'],'');self.assertEqual(p['opening']['state'],'unknown')
    def test_reverse_is_v5_and_does_not_claim_indoor_position(self):
        with patch('shopping.services.places.api_json',return_value={'formatted_address':'خیابان'}) as call:p=reverse({'lat':35.7,'lon':51.4,'accuracy_m':80})
        self.assertIn('/v5/reverse',call.call_args.args[2]);self.assertFalse(p['indoor_precision']);self.assertEqual(p['accuracy_m'],80)
    def test_google_places_field_mask_and_attribution_are_preserved(self):
        payload={'places':[{'id':'abc','displayName':{'text':'Store'},'location':{'latitude':35.7,'longitude':51.4},'nationalPhoneNumber':'02112345678','attributions':[{'displayName':'Provider'}]}]}
        with patch('shopping.services.places.api_json',return_value=payload) as call:rows=google_places('Store')
        self.assertIn('places.nationalPhoneNumber',call.call_args.kwargs['headers']['X-Goog-FieldMask']);self.assertEqual(rows[0]['attributions'][0]['displayName'],'Provider')
    def test_bad_neshan_hash_is_rejected_without_network(self):
        with patch('shopping.services.places.api_json') as call,self.assertRaises(ProviderError):neshan_detail('../private')
        call.assert_not_called()
    def test_selected_business_token_cannot_be_edited_by_client(self):
        p=selectable({'provider':'neshan','name':'Store A','id':'neshan:abc','distance_km':1.2})
        self.assertEqual(selected_place(p['selection_token'])['name'],'Store A')
        self.assertNotIn('distance_km',selected_place(p['selection_token']))
        self.assertIsNone(selected_place(p['selection_token']+'tampered'))

class WebEvidenceV2Tests(SimpleTestCase):
    @override_settings(SERPER_API_KEY='private',WEB_RESEARCH_ENABLED=True,WEB_PAGE_FETCH_ENABLED=False)
    def test_google_search_keeps_sources_and_drops_unsafe_link(self):
        with patch('shopping.services.web_research.api_json',return_value={'organic':[{'title':'Page','link':'https://example.com/item','snippet':'نام و قیمت قدیمی'},{'link':'javascript:alert(1)'}]}) as call:
            data=google_search('گوشی')
        self.assertEqual(len(data['sources']),1);self.assertEqual(data['sources'][0]['evidence_type'],'search_snippet')
        self.assertIn('X-API-KEY',call.call_args.kwargs['headers']);self.assertNotIn('private',json.dumps(data))
    def test_page_extract_removes_scripts_and_reads_structured_business_phone(self):
        html='<html><script>leak_secret()</script><p>فروشگاه تست، نشانی و مشخصات مدل ثبت شده در این صفحه است.</p><script type="application/ld+json">{"@type":"Store","name":"فروشگاه تست","telephone":"02112345678"}</script></html>'
        data=extract_page(html,'فروشگاه تست');self.assertNotIn('leak_secret',data['page_excerpt']);self.assertEqual(data['structured_facts'][0]['telephone'],'02112345678')
    def test_public_page_fetch_blocks_private_addresses(self):
        for address in ('127.0.0.1','10.0.0.1','::1','169.254.169.254'):
            with patch('shopping.services.pages.socket.getaddrinfo',return_value=[(0,0,0,'',(address,443))]):self.assertFalse(public_url('https://example.com/private'))
    def test_page_redirect_is_revalidated(self):
        r=Mock();r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=False);r.status_code=302;r.headers={'Location':'https://127.0.0.1/private'}
        with patch('shopping.services.pages.public_url',side_effect=[True,False]),patch('shopping.services.pages.requests.get',return_value=r) as get,self.assertRaises(PageUnavailable):public_text('https://example.com/page')
        self.assertEqual(get.call_count,1)
    @override_settings(SERPER_API_KEY='')
    def test_no_google_key_is_reported_without_fake_results(self):
        with patch('shopping.services.web_research.api_json') as call:p=google_search('فروشگاه')
        self.assertEqual(p['status'],'not_configured');self.assertEqual(p['sources'],[]);call.assert_not_called()
