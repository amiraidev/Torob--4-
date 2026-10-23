"""Lossless storage, bounded search work, and verified snapshot restoration."""
from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch

from django.core import serializers
from django.core.management import call_command
from django.forms import modelform_factory
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from shopping.catalog_codec import encode_json, decode_json
from shopping.catalog_index import rebuild_index
from shopping.models import Product, Shop, Offer, ImportState
from shopping.services.search import search_products, serialize_shop

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
from catalog_bundle import pack_catalog, load_catalog


class DocumentCodecTests(SimpleTestCase):
    def test_roundtrip_preserves_unicode_nested_values_and_types(self):
        values=[None,{},[],False,0,12.5,'متن فارسی 😀',{'a':[None,True,False,0,3.5,{'رنگ':'آبی\u200cتیره'}]},
                [{'key':'مشخصات','value':'حافظه رم و پردازنده '*200}]]
        for value in values:
            with self.subTest(value=type(value).__name__):
                self.assertEqual(decode_json(encode_json(value)),value)

    def test_legacy_escaped_json_remains_readable(self):
        value={'برنامه': ['شنبه','یکشنبه'], 'count': 2}
        self.assertEqual(decode_json(json.dumps(value)),value)

    def test_large_documents_are_smaller_and_invalid_encoding_is_rejected(self):
        value=[{'key':'رنگ','value':'مشکی'}]*50
        self.assertLess(len(encode_json(value)),len(json.dumps(value).encode())//4)
        with self.assertRaises(ValueError):decode_json(b'TYJ1xanything')


class CompactSearchTests(TestCase):
    def setUp(self):
        self.shop=Shop.objects.create(id='shop',name='فروشگاه',weekly_hours={'fri':{'status':'closed'}})
        self.product=Product.objects.create(id='p',title='گوشی تست',search_text='گوشی تست',
            specs=[{'key':'رنگ','value':'مشکی'}],images=['https://example.com/product.webp'])
        Offer.objects.create(id='o',product=self.product,shop=self.shop,price_toman=100,warranty={'name':'تست'})
        rebuild_index(connection)

    def test_database_and_fixtures_keep_json_values_after_a_second_save(self):
        self.product.refresh_from_db()
        self.product.specs.append({'key':'گارانتی','value':'۱۸ ماه'})
        form=modelform_factory(Product,fields=['specs'])(
            data={'specs':json.dumps(self.product.specs)},instance=self.product)
        self.assertTrue(form.is_valid(),form.errors)
        self.product=form.save()
        exported=serializers.serialize('json',[self.product])
        restored=list(serializers.deserialize('json',exported))[0].object
        self.assertEqual(restored.specs,self.product.specs)
        with connection.cursor() as cursor:
            cursor.execute('SELECT typeof(specs),specs FROM shopping_product WHERE id=%s',['p'])
            kind,raw=cursor.fetchone()
        self.assertEqual(kind,'blob')
        self.assertEqual(decode_json(raw),self.product.specs)
        result=search_products({'query':'گوشی'})['products'][0]
        self.assertEqual(result['specs'],self.product.specs)
        self.assertEqual(result['best_offer']['warranty'],{'name':'تست'})

    def test_search_index_follows_insert_update_delete(self):
        p=Product.objects.create(id='other',title='other',search_text='ultrabook silver')
        def ids(term):
            with connection.cursor() as cursor:
                cursor.execute('SELECT product_id FROM product_fts WHERE product_fts MATCH %s',[term])
                return [r[0] for r in cursor.fetchall()]
        self.assertEqual(ids('"ultra"* AND "silver"*'),['other'])
        p.search_text='notebook black';p.save(update_fields=['search_text'])
        self.assertEqual(ids('ultrabook'),[])
        self.assertEqual(ids('"note"*'),['other'])
        p.delete()
        self.assertEqual(ids('notebook'),[])

    def test_budget_bounds_must_match_the_same_offer(self):
        Offer.objects.filter(pk='o').update(price_toman=50)
        Offer.objects.create(id='high',product=self.product,shop=self.shop,price_toman=200)
        self.assertEqual(search_products({'budget_min':100,'budget_max':150})['products'],[])

    def test_large_candidate_sets_have_bounded_queries_and_shop_work(self):
        for i in range(50):
            p=Product.objects.create(id=f'item-{i:03}',title='محصول',search_text='محصول',
                specs=[{'key':'توضیحات','value':'متن '*500}],images=[])
            Offer.objects.create(id=f'offer-{i}',product=p,shop=self.shop,price_toman=200+i)
        with CaptureQueriesContext(connection) as queries, patch('shopping.services.search.serialize_shop',wraps=serialize_shop) as shop_work:
            result=search_products({},limit=4)
        self.assertEqual(len(result['products']),4)
        self.assertEqual(result['matched_count'],51)
        self.assertLessEqual(len(queries),5)
        self.assertEqual(shop_work.call_count,1)
        self.assertTrue(all('specs' in p and 'images' in p for p in result['products']))

    def test_fallback_search_still_works_without_fts(self):
        from shopping.catalog_index import drop_index
        drop_index(connection)
        self.assertEqual(search_products({'query':'گوشی'})['products'][0]['id'],'p')


class CatalogBundleTests(TransactionTestCase):
    def setUp(self):
        shop=Shop.objects.create(id='shop',name='فروشگاه',contacts=[{'channel':'phone','value':'test'}])
        product=Product.objects.create(id='product',title='کالای آزمایش',search_text='کالای آزمایش',specs=[{'key':'رنگ','value':'مشکی'}])
        Offer.objects.create(id='offer',shop=shop,product=product,seller_title=product.title,price_toman=123,warranty={'title':'۱۸ ماه'})
        ImportState.objects.create(source_key='a'*64,completed=True,progress={'counts':{'shops':1,'products':1,'offers':1}})
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source=Path(self.directory.name)/'source.sqlite3'
        with closing(sqlite3.connect(self.source)) as db:connection.connection.backup(db)
        self.archive=Path(self.directory.name)/'catalog.jsonl.xz'
        pack_catalog(self.source,self.archive)

    def empty_target(self):
        path=Path(self.directory.name)/'target.sqlite3'
        with closing(sqlite3.connect(self.source)) as source, closing(sqlite3.connect(path)) as target:
            source.backup(target)
            for table in ('shopping_offer','shopping_product','shopping_shop'):
                target.execute('DELETE FROM '+table)
            target.commit()
        return path

    def test_snapshot_roundtrip_preserves_every_column(self):
        target=self.empty_target()
        info=load_catalog(self.archive,target)
        self.assertEqual(info['counts'],{'shops':1,'products':1,'offers':1})
        with closing(sqlite3.connect(self.source)) as source, closing(sqlite3.connect(target)) as restored:
            for table in ('shopping_shop','shopping_product','shopping_offer'):
                self.assertEqual(source.execute('SELECT * FROM '+table).fetchall(),restored.execute('SELECT * FROM '+table).fetchall())
            self.assertIsNone(restored.execute('PRAGMA foreign_key_check').fetchone())

    def test_bad_checksum_rolls_back_data_and_secondary_indexes(self):
        target=self.empty_target()
        manifest=self.archive.with_name('catalog.json')
        info=json.loads(manifest.read_text());info['logical_sha256']='0'*64;manifest.write_text(json.dumps(info))
        with self.assertRaisesRegex(RuntimeError,'checksum'):load_catalog(self.archive,target)
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM shopping_product').fetchone()[0],0)
            self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='shopping_of_product_a4d00a_idx'").fetchone())

    def test_existing_catalog_is_never_overwritten(self):
        before=self.source.read_bytes()
        with self.assertRaisesRegex(RuntimeError,'empty'):load_catalog(self.archive,self.source)
        self.assertEqual(self.source.read_bytes(),before)

    def test_packaging_refuses_private_accounts(self):
        with closing(sqlite3.connect(self.source)) as db:
            db.execute("INSERT INTO auth_user(password,is_superuser,username,first_name,last_name,email,is_staff,is_active,date_joined) VALUES('',0,'private','','','',0,1,'2026-10-23')")
            db.commit()
        with self.assertRaisesRegex(RuntimeError,'user accounts'):pack_catalog(self.source,Path(self.directory.name)/'private.xz')
