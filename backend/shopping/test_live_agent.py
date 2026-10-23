from copy import deepcopy
from datetime import datetime,timezone
from unittest.mock import patch
from django.test import TestCase,override_settings
from django.core.cache import cache
from rest_framework.test import APIClient
from .services.live import normalize_live_product,get_json,LiveSearchError,schedule_hours,enrich_offer,route_key,search_live_in_person

PID='60f90a56-f971-434b-a1de-fc602e629b53'
def fixture():
    hours={'schedule':[{'title':'پنجشنبه (امروز)','text':'۱۰:۰۰ - ۲۰:۰۰'}]}
    rows=[{'prk':'offer-one','shop_id':100,'shop_name':'فروشگاه تهران','shop_name2':'تهران','price':105000000,
        'location':{'lat':35.7,'lon':51.4},'working_hours':hours,'name2':'گارانتی ۱۸ ماهه؛ مشکی',
        'address':'نشانی کوتاه...','last_price_change_date':'۱۵ روز پیش','supports_fast_delivery':True},
        {'prk':'offer-two','shop_id':200,'shop_name':'ساعت نامشخص','shop_name2':'تهران','price':100000000,
        'location':{'lat':35.8,'lon':51.4},'working_hours':None,'is_open':False,'name2':'مشکی'},
        {'prk':'offer-three','shop_id':300,'shop_name':'شهر دیگر','shop_name2':'قم','price':1,
        'location':{'lat':34.6,'lon':50.8},'working_hours':hours}]
    return {'base':{'random_key':PID,'name1':'گوشی سامسونگ A55','price':999,'image_urls':[]},'sellers':rows,'retrieved_at':'2026-10-22T10:00:00Z'}

class LiveAgentTests(TestCase):
    def setUp(self):cache.clear();self.client=APIClient();self.prefs={'category':'گوشی موبایل','budget_max':120000000,'visit_at':datetime(2026,10,22,12,tzinfo=timezone.utc)}
    def test_live_seller_identity_price_coordinates_and_unknown_hours(self):
        p=normalize_live_product(fixture(),self.prefs,{'lat':35.7,'lon':51.4})
        self.assertEqual(p['source'],'torob_live');self.assertEqual(p['offer_count'],2)
        self.assertEqual(p['best_offer']['shop']['name'],'فروشگاه تهران')
        self.assertEqual(p['best_offer']['price_toman'],105000000)
        self.assertEqual(p['best_offer']['distance_km'],0)
        unknown=next(o for o in p['offers'] if o['shop']['name']=='ساعت نامشخص')
        self.assertEqual(unknown['shop']['opening']['state'],'unknown')
    def test_budget_color_and_open_remain_hard(self):
        self.assertIsNone(normalize_live_product(fixture(),{**self.prefs,'budget_max':999}))
        self.assertIsNone(normalize_live_product(fixture(),{**self.prefs,'color':'سفید'}))
        p=normalize_live_product(fixture(),{**self.prefs,'only_open':True})
        self.assertEqual(p['offer_count'],1)
    @override_settings(TOROB_LIVE_PRODUCT_LIMIT=1)
    def test_budget_prioritizes_which_live_product_is_inspected(self):
        market={'status':'ok','products':[{'id':'expensive','title':'گوشی گران','price_toman':300000000},{'id':PID,'title':'گوشی مناسب','price_toman':110000000}]}
        with patch('shopping.services.live.search_live',return_value=market),patch('shopping.services.live.raw_product',return_value=fixture()) as details:
            result=search_live_in_person(self.prefs)
        details.assert_called_once_with(PID);self.assertEqual(result['products'][0]['best_offer']['price_toman'],105000000)
    def test_requested_visit_time_changes_open_status(self):
        p=normalize_live_product(fixture(),{**self.prefs,'visit_at':datetime(2026,10,22,18,tzinfo=timezone.utc)})
        actual=next(o for o in p['offers'] if o['shop']['name']=='فروشگاه تهران')
        self.assertEqual(actual['shop']['opening']['state'],'closed')
    def test_parses_persian_declared_hours(self):
        h=schedule_hours({'schedule':[{'title':'سه‌شنبه','text':'۰۹:۰۰ - ۱۳:۰۰ و ۱۷:۰۰ - ۲۱:۰۰'},{'title':'پنج‌شنبه (امروز)','text':'۱۱:۰۰ - ۲۱:۰۰'},{'title':'جمعه','text':'فروشگاه تعطیل است'}]})
        self.assertEqual(len(h['tue']['shifts']),2);self.assertEqual(h['fri']['status'],'closed');self.assertEqual(h['thu']['status'],'declared')
    def test_origin_code_is_not_inventory_failure_and_no_retry(self):
        with patch('shopping.services.live.requests.get') as get:
            get.return_value.status_code=403;get.return_value.json.return_value={'error':'origin_not_allowed'}
            with self.assertRaises(LiveSearchError) as caught:get_json('https://api.torob.com/v4/base-product/search/')
            self.assertEqual(caught.exception.code,'torob_origin_not_allowed');self.assertEqual(get.call_count,1)
    def test_untrusted_route_is_not_requested(self):
        with patch('shopping.services.live.requests.get') as get:
            with self.assertRaises(LiveSearchError):get_json('http://127.0.0.1/private')
            get.assert_not_called()
    @override_settings(LLM_ENABLED=False)
    def test_chat_uses_live_pipeline_by_default(self):
        product=normalize_live_product(fixture(),self.prefs)
        result={'products':[product],'matched_count':1,'source':'torob_live','checked_product_count':1,'market':{'status':'ok','products':[]}}
        with patch('shopping.views.search_live_in_person',return_value=result) as live:
            r=self.client.post('/api/chat/',{'message':'گوشی سامسونگ A55 برای عکاسی','preferences':{'budget_any':True,'color_any':True},'location':{'lat':35.7,'lon':51.4}},format='json')
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['source'],'torob_live');self.assertEqual(live.call_args.args[1]['lat'],35.7)
        self.assertIn('عکاسی',r.json()['preferences']['needs'])
    @override_settings(LLM_ENABLED=False,TOROB_FALLBACK_TO_DATASET=False)
    def test_live_failure_is_visible_in_chat_status(self):
        with patch('shopping.views.search_live_in_person',side_effect=LiveSearchError('اتصال به ترب برقرار نشد.')):
            r=self.client.post('/api/chat/',{'message':'گوشی سامسونگ','preferences':{'budget_any':True,'color_any':True,'needs':'مقایسه مدل‌ها'}},format='json')
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['source'],'torob_unavailable')
        self.assertEqual(r.json()['market']['status'],'unavailable');self.assertIn('انجام نشد',r.json()['reply'])
    def test_backend_identifies_itself_under_local_origin(self):
        r=self.client.get('/api/health/',HTTP_ORIGIN='http://localhost:4173')
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['service'],'torob-yar')
    @override_settings(PUBLISH_PHONE_CONTACTS=False)
    def test_full_address_can_be_loaded_without_publishing_contacts(self):
        product=normalize_live_product(fixture(),self.prefs);offer=product['best_offer']
        cache.set(route_key('offer-route',offer['id']),{'url':'https://api.torob.com/v4/product-in-store/contact-info/?prk=x','product_id':PID})
        with patch('shopping.services.live.get_json',return_value={'address':'پاساژ، طبقه دوم، واحد ۷','phone':'02100000000','coordinates':{'lat':35.7,'lon':51.4}}):
            result=enrich_offer(offer,PID)
        self.assertTrue(result['shop']['address_complete']);self.assertIn('واحد ۷',result['shop']['address']);self.assertEqual(result['shop']['contacts'],[])
