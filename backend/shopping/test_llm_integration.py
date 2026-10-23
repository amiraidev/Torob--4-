"""Exercise the actual HTTP client against a local OpenAI-compatible test server."""
import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from django.test import SimpleTestCase,override_settings
from shopping.services import llm
from shopping.services.research import attach_research
from shopping.test_live_agent import fixture
from shopping.services.live import normalize_live_product

class LLMHTTPTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                cls.last_request={'path':self.path,'body':body,'authorization':self.headers.get('Authorization')}
                if body['messages'][0]['content'].startswith('You extract'):
                    content={'preferences':{'needs':'باتری','budget_max':100000000,'search_mode':'dataset','visit_at':'2030-01-01T00:00:00Z'}}
                else:
                    evidence=json.loads(body['messages'][1]['content'])['evidence']
                    content={'explanation':'مشخصات ثبت‌شده را با بودجه و فاصله مقایسه کن.','ranked_product_ids':['invented',evidence[0]['product_id'],evidence[0]['product_id']]}
                    cls.last_evidence=evidence
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(json.dumps({'choices':[{'message':{'content':json.dumps(content)}}]}).encode())
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();super().tearDownClass()
    def config(self):return override_settings(LLM_ENABLED=True,LLM_MODEL='test-model',LLM_API_KEY='test-only',LLM_BASE_URL=f'http://127.0.0.1:{self.server.server_port}/v1')
    def test_actual_http_extraction_keeps_server_controlled_source_and_visit(self):
        with self.config():prefs,used=llm.extract('باتری خوب',{'search_mode':'live','visit_at':None},[])
        self.assertTrue(used);self.assertEqual(prefs['needs'],'باتری');self.assertEqual(prefs['search_mode'],'live');self.assertIsNone(prefs['visit_at'])
    def test_actual_http_explanation_gets_relevant_specs_and_only_existing_ids_rank(self):
        p=normalize_live_product(fixture(),{})
        p['specs']=[{'key':'other'+str(i),'value':'x'} for i in range(30)]+[{'key':'ظرفیت باتری','value':'5000 mAh'}]
        attach_research([p],{'needs':'باتری'})
        with self.config():text,order=llm.explain({'needs':'باتری'},[p])
        self.assertTrue(text);self.assertEqual(order,[p['id']]);self.assertEqual(self.last_evidence[0]['specs'][0]['key'],'ظرفیت باتری')
        self.assertNotIn('contacts',json.dumps(self.last_evidence));self.assertNotIn('test-only',json.dumps(self.last_evidence))
    def test_provider_failure_leaves_rule_preferences_usable(self):
        with override_settings(LLM_ENABLED=True,LLM_MODEL='test',LLM_BASE_URL='http://127.0.0.1:1/v1'):
            prefs,used=llm.extract('باتری',{'category':'گوشی موبایل'},[])
        self.assertFalse(used);self.assertEqual(prefs['category'],'گوشی موبایل')
    def test_boxapi_path_model_bearer_and_optional_json_mode(self):
        with self.config(),override_settings(LLM_BASE_URL=f'http://127.0.0.1:{self.server.server_port}/ai/v1',
                LLM_MODEL='prism-ml/ternary-bonsai-2-27b',LLM_JSON_MODE=False):
            prefs,used=llm.extract('برای باتری',{},[])
        self.assertTrue(used)
        self.assertEqual(self.last_request['path'],'/ai/v1/chat/completions')
        self.assertEqual(self.last_request['authorization'],'Bearer test-only')
        self.assertEqual(self.last_request['body']['model'],'prism-ml/ternary-bonsai-2-27b')
        self.assertNotIn('response_format',self.last_request['body'])
        self.assertFalse(self.last_request['body']['stream'])
    def test_optional_bearer_prefix_in_user_key_is_not_duplicated(self):
        with self.config(),override_settings(LLM_API_KEY=' Bearer test-only '):
            prefs,used=llm.extract('برای باتری',{},[])
        self.assertTrue(used)
        self.assertEqual(self.last_request['authorization'],'Bearer test-only')
