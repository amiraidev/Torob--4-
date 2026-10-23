import csv
import io
import json
import tempfile
import zipfile
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from django.core.management import call_command
from django.test import TestCase,SimpleTestCase,override_settings
from rest_framework.test import APIClient
from shopping.models import Shop,Product,Offer,ImportState
from shopping.management.commands.import_torob import Command
from shopping.services.intent import infer
from shopping.services.research import attach_research
from shopping.services.live import normalize_live_product,payments_for,search_live_in_person,live_offer_detail
from shopping.test_live_agent import fixture,PID

class ImportAuditTests(TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.source=Path(self.directory.name)/'sample.zip'
        self.write_zip()
    def write_zip(self,price=100):
        tables={
            'shops.csv':[
                dict(shop_id='s',name='فروشگاه فارسی',address='تهران',category_names='[]',contacts='[]',lat='35.7',lon='51.4',location_label='',weekly_hours='{}',payment_options='[]',supports_fast_delivery='null',website_url='',instagram='')],
            'products.csv':[dict(product_id='p',persian_title='گوشی تست',brand_name='سامسونگ',category_name='گوشی موبایل',model='A55',specs='[]',image_urls='[]')],
            'offers.csv':[dict(offer_id='o'+str(i),product_id='p',shop_id='s',seller_title='عنوان',description='',price_toman=str(price+i),warranty='null',last_price_changed_at='') for i in range(4)]}
        with zipfile.ZipFile(self.source,'w') as archive:
            for name,rows in tables.items():
                stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
                archive.writestr('nested/'+name,stream.getvalue())
    def run_import(self,**kwargs):
        out=io.StringIO();call_command('import_torob',str(self.source),batch_size=1,stdout=out,**kwargs);return out.getvalue()
    def test_full_import_progress_and_completed_source_is_skipped(self):
        output=self.run_import();self.assertIn('rows committed',output);self.assertIn('Search index: ready',output)
        self.assertEqual((Shop.objects.count(),Product.objects.count(),Offer.objects.count()),(1,1,4))
        with patch.object(Command,'bulk',side_effect=AssertionError('must skip')):
            self.assertIn('Skipping import',self.run_import())
    def test_interrupted_import_resumes_after_last_atomic_batch(self):
        original=Command.bulk
        def interrupt(command,model,objects):
            if model is Offer and objects and objects[0].id=='o1':raise RuntimeError('simulated interruption')
            return original(command,model,objects)
        with patch.object(Command,'bulk',interrupt),self.assertRaises(RuntimeError):self.run_import()
        self.assertEqual(Offer.objects.count(),1)
        self.assertEqual(ImportState.objects.get().progress['Offers']['processed'],1)
        self.assertIn('committed row 1',self.run_import())
        self.assertEqual(Offer.objects.count(),4);self.assertTrue(ImportState.objects.get().completed)
    def test_changed_dataset_and_force_refresh_existing_ids(self):
        self.run_import();self.write_zip(500);self.run_import()
        self.assertEqual(Offer.objects.get(id='o0').price_toman,500)
        self.assertEqual(ImportState.objects.count(),2)
        with patch.object(Command,'bulk',wraps=Command().bulk) as bulk:self.run_import(force=True);self.assertGreater(bulk.call_count,0)
    def test_second_import_cannot_run_concurrently(self):
        from django.core.management.base import CommandError
        with Command().exclusive(),self.assertRaises(CommandError):self.run_import()

class PreferenceAuditTests(SimpleTestCase):
    def test_headphone_is_not_phone(self):self.assertEqual(infer('headphone sony')['category'],'هدفون، هدست و هندزفری')
    def test_shared_budget_range_is_parsed(self):
        p=infer('گوشی بین ۲۰ تا ۳۰ میلیون تومان');self.assertEqual((p['budget_min'],p['budget_max']),(20000000,30000000))
    def test_laptop_model_is_kept(self):self.assertEqual(infer('لپ تاپ لنوو ideapad slim 3 تا ۸۰ میلیون')['query'],'ideapad slim 3')
    def test_need_followup_does_not_erase_model(self):self.assertEqual(infer('برای عکاسی و باتری',{'category':'گوشی موبایل','query':'a55'})['query'],'a55')
    def test_research_finds_battery_outside_first_24_specs(self):
        product={'specs':[{'key':'other'+str(i),'value':'x'} for i in range(30)]+[{'key':'ظرفیت باتری','value':'5000 mAh'}]}
        attach_research([product],{'needs':'باتری'})
        self.assertEqual(product['research']['relevant_specs'][0]['value'],'5000 mAh')
    def test_unknown_research_is_not_invented(self):
        p={'specs':[]};attach_research([p],{'needs':'عکاسی'});self.assertEqual(p['research']['needs'][0]['status'],'unknown')
    def test_installment_channel_is_never_assumed(self):
        providers={'installment':{'providers':[{'name':'ترب‌پی'}]}}
        self.assertEqual(payments_for(providers)[0]['channel'],'unknown')
        raw=fixture();raw['sellers'][0].update(providers)
        self.assertIsNone(normalize_live_product(raw,{'installment':True}))
    def test_live_brand_is_a_hard_filter(self):
        market={'products':[{'id':PID,'title':'گوشی شیائومی','price_toman':100}]}
        with patch('shopping.services.live.search_live',return_value=market),patch('shopping.services.live.raw_product') as details:
            result=search_live_in_person({'brand':'سامسونگ'})
        self.assertEqual(result['checked_product_count'],0);details.assert_not_called()
    def test_seller_description_is_not_automatically_warranty(self):
        raw=fixture();raw['sellers']=raw['sellers'][1:2]
        self.assertIsNone(normalize_live_product(raw,{})['best_offer']['warranty'])
    def test_live_offer_details_validate_product_offer_and_current_filters(self):
        with patch('shopping.services.live.raw_product',return_value=fixture()),patch('shopping.services.live.enrich_offer',side_effect=lambda offer,pid:offer):
            self.assertIsNone(live_offer_detail(PID,'torob_offer_offer-one',{'budget_max':1}))
            self.assertIsNone(live_offer_detail(PID,'not-a-seller',{}))
            self.assertIsNotNone(live_offer_detail(PID,'torob_offer_offer-one',{}))

class DatasetAuditTests(TestCase):
    def setUp(self):
        self.client=APIClient();self.hours={'thu':{'status':'declared','shifts':[{'start_time':'10:00','end_time':'20:00'}]}}
        self.shop=Shop.objects.create(id='s',name='shop',weekly_hours=self.hours,lat=35.7,lon=51.4)
        self.product=Product.objects.create(id='p',title='گوشی سامسونگ',brand='سامسونگ',category='گوشی موبایل',search_text='گوشی سامسونگ')
        Offer.objects.create(id='o',shop=self.shop,product=self.product,price_toman=100)
    def test_dataset_respects_requested_visit_time(self):
        from shopping.services.search import search_products
        closed=search_products({'visit_at':datetime(2026,10,22,18,tzinfo=timezone.utc),'only_open':True})
        opened=search_products({'visit_at':datetime(2026,10,22,12,tzinfo=timezone.utc),'only_open':True})
        self.assertEqual(closed['matched_count'],0);self.assertEqual(opened['matched_count'],1)
    def test_dataset_details_keep_budget_filter(self):
        response=self.client.post('/api/products/p/',{'preferences':{'budget_max':99}},format='json')
        self.assertEqual(response.status_code,404)
    def test_unknown_coordinates_receive_no_nearness_bonus(self):
        from shopping.services.search import search_products
        unknown=Shop.objects.create(id='u',name='unknown')
        Offer.objects.create(id='unknown',shop=unknown,product=self.product,price_toman=100)
        result=search_products({},location={'lat':35.7,'lon':51.4})
        self.assertEqual(result['products'][0]['best_offer']['id'],'o')
