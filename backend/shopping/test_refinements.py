from django.test import TestCase,override_settings
from rest_framework.test import APIClient
from .services.intent import infer
from .services.questions import clarifications

class RefinementTests(TestCase):
    def test_google_is_default_and_only_public_browser_keys_are_exposed(self):
        with override_settings(GOOGLE_MAPS_BROWSER_KEY='public-google',GOOGLE_PLACES_API_KEY='private-google',NESHAN_MAP_KEY='public-neshan',NESHAN_SERVICE_KEY='private-neshan'):
            data=APIClient().get('/api/map-config/').json()
        self.assertEqual(data['default_provider'],'google')
        self.assertEqual(data['google_browser_key'],'public-google')
        self.assertNotIn('private',str(data))
    def test_budget_range_without_an_intro_word_still_has_shared_units(self):
        p=infer('بودجه ۲۰ تا ۳۰ میلیون تومان')
        self.assertEqual((p['budget_min'],p['budget_max']),(20000000,30000000))
    def test_budget_choices_use_only_retrieved_prices(self):
        q=clarifications({}, {'market':{'products':[{'price_toman':12670000},{'price_toman':25340000}]}})[0]
        self.assertIn('12,670,000',q['text']);self.assertIn('25,340,000',q['text'])
        self.assertEqual(q['basis'],'retrieved_prices')
    def test_nan_gps_accuracy_does_not_enter_place_providers(self):
        from .serializers import LocationSerializer
        self.assertFalse(LocationSerializer(data={'lat':35.7,'lon':51.4,'accuracy_m':'NaN'}).is_valid())
