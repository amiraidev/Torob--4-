"""Contract tests for BoxAPI errors, grounded analysis, and the Django chat path."""
import io
import json
from unittest.mock import patch

import requests
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from shopping.models import Product, Offer, Shop
from shopping.services import llm
from shopping.services.live import LiveSearchError
from shopping.services.search import search_products


CONFIG = dict(LLM_ENABLED=True, LLM_BASE_URL='https://ai.boxapi.ir/ai/v1',
              LLM_MODEL='prism-ml/ternary-bonsai-2-27b', LLM_API_KEY='private-test-key',
              LLM_JSON_MODE=False)


def provider_response(content, code=200):
    response = requests.Response()
    response.status_code = code
    response._content = json.dumps({'choices': [{'message': {'content': content},
                                                 'finish_reason': 'stop'}]}).encode()
    return response


@override_settings(**CONFIG)
class BoxAPIClientTests(SimpleTestCase):
    def test_placeholder_or_blank_key_never_calls_provider(self):
        for key in ['', 'PASTE_YOUR_BOXAPI_KEY_HERE', 'YOUR_API_KEY']:
            with self.subTest(key=key), override_settings(LLM_API_KEY=key), patch.object(llm.requests, 'post') as post:
                status = llm.request_status()
                self.assertFalse(llm.enabled())
                self.assertIsNone(llm.json_call('system', {}, status=status))
                self.assertEqual(llm.public_status(status)['status'], 'missing_key')
                post.assert_not_called()

    def test_provider_errors_are_distinct_and_do_not_disclose_response_or_key(self):
        codes = {401: 'authentication_failed', 402: 'insufficient_credit', 403: 'access_denied',
                 404: 'model_unavailable', 429: 'rate_limited', 503: 'provider_unavailable'}
        for code, expected in codes.items():
            with self.subTest(code=code), patch.object(llm.requests, 'post',
                    return_value=provider_response('SECRET provider response private-test-key', code)) as post:
                status = llm.request_status()
                self.assertIsNone(llm.json_call('system', {}, status=status))
                public = llm.public_status(status)
                self.assertEqual(public['status'], expected)
                self.assertNotIn('private-test-key', json.dumps(public))
                self.assertNotIn('SECRET', json.dumps(public))
                self.assertEqual(post.call_count, 1)

    def test_timeout_uses_rules_and_is_not_reported_as_success(self):
        with patch.object(llm.requests, 'post', side_effect=requests.Timeout):
            status = llm.request_status()
            llm.json_call('system', {}, status=status)
        self.assertEqual(llm.public_status(status)['status'], 'timeout')
        self.assertFalse(llm.public_status(status)['used'])

    def test_reasoning_fences_and_content_blocks_parse_without_json_mode(self):
        variants = ['{"preferences":{"needs":"بازی"}}',
                    '<think>private reasoning</think>\n```json\n{"preferences":{"needs":"بازی"}}\n```',
                    [{'type': 'text', 'text': '{"preferences":{"needs":"بازی"}}'}]]
        for content in variants:
            with self.subTest(content=content), patch.object(llm.requests, 'post',
                    return_value=provider_response(content)):
                prefs, used = llm.extract('برای بازی', {'query': 'a55'}, [])
                self.assertTrue(used)
                self.assertEqual(prefs['query'], 'a55')
                self.assertEqual(prefs['needs'], 'بازی')

    def test_invalid_or_truncated_json_is_a_controlled_failure(self):
        for content in ['[1,2,3]', '{"broken":', None, '']:
            with self.subTest(content=content), patch.object(llm.requests, 'post',
                    return_value=provider_response(content)):
                status = llm.request_status()
                self.assertIsNone(llm.json_call('system', {}, status=status))
                self.assertEqual(llm.public_status(status)['status'], 'invalid_response')

    def test_model_cannot_change_source_visit_radius_or_location(self):
        with patch.object(llm, 'json_call', return_value={'preferences': {
                'needs': 'تدوین', 'search_mode': 'live', 'radius_km': 200,
                'visit_at': '2030-01-01T00:00:00Z', 'location': {'lat': 1}}}):
            prefs, used = llm.extract('برای تدوین', {'search_mode': 'dataset', 'radius_km': 2}, [])
        self.assertTrue(used)
        self.assertEqual(prefs['search_mode'], 'dataset')
        self.assertEqual(prefs['radius_km'], 2)
        self.assertIsNone(prefs['visit_at'])
        self.assertNotIn('location', prefs)

    def test_explicit_any_preference_clears_its_prior_filter(self):
        with patch.object(llm, 'json_call', return_value={'preferences': {
                'brand_any': True, 'color_any': True, 'budget_any': True}}):
            prefs, used = llm.extract('محدودیت ندارم', {
                'brand': 'سامسونگ', 'color': 'مشکی', 'budget_min': 100, 'budget_max': 200}, [])
        self.assertTrue(used)
        self.assertEqual((prefs['brand'], prefs['color'], prefs['budget_min'], prefs['budget_max']), ('', '', 0, None))

    def test_invalid_numeric_preferences_cannot_replace_existing_budget(self):
        with patch.object(llm, 'json_call', return_value={'preferences': {'budget_max': -1}}):
            prefs, used = llm.extract('عکاسی', {'budget_max': 200}, [])
        self.assertFalse(used)
        self.assertEqual(prefs['budget_max'], 200)

    def test_insecure_remote_or_embedded_credentials_rejected(self):
        for base in ['http://ai.boxapi.ir/ai/v1', 'https://user:secret@ai.boxapi.ir/ai/v1',
                     'https://ai.boxapi.ir/ai/v1?key=secret', 'https://[bad']:
            with self.subTest(base=base), override_settings(LLM_BASE_URL=base):
                self.assertEqual(llm.public_status(llm.request_status())['status'], 'invalid_configuration')
                self.assertFalse(llm.enabled())

    def test_connection_check_has_safe_output_and_returns_error_without_key(self):
        output = io.StringIO()
        with patch.object(llm, 'json_call', return_value={'ok': True}):
            call_command('check_llm', stdout=output)
        self.assertIn('OK', output.getvalue())
        self.assertNotIn('private-test-key', output.getvalue())
        with override_settings(LLM_API_KEY=''), self.assertRaises(CommandError):
            call_command('check_llm', stdout=io.StringIO())


