"""Agent contracts: actual tool loop + real fixture database, model replies controlled."""
from copy import deepcopy
from unittest.mock import patch
from django.test import TestCase,SimpleTestCase,override_settings
from django.core.cache import cache
from django.core import signing
from rest_framework.test import APIClient
from .models import Product,Shop,Offer
from .services.agent import run,patch_preferences
from .services.agent_tools import ShoppingTools,ToolInputError
from .services.agent_evidence import seal,unseal,catalogue,render_comparison,eligible
from .services.live import LiveSearchError

PREFS={'search_mode':'dataset','category':'گوشی موبایل','budget_max':150000000,'color_any':True,'needs':'عکاسی'}

def tool(name,args=None,**extra):return {'action':'tool','tool':{'name':name,'arguments':args or {}},**extra}
def ask(text='کاربردت چیست؟',**extra):return {'action':'ask','answer':'برای انتخاب دقیق‌تر، این مورد را مشخص کنیم.','questions':[{'key':'needs','text':text,'choices':[]}],**extra}

def final(payload,compare=False):
    cards=payload['evidence']['products'];facts=payload['evidence']['facts'];ids=[p['id'] for p in cards]
    choices={p['id']:p['offers'][-1]['id'] for p in cards}
    refs={p['id']:p['offers'][-1]['facts']['price'] for p in cards}
    a={'action':'final','answer':'داده‌های ثبت‌شده را با اولویت عکاسی مقایسه کردم؛ موجودی و مدل را پیش از خرید تطبیق بده.',
       'ranking':list(reversed(ids)),'offer_choices':choices,
       'product_analysis':[{'product_id':i,'verdict':'این گزینه با بودجه ثبت‌شده سازگار است.','supporting_fact_ids':[refs[i]],'unknowns':['تست عملی دوربین ثبت نشده']} for i in ids]}
    if compare:a['comparison']={'product_ids':ids[:2],'rows':[{'label':'قیمت همان فروشنده (تومان)','fact_refs':{i:refs[i] for i in ids[:2]},'winner_id':None,'explanation':'گارانتی و وضعیت باید یکسان باشد.'}], 'winner_id':ids[-1], 'verdict':'با توجه به نیاز اعلامی، گزینه منتخب مدل را بررسی کن.','limits':'آزمون عملی نداریم.'}
    return a

