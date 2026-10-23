"""Production configuration, catalog bootstrap and honest fallback behavior."""
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from config.environment import load_environment
from shopping.models import Shop, Product, Offer, ImportState
from shopping.services.live import LiveSearchError

ROOT = Path(__file__).resolve().parents[2]


def script_module(name):
    path = ROOT / 'scripts' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrivateConfigurationTests(SimpleTestCase):
    def test_console_commands_apply_the_same_profile_before_loading_django(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                'TOROB_IN_DOCKER':'true','PORT':'80','DJANGO_DB_PATH':'/old/db.sqlite3',
                'DJANGO_SECRET_KEY_FILE':'/old/key','DJANGO_DEBUG':'true'},clear=True):
            root=Path(directory)
            (root/'scripts').mkdir()
            shutil.copyfile(ROOT/'scripts/container_start.py',root/'scripts/container_start.py')
            load_environment(root)
            self.assertEqual(os.environ['PORT'],'8000')
            self.assertEqual(os.environ['DJANGO_DEBUG'],'false')
            self.assertEqual(os.environ['DJANGO_DB_READONLY'],'true')
            self.assertEqual(os.environ['DJANGO_DB_PATH'],str(root/'bootstrap/catalog.sqlite3'))
            self.assertNotEqual(os.environ['DJANGO_SECRET_KEY_FILE'],'/old/key')

    def test_docker_reads_only_llm_settings_and_ignores_stale_panel_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            (root / 'config/runtime.env').write_text(
                'LLM_API_KEY=file-test-only\nLLM_ENABLED=True\nLLM_MODEL=uploaded-model\n'
                'DJANGO_DEBUG=true\nDJANGO_SECRET_KEY=weak-local-only\nDJANGO_ALLOWED_HOSTS=localhost\n')
            with patch.dict(os.environ, {'TOROB_IN_DOCKER': 'true',
                    'LLM_API_KEY': 'stale-panel-test', 'LLM_ENABLED': 'false',
                    'DJANGO_DEBUG': 'false', 'DJANGO_ALLOWED_HOSTS': 'production.example'}, clear=True):
                load_environment(root)
                self.assertEqual(os.environ['LLM_API_KEY'], 'file-test-only')
                self.assertEqual(os.environ['LLM_ENABLED'], 'True')
                self.assertEqual(os.environ['LLM_MODEL'], 'uploaded-model')
                self.assertEqual(os.environ['DJANGO_DEBUG'], 'false')
                self.assertEqual(os.environ['DJANGO_ALLOWED_HOSTS'], 'production.example')
                self.assertNotIn('DJANGO_SECRET_KEY', os.environ)

    def test_explicit_environment_mode_allows_private_key_rotation_from_panel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            (root / 'config/runtime.env').write_text('LLM_API_KEY=file-test-only\n')
            with patch.dict(os.environ, {'TOROB_IN_DOCKER': 'true',
                    'LLM_CONFIG_SOURCE': 'environment', 'LLM_API_KEY': 'rotated-test-only'}, clear=True):
                load_environment(root)
                self.assertEqual(os.environ['LLM_API_KEY'], 'rotated-test-only')

    def test_local_development_keeps_environment_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('LLM_API_KEY=file-test-only\nDJANGO_DEBUG=true\n')
            with patch.dict(os.environ, {'LLM_API_KEY': 'environment-test-only'}, clear=True):
                load_environment(root)
                self.assertEqual(os.environ['LLM_API_KEY'], 'environment-test-only')
                self.assertEqual(os.environ['DJANGO_DEBUG'], 'true')

    def test_production_profile_repairs_old_port_domain_and_database_variables(self):
        module = script_module('container_start')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {'PORT': '80', 'DJANGO_DEBUG': 'true',
                    'DJANGO_ALLOWED_HOSTS': 'localhost', 'DJANGO_DB_PATH': '/old/local.sqlite3',
                    'TOROB_DATA_MODE': 'persistent'}, clear=True):
                storage = module.configure_environment(root)
                self.assertEqual(os.environ['PORT'], '8000')
                self.assertEqual(os.environ['DJANGO_DEBUG'], 'false')
                self.assertEqual(os.environ['DJANGO_DB_PATH'], str(storage / 'db.sqlite3'))
                self.assertIn('torob-yar-v2.liara.run', os.environ['DJANGO_ALLOWED_HOSTS'])
                self.assertIn('https://torob-yar-v2.liara.run', os.environ['DJANGO_CSRF_TRUSTED_ORIGINS'])

    def test_no_volume_uses_immutable_packaged_catalog_without_large_disk_copy(self):
        module = script_module('container_start')
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True), \
                patch.object(module, 'is_mounted', return_value=False):
            root = Path(directory)
            state = module.configure_environment(root)
            self.assertEqual(os.environ['DJANGO_DB_READONLY'], 'true')
            self.assertEqual(os.environ['DJANGO_DB_PATH'], str(root / 'bootstrap/catalog.sqlite3'))
            self.assertEqual(os.environ['DJANGO_SECRET_KEY_FILE'], str(state / 'django-secret-key'))

    def test_mounted_liara_disk_is_detected_without_manual_configuration(self):
        module = script_module('container_start')
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True), \
                patch.object(module, 'is_mounted', return_value=True):
            root = Path(directory)
            storage = module.configure_environment(root)
            self.assertEqual(storage, root / 'storage')
            self.assertEqual(os.environ['DJANGO_DB_READONLY'], 'false')
            self.assertEqual(os.environ['DJANGO_DB_PATH'], str(storage / 'db.sqlite3'))