@override_settings(**CONFIG)
class BoxAPIChatTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        shop = Shop.objects.create(id='s', name='فروشگاه ثبت‌شده', lat=35.7, lon=51.4,
                                   contacts=[{'channel': 'phone', 'display_number': 'PRIVATE_CONTACT'}])
        for number, memory in [(1, '16 GB'), (2, '32 GB')]:
            product = Product.objects.create(id='p' + str(number), title='لپ تاپ تست ' + str(number),
                category='لپ تاپ و نوت بوک', search_text='لپ تاپ تست',
                specs=[{'key': 'حافظه رم', 'value': memory}])
            Offer.objects.create(id='o' + str(number), product=product, shop=shop,
                                 price_toman=number * 100)

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.prefs = {'search_mode': 'dataset', 'category': 'لپ تاپ و نوت بوک',
                      'needs': 'برنامه نویسی', 'budget_max': 300, 'color_any': True}
        self.answer = {
            'explanation': 'مشخصات ثبت‌شده را برای برنامه‌نویسی مقایسه کردم.',
            'ranked_product_ids': ['invented', 'p2', 'p2', 'p1'],
            'product_analysis': [
                {'product_id': 'p2', 'verdict': 'برای مقایسه ظرفیت رم، این گزینه را بررسی کن.',
                 'supporting_spec_keys': ['حافظه رم', 'ویژگی ساختگی'],
                 'supporting_specs': [{'key': 'حافظه رم', 'value': 'FAKE_VALUE'}],
                 'price_toman': 1, 'tradeoff': 'زمان کارکرد باتری در داده ثبت نشده است.',
                 'unknowns': ['وضعیت نو یا کارکرده را از فروشنده بپرس.']},
                {'product_id': 'invented', 'verdict': 'محصول ساختگی'}],
            'follow_up': {'key': 'technical', 'text': 'وزن دستگاه برایت مهم است؟',
                          'choices': ['سبک باشد', 'وزن مهم نیست']},
            'shopping_tips': ['موجودی و گارانتی همین پیشنهاد را پیش از مراجعه تأیید کن.'],
        }

    def post(self, message='', **prefs):
        return self.client.post('/api/chat/', {
            'message': message, 'preferences': {**self.prefs, **prefs}}, format='json')

    def test_filter_only_request_analyzes_real_results_and_attaches_canonical_specs(self):
        with patch.object(llm, 'json_call', return_value=self.answer) as call:
            response = self.post()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(call.call_count, 1)  # No needless extraction for a filter change.
        self.assertTrue(data['llm']['analysis_used'])
        self.assertFalse(data['llm']['extraction_used'])
        self.assertEqual([p['id'] for p in data['products']], ['p2', 'p1'])
        product = data['products'][0]
        self.assertEqual(product['best_offer']['price_toman'], 200)
        self.assertEqual(product['ai_analysis']['supporting_specs'], [{'key': 'حافظه رم', 'value': '32 GB'}])
        self.assertEqual(data['questions'][0]['key'], 'technical')
        self.assertEqual(data['analysis']['ranked_product_ids'], ['p2', 'p1'])
        self.assertNotIn('PRIVATE_CONTACT', json.dumps(call.call_args.args[1]))

    def test_analysis_is_independent_of_failed_preference_extraction(self):
        with patch.object(llm, 'json_call', side_effect=[None, self.answer]) as call:
            data = self.post('برای برنامه نویسی').json()
        self.assertEqual(call.call_count, 2)
        self.assertFalse(data['llm']['extraction_used'])
        self.assertTrue(data['llm']['analysis_used'])
        self.assertEqual(data['reply'], self.answer['explanation'])

    def test_extraction_success_does_not_claim_successful_product_analysis(self):
        with patch.object(llm, 'json_call', side_effect=[{'preferences': {}}, None]):
            data = self.post('برای برنامه نویسی').json()
        self.assertTrue(data['llm']['extraction_used'])
        self.assertFalse(data['llm']['analysis_used'])
        self.assertIsNone(data['analysis'])
        self.assertIn('مشخصاتِ پیشنهاد اول', data['reply'])

    def test_explicit_price_and_distance_sort_cannot_be_overridden_by_model_ranking(self):
        for order in ['price', 'distance']:
            with self.subTest(order=order), patch.object(llm, 'json_call', return_value=self.answer):
                data = self.post(sort=order).json()
            self.assertEqual([p['id'] for p in data['products']], ['p1', 'p2'])
            self.assertEqual(data['analysis']['ranked_product_ids'], ['p1', 'p2'])

    def test_model_cannot_add_over_budget_results_or_fabricate_no_results_reply(self):
        with patch.object(llm, 'json_call', return_value=self.answer):
            data = self.post(budget_max=99).json()
        self.assertEqual(data['products'], [])
        self.assertEqual(data['analysis']['ranked_product_ids'], [])
        self.assertEqual(data['analysis']['product_analysis'], [])
        self.assertNotEqual(data['reply'], self.answer['explanation'])
        self.assertIn('پیدا نشد', data['reply'])

    @override_settings(TOROB_FALLBACK_TO_DATASET=False)
    def test_live_connection_failure_is_not_misreported_as_no_stock_by_model(self):
        with patch('shopping.views.search_live_in_person', side_effect=LiveSearchError('اتصال ناموفق')), \
                patch.object(llm, 'json_call', return_value=self.answer):
            data = self.post(search_mode='live').json()
        self.assertEqual(data['source'], 'torob_unavailable')
        self.assertEqual(data['products'], [])
        self.assertIn('جستجوی زنده انجام نشد', data['reply'])

    def test_provider_auth_failure_preserves_http_200_and_real_product_data(self):
        with patch.object(llm.requests, 'post', return_value=provider_response('private-test-key', 401)):
            response = self.post()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['llm']['status'], 'authentication_failed')
        self.assertFalse(data['llm']['analysis_used'])
        self.assertEqual(len(data['products']), 2)
        self.assertNotIn('private-test-key', json.dumps(data))

    def test_malformed_analysis_fields_do_not_crash_chat(self):
        malformed = {**self.answer, 'product_analysis': [{'product_id': ['bad']}],
                     'ranked_product_ids': {'bad': 1},
                     'follow_up': {'key': ['bad'], 'text': 'سؤال', 'choices': [None, 5, {}, 'بازی']}}
        with patch.object(llm, 'json_call', return_value=malformed):
            response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['questions'][0]['choices'], ['بازی'])

    @override_settings(LLM_API_KEY='PASTE_YOUR_BOXAPI_KEY_HERE')
    def test_public_health_reports_placeholder_as_unconfigured_and_chat_remains_usable(self):
        with patch.object(llm.requests, 'post') as post:
            health = self.client.get('/api/health/').json()
            data = self.post().json()
        self.assertFalse(health['llm_configured'])
        self.assertEqual(health['llm_provider'], 'BoxAPI')
        self.assertEqual(health['llm_status'], 'missing_key')
        self.assertFalse(data['llm']['analysis_used'])
        self.assertEqual(len(data['products']), 2)
        post.assert_not_called()