@override_settings(LLM_ENABLED=True,LLM_BASE_URL='http://localhost:9999/v1',LLM_MODEL='test-model',LLM_API_KEY='',AGENT_MAX_STEPS=6,AGENT_MAX_TOOLS=4)
class AgentLoopTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for i in range(2):
            shop=Shop.objects.create(id='s'+str(i),name='فروشگاه '+str(i),lat=35.7,lon=51.4)
            p=Product.objects.create(id='p'+str(i),title='گوشی A'+str(i),category='گوشی موبایل',search_text='گوشی a'+str(i),specs=[{'key':'ظرفیت باتری','value':5000+i},{'key':'حافظه رم','value':'8 GB'}])
            for j in range(2):Offer.objects.create(id='o'+str(i)+str(j),product=p,shop=shop,price_toman=100000000+i*1000000+j*5000000,seller_title=p.title,description='مشکی آکبند',warranty='گارانتی اعلامی')
    def setUp(self):cache.clear();self.client=APIClient()
    def execute(self,actions,**data):
        def model(system,payload,**kwargs):
            self.assertIn('tools',payload);a=next(actions)
            return a(payload) if callable(a) else a
        with patch('shopping.services.agent.llm.json_call',side_effect=model) as call:
            result=run({'message':'برای عکاسی مقایسه کن','preferences':PREFS,**data})
        return result,call
    def test_model_selects_tool_then_rank_and_seller_instead_of_heuristic(self):
        result,call=self.execute(iter([tool('search_products'),lambda p:final(p,True)]))
        self.assertEqual(call.call_count,2);self.assertEqual(result['agent']['tool_calls'],1)
        self.assertEqual(result['agent']['status'],'complete');self.assertEqual(result['llm']['mode'],'agentic')
        p=result['products'][0];self.assertEqual(p['id'],'p1');self.assertEqual(p['best_offer']['id'],'o11')
        self.assertIsNone(p['score']);self.assertEqual(p['ai_rank'],1)
        values=[c['value'] for c in result['comparison']['rows'][0]['cells']]
        self.assertEqual(values,['105000000','106000000'])
    def test_endpoint_uses_model_for_clarification_without_calling_search(self):
        with patch('shopping.services.agent.llm.json_call',return_value=ask('بودجه و رنگ دلخواهت چیست؟')),patch('shopping.services.agent_tools.search_products') as search:
            r=self.client.post('/api/agent/chat/',{'message':'یک گوشی می‌خواهم'},format='json')
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['agent']['status'],'awaiting_input');self.assertFalse(r.json()['llm']['analysis_used']);search.assert_not_called()
    def test_preference_update_by_ai_then_search_keeps_answered_color(self):
        r,_=self.execute(iter([tool('search_products',preferences_patch={'color':'مشکی','color_any':False},evidence_quotes={'color':'مشکی','color_any':'مشکی'}),final]),message='مشکی')
        self.assertEqual(r['preferences']['color'],'مشکی');self.assertEqual(r['agent']['status'],'complete')
    def test_invalid_hard_filter_relaxation_is_returned_to_model_for_repair(self):
        r,c=self.execute(iter([tool('search_products',preferences_patch={'budget_any':True}),tool('search_products'),final]))
        self.assertEqual(r['preferences']['budget_max'],150000000);self.assertEqual(c.call_count,3)
        self.assertEqual(r['agent']['events'][0]['status'],'rejected')
    def test_unknown_tool_cannot_execute_arbitrary_requests(self):
        r,_=self.execute(iter([tool('shell',{'cmd':'anything'}),ask()]))
        self.assertEqual(r['agent']['status'],'awaiting_input');self.assertEqual(r['agent']['events'][0]['status'],'rejected')
    def test_hallucinated_ranking_is_repaired(self):
        def forged(p):
            a=final(p);a['ranking']=['invented'];return a
        r,c=self.execute(iter([tool('search_products'),forged,final]))
        self.assertEqual(c.call_count,3);self.assertEqual(r['agent']['status'],'complete');self.assertNotIn('invented',[p['id'] for p in r['products']])
    def test_cross_product_facts_are_rejected_and_repaired(self):
        def crossed(p):
            a=final(p,True);row=a['comparison']['rows'][0];row['fact_refs']['p0']=row['fact_refs']['p1'];return a
        r,c=self.execute(iter([tool('search_products'),crossed,lambda p:final(p,True)]))
        self.assertEqual(c.call_count,3);self.assertEqual(r['agent']['status'],'complete')
    def test_foreign_seller_is_rejected(self):
        def bad(p):
            a=final(p);a['offer_choices']['p0']='o10';return a
        r,c=self.execute(iter([tool('search_products'),bad,final]));self.assertEqual(c.call_count,3);self.assertEqual(r['agent']['status'],'complete')
    @override_settings(AGENT_MAX_STEPS=3,AGENT_MAX_TOOLS=2)
    def test_identical_tools_are_cached_and_total_actions_are_bounded(self):
        with patch('shopping.services.agent_tools.search_products',wraps=__import__('shopping.services.search',fromlist=['search_products']).search_products) as search:
            r,c=self.execute(iter([tool('search_products'),tool('search_products'),final]))
        self.assertEqual(search.call_count,1);self.assertEqual(c.call_count,3);self.assertTrue(r['agent']['events'][1]['reused'])
    @override_settings(AGENT_MAX_STEPS=2)
    def test_invalid_repeating_model_never_becomes_fake_ai_analysis(self):
        r,c=self.execute(iter([tool('unknown'),tool('unknown')]))
        self.assertEqual(c.call_count,2);self.assertEqual(r['agent']['status'],'unavailable');self.assertIsNone(r['analysis'])
    def test_provider_failure_preserves_data_without_ai_badges(self):
        r,_=self.execute(iter([tool('search_products'),None]))
        self.assertEqual(r['agent']['status'],'unavailable');self.assertFalse(r['llm']['analysis_used']);self.assertEqual(r['llm']['mode'],'unavailable')
        self.assertTrue(r['products']);self.assertTrue(all(p['score'] is None and not p['badges'] for p in r['products']))
    @override_settings(LLM_ENABLED=False)
    def test_no_model_means_explicit_unavailable_and_no_network(self):
        with patch('shopping.services.agent_tools.search_live_in_person') as search:
            r=run({'message':'گوشی می‌خواهم'})
        self.assertEqual(r['agent']['status'],'unavailable');self.assertEqual(r['agent']['model_calls'],0);search.assert_not_called()
    def test_live_failure_is_observation_not_zero_stock_or_dataset_fallback(self):
        def report(payload):
            self.assertEqual(payload['observations'][-1]['result']['status'],'torob_timeout');return ask('اتصال ترب ناموفق بود؛ دوباره تلاش کنیم یا فایل داده را انتخاب می‌کنی؟')
        with patch('shopping.services.agent_tools.search_live_in_person',side_effect=LiveSearchError('timeout','torob_timeout')),patch('shopping.services.agent_tools.search_products') as dataset:
            r,_=self.execute(iter([tool('search_products'),report]),preferences={**PREFS,'search_mode':'live'})
        self.assertEqual(r['source'],'torob_unavailable');dataset.assert_not_called()
    def test_all_failed_live_details_are_inconclusive_not_zero_matches(self):
        result={'products':[],'matched_count':0,'checked_product_count':3,'detail_failures':3,'source':'torob_live'}
        def report(payload):
            self.assertEqual(payload['observations'][-1]['result']['status'],'partial');return ask('جزئیات دریافت نشد؛ دوباره تلاش کنیم؟')
        with patch('shopping.services.agent_tools.search_live_in_person',return_value=result):
            r,_=self.execute(iter([tool('search_products'),report]),preferences={**PREFS,'search_mode':'live'})
        self.assertEqual(r['source'],'torob_unavailable')
    def test_signed_evidence_supports_followup_across_requests(self):
        first,_=self.execute(iter([tool('search_products'),final]))
        second,c=self.execute(iter([lambda p:final(p,True)]),message='دومی با اولی چه فرقی دارد؟',agent_state=first['agent_state'])
        self.assertEqual(c.call_count,1);self.assertEqual(second['agent']['state_status'],'ok');self.assertIsNotNone(second['comparison'])
    def test_ui_comparison_refreshes_canonical_ids_without_client_records(self):
        r,_=self.execute(iter([tool('get_products',{'product_ids':['p0','p1']}),lambda p:final(p,True)]),comparison_ids=['p0','p1'])
        self.assertEqual(r['comparison']['product_ids'],['p0','p1'])
    def test_selected_comparison_without_table_requires_model_repair(self):
        r,c=self.execute(iter([tool('get_products',{'product_ids':['p0','p1']}),final,lambda p:final(p,True)]),comparison_ids=['p0','p1'])
        self.assertEqual(c.call_count,3);self.assertTrue(r['comparison'])
    def test_unknown_selected_product_cannot_be_invented(self):
        r,_=self.execute(iter([tool('get_products',{'product_ids':['unknown']}),ask('این محصول در منبع موجود نیست؛ دوباره انتخاب می‌کنی؟')]),comparison_ids=['unknown'])
        self.assertFalse(r['products']);self.assertEqual(r['agent']['status'],'awaiting_input')
    def test_latest_user_history_not_provider_credentials_is_in_model_payload(self):
        r,c=self.execute(iter([ask()]),history=[{'role':'user','content':'برای بازی می‌خواهم'}])
        payload=c.call_args.args[1];self.assertEqual(payload['history'][0]['content'],'برای بازی می‌خواهم');self.assertNotIn('api_key',str(payload).lower())
    def test_location_not_sent_as_coordinates_to_llm_or_stored_in_state(self):
        r,c=self.execute(iter([tool('search_products'),final]),location={'lat':35.723456789,'lon':51.487654321,'approximate':False,'label':'موقعیت فعلی'})
        self.assertNotIn('35.723456789',str(c.call_args.args[1]));saved,_=unseal(r['agent_state'])
        self.assertNotIn('35.723456789',str(saved));self.assertTrue(all(o['distance_km'] is None for p in saved for o in p['offers']))
    @override_settings(SERPER_API_KEY='')
    def test_model_receives_honest_missing_google_configuration(self):
        def reply(p):self.assertEqual(p['evidence']['web_research']['status'],'not_configured');return ask()
        r,_=self.execute(iter([tool('web_search',{'query':'بررسی دوربین'}),reply]));self.assertEqual(r['web_research']['status'],'not_configured')
    def test_user_price_sort_overrides_ai_order(self):
        r,_=self.execute(iter([tool('search_products'),final]),preferences={**PREFS,'sort':'price'})
        self.assertEqual([p['id'] for p in r['products']],['p0','p1'])
    def test_expired_state_reports_expired(self):
        with patch('django.core.signing.time.time',return_value=1):token=seal([])
        r,_=self.execute(iter([ask()]),agent_state=token);self.assertEqual(r['agent']['state_status'],'expired')
    def test_user_shop_quote_difference_uses_canonical_offer_price(self):
        r,_=self.execute(iter([tool('search_products'),tool('compare_quote',{'product_id':'p0','quote_toman':120000000,'evidence_quote':'۱۲۰ میلیون تومان'}),final]),message='فروشنده ۱۲۰ میلیون تومان گفته')
        q=r['calculations'][0];self.assertEqual(q['quoted_toman'],120000000);self.assertEqual(q['offers'][0]['difference_toman'],20000000)
    def test_visit_quote_keeps_user_declared_source(self):
        r,_=self.execute(iter([tool('search_products'),tool('compare_quote',{'product_id':'p0'}),final]),visit={'quoted_price':125000000})
        self.assertEqual(r['calculations'][0]['quoted_source'],'user_declared');self.assertEqual(r['calculations'][0]['offers'][0]['difference_toman'],25000000)
    def test_tampered_state_is_never_used(self):
        token=seal([])+'bad';r,_=self.execute(iter([ask()]),agent_state=token)
        self.assertEqual(r['agent']['state_status'],'invalid');self.assertFalse(r['products'])