class SeedInstallationTests(SimpleTestCase):
    def test_seed_is_copied_once_and_existing_database_is_kept(self):
        module = script_module('bootstrap_container')
        with tempfile.TemporaryDirectory() as directory:
            seed = Path(directory) / 'seed.sqlite3'
            target = Path(directory) / 'storage/db.sqlite3'
            with sqlite3.connect(seed) as database:
                database.execute('CREATE TABLE content (value TEXT)')
                database.execute('INSERT INTO content VALUES (?)', ['original'])
            self.assertTrue(module.install_seed(seed, target))
            with sqlite3.connect(target) as database:
                database.execute('UPDATE content SET value=?', ['my-edit'])
            self.assertFalse(module.install_seed(seed, target))
            with sqlite3.connect(target) as database:
                self.assertEqual(database.execute('SELECT value FROM content').fetchone()[0], 'my-edit')
            self.assertFalse(list(target.parent.glob('.catalog-*')))

    def test_invalid_seed_never_replaces_existing_data(self):
        module = script_module('bootstrap_container')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'seed').write_bytes(b'not a database')
            (root / 'existing').write_bytes(b'keep this')
            with self.assertRaises(RuntimeError):
                module.install_seed(root / 'seed', root / 'existing')
            self.assertEqual((root / 'existing').read_bytes(), b'keep this')


class CatalogMergeTests(TransactionTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.seed = Path(self.directory.name) / 'catalog.sqlite3'
        shop = Shop.objects.create(id='s', name='seed shop')
        for i in [1, 2]:
            product = Product.objects.create(id='p'+str(i), title='seed product '+str(i), search_text='seed product')
            Offer.objects.create(id='o'+str(i), product=product, shop=shop, price_toman=i*100)
        ImportState.objects.create(source_key='f'*64, completed=True)
        connection.ensure_connection()
        with sqlite3.connect(self.seed) as seed_connection:
            connection.connection.backup(seed_connection)
        self.seed.with_suffix('.json').write_text(json.dumps({
            'source_key': 'f'*64, 'counts': {'shops': 1, 'products': 2, 'offers': 2}}))
        Offer.objects.all().delete()
        Product.objects.all().delete()
        Shop.objects.all().delete()
        ImportState.objects.all().delete()

    def merge(self):
        output = io.StringIO()
        call_command('bootstrap_catalog', seed=self.seed, stdout=output)
        return output.getvalue()

    def test_empty_existing_database_is_populated_automatically(self):
        self.merge()
        self.assertEqual((Shop.objects.count(), Product.objects.count(), Offer.objects.count()), (1, 2, 2))
        self.assertTrue(ImportState.objects.get(source_key='f'*64).completed)
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM product_fts')
            self.assertEqual(cursor.fetchone()[0], 2)

    def test_upgrade_adds_missing_records_without_overwriting_user_edits(self):
        shop = Shop.objects.create(id='s', name='custom shop')
        product = Product.objects.create(id='p1', title='custom title')
        Offer.objects.create(id='o1', shop=shop, product=product, price_toman=999)
        self.merge()
        self.assertEqual(Product.objects.get(pk='p1').title, 'custom title')
        self.assertEqual(Shop.objects.get(pk='s').name, 'custom shop')
        self.assertEqual(Offer.objects.get(pk='o1').price_toman, 999)
        self.assertTrue(Offer.objects.filter(pk='o2').exists())
        self.assertIn('already initialized', self.merge())
        self.assertEqual(Offer.objects.count(), 2)
        # Refreshing edited rows requires this separate, explicit option.
        call_command('bootstrap_catalog',seed=self.seed,refresh=True,stdout=io.StringIO())
        self.assertEqual(Product.objects.get(pk='p1').title,'seed product 1')
        self.assertEqual(Shop.objects.get(pk='s').name,'seed shop')
        self.assertEqual(Offer.objects.get(pk='o1').price_toman,100)


@override_settings(LLM_ENABLED=False, TOROB_FALLBACK_TO_DATASET=True)
class CatalogFallbackTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        shop = Shop.objects.create(id='s', name='recorded shop')
        product = Product.objects.create(id='p', title='گوشی سامسونگ', category='گوشی موبایل',
                                         search_text='گوشی سامسونگ', brand='سامسونگ')
        Offer.objects.create(id='o', shop=shop, product=product, price_toman=100)

    def test_upstream_failure_uses_real_catalog_with_explicit_source_and_keeps_budget(self):
        with patch('shopping.views.search_live_in_person', side_effect=LiveSearchError('no connection')):
            data = self.client.post('/api/chat/', {'message':'گوشی سامسونگ',
                'preferences':{'budget_max':200,'color_any':True,'needs':'مقایسه مدل‌ها'}}, format='json').json()
            over_budget = self.client.post('/api/chat/', {'message':'گوشی سامسونگ',
                'preferences':{'budget_max':99,'color_any':True,'needs':'مقایسه مدل‌ها'}}, format='json').json()
        self.assertEqual(data['source'], 'uploaded_dataset')
        self.assertEqual(data['requested_source'], 'live')
        self.assertEqual(data['market']['status'], 'unavailable')
        self.assertEqual(data['products'][0]['best_offer']['price_toman'], 100)
        self.assertIn('از فایل', data['reply'])
        self.assertEqual(over_budget['products'], [])

    def test_health_reflects_catalog_readiness_without_a_provider_request(self):
        with patch('shopping.services.llm.requests.post') as provider:
            ready = self.client.get('/api/health/').json()
            Offer.objects.all().delete()
            empty = self.client.get('/api/health/').json()
        self.assertTrue(ready['catalog_ready'])
        self.assertFalse(empty['catalog_ready'])
        provider.assert_not_called()

