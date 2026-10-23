from datetime import datetime,timezone
from unittest.mock import patch
from django.test import TestCase,SimpleTestCase,override_settings
from django.core.cache import cache
from rest_framework.test import APIClient
from .models import Shop,Product,Offer
from .services.common import opening_status,payment_matches,distance_km
from .services.intent import infer
from .services.search import search_products
from .services.llm import explain
from .services.live import search_live,LiveSearchError

class HoursTests(SimpleTestCase):
    def test_unknown_not_open(self):self.assertEqual(opening_status({})['state'],'unknown')
    def test_overnight(self):
        hours={'wed':{'status':'declared','shifts':[{'start_time':'22:00:00','end_time':'02:00:00'}]},'thu':{'status':'closed'}}
        self.assertEqual(opening_status(hours,datetime(2026,10,21,21,30,tzinfo=timezone.utc))['state'],'open')
        self.assertEqual(opening_status(hours,datetime(2026,10,22,6,tzinfo=timezone.utc))['state'],'closed')
    def test_unknown_channel_not_in_person(self):
        self.assertFalse(payment_matches({'provider_name':'ترب‌پی','channel':'unknown'},'گوشی موبایل','ترب‌پی'))
    def test_payment_category_restriction(self):
        self.assertFalse(payment_matches({'channel':'in_person','category_names':['لپ تاپ']},'گوشی موبایل'))
    def test_distance_missing(self):self.assertIsNone(distance_km(None,None,35,51))
    def test_intent_budget_and_storage(self):
        p=infer('گوشی سامسونگ A55 حافظه ۲۵۶ با بودجه ۱۲۰ میلیون تومان')
        self.assertEqual(p['budget_max'],120000000);self.assertEqual(p['query'],'a55')
        self.assertNotIn('budget_max',infer('گوشی سامسونگ حافظه ۲۵۶ رم ۸'))

class SearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.shop=Shop.objects.create(id='s',name='فروشگاه واقعی',lat=35.7,lon=51.4,contacts=[{'channel':'phone','display_number':'۰۲۱۱۲۳۴۵۶۷۸'}])
        Shop.objects.create(id='category-only',name='فقط دسته',categories=['گوشی موبایل'],lat=35.7,lon=51.4)
        cls.product=Product.objects.create(id='p',title='گوشی سامسونگ A55',brand='سامسونگ',category='گوشی موبایل',search_text='گوشی سامسونگ a55',color_text='مشکی')
        Offer.objects.create(id='o',product=cls.product,shop=cls.shop,price_toman=100,last_price_changed_at=datetime(2020,1,1,tzinfo=timezone.utc))
    def setUp(self):cache.clear();self.client=APIClient()
    def test_real_offer_relation_only(self):
        p=search_products({})['products'][0]
        self.assertEqual(p['offer_count'],1);self.assertEqual(p['best_offer']['shop']['id'],'s')
    def test_budget_is_hard(self):self.assertEqual(search_products({'budget_max':99})['matched_count'],0)
    def test_unknown_closed_filter(self):self.assertEqual(search_products({'only_open':True})['matched_count'],0)
    def test_color_is_hard(self):self.assertEqual(search_products({'color':'سفید'})['matched_count'],0)
    def test_unknown_instalments(self):
        self.shop.payment_options=[{'provider_name':'ترب‌پی','channel':'unknown'}];self.shop.save()
        self.assertEqual(search_products({'torobpay':True})['matched_count'],0)
    def test_old_price_and_zero_distance(self):
        o=search_products({},location={'lat':35.7,'lon':51.4})['products'][0]['best_offer']
        self.assertTrue(o['price_stale']);self.assertEqual(o['distance_km'],0);self.assertEqual(o['availability'],'recorded_offer')
    @override_settings(PUBLISH_PHONE_CONTACTS=False)
    def test_unreleased_contacts_not_in_api(self):
        r=self.client.get('/api/shops/s/');self.assertEqual(r.status_code,200);self.assertEqual(r.json()['contacts'],[])
    def test_request_validation(self):
        r=self.client.post('/api/chat/',{'message':'x'*1600},format='json');self.assertEqual(r.status_code,400)
        r=self.client.post('/api/chat/',{'message':'hi','location':{'lat':100,'lon':10}},format='json');self.assertEqual(r.status_code,400)
    @override_settings(LLM_ENABLED=False)
    def test_rule_chat_preserves_preferences(self):
        r=self.client.post('/api/chat/',{'message':'رنگ مهم نیست','preferences':{'category':'گوشی موبایل','budget_max':200,'search_mode':'dataset'}},format='json')
        self.assertEqual(r.status_code,200);d=r.json();self.assertEqual(d['preferences']['budget_max'],200);self.assertTrue(d['preferences']['color_any']);self.assertFalse(d['llm']['used'])
    def test_model_cannot_add_products_to_evidence(self):
        r=search_products({})['products']
        with patch('shopping.services.llm.json_call',return_value={'explanation':'مقایسه','ranked_product_ids':['invented','p','p']}):
            text,order=explain({},r)
        self.assertEqual(order,['p']);self.assertEqual(r[0]['best_offer']['price_toman'],100)
    @override_settings(TOROB_LIVE_ENABLED=True)
    def test_live_results_keep_separate_source(self):
        with patch('shopping.services.live.requests.get') as get:
            get.return_value.status_code=200;get.return_value.json.return_value={'results':[{'random_key':'real','name1':'محصول','price':200,'web_client_absolute_url':'/p/real/','shop_text':'دو فروشگاه'}]}
            d=search_live('sample')
        self.assertEqual(d['source'],'torob_live');self.assertFalse(d['products'][0]['local_shop_match']);self.assertEqual(d['products'][0]['price_toman'],200)
    @override_settings(TOROB_LIVE_ENABLED=True)
    def test_block_does_not_retry(self):
        with patch('shopping.services.live.requests.get') as get:
            get.return_value.status_code=429
            with self.assertRaises(LiveSearchError):search_live('blocked')
            self.assertEqual(get.call_count,1)