class PaymentToolTests(SimpleTestCase):
    def test_total_is_computed_with_exact_integers_and_fees(self):
        t=ShoppingTools({},None,[],[],'نقدی ۱۰ میلیون تومان، پیش ۲ میلیون، ۱۰ قسط ۱ میلیون، کارمزد ۵۰۰ هزار تومان')
        result=t.run('calculate_payments',{'cash':10000000,'down':2000000,'monthly':1000000,'count':10,'fees':500000,'evidence_quote':t.message})
        self.assertEqual(result['calculation']['total_toman'],12500000);self.assertEqual(result['calculation']['extra_percent'],'25.00')
    def test_unstated_fee_cannot_be_assumed_zero(self):
        t=ShoppingTools({},None,[],[],'نقدی ۱۰ میلیون تومان، پیش ۲ میلیون، ۱۰ قسط ۱ میلیون')
        with self.assertRaises(ToolInputError):t.run('calculate_payments',{'cash':10000000,'down':2000000,'monthly':1000000,'count':10,'fees':0,'evidence_quote':t.message})
    def test_arbitrary_urls_or_tool_args_are_rejected(self):
        t=ShoppingTools({},None,[],[],'')
        with self.assertRaises(ToolInputError):t.run('web_search',{'url':'http://localhost/private'})
    def test_comparison_malformed_ids_do_not_raise_uncontrolled_type_error(self):
        with self.assertRaises(ValueError):render_comparison({'product_ids':[{},{}]}, {},{})
    def test_memory_number_cannot_be_used_as_a_monetary_budget(self):
        with self.assertRaises(ValueError):patch_preferences({}, {'preferences_patch':{'budget_max':256},'evidence_quotes':{'budget_max':'حافظه ۲۵۶ گیگ'}},'حافظه ۲۵۶ گیگ')
    def test_budget_range_and_rials_are_checked_against_actual_user_units(self):
        a={'preferences_patch':{'budget_min':2000000,'budget_max':3000000},'evidence_quotes':{'budget_min':'بین ۲۰ تا ۳۰ میلیون ریال','budget_max':'بین ۲۰ تا ۳۰ میلیون ریال'}}
        self.assertEqual(patch_preferences({},a,'بین ۲۰ تا ۳۰ میلیون ریال')['budget_max'],3000000)
    def test_zero_down_payment_does_not_prove_zero_fees(self):
        t=ShoppingTools({},None,[],[],'نقدی ۱۰ میلیون تومان، بدون پیش پرداخت، ۱۰ قسط ۱ میلیون تومان')
        with self.assertRaises(ToolInputError):t.run('calculate_payments',{'cash':10000000,'down':0,'monthly':1000000,'count':10,'fees':0,'evidence_quote':t.message})

class NetworkBudgetTests(SimpleTestCase):
    def test_expired_budget_is_propagated_to_worker_and_reset_afterwards(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        from .services.request_budget import within,submit,http_timeout,BudgetExceeded
        with within(time.monotonic()-1):
            with ThreadPoolExecutor(max_workers=1) as pool:
                with self.assertRaises(BudgetExceeded):submit(pool,http_timeout,3,10).result()
        self.assertEqual(http_timeout(3,10),(3,10))
