"""Bounded imports with atomic checkpoints and visible progress, including on Windows."""
import csv
import hashlib
import gzip
import io
import json
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils.dateparse import parse_datetime
from shopping.models import Shop, Product, Offer, ImportState
from shopping.services.common import normalize
from shopping.catalog_index import drop_index, rebuild_index

IMPORT_VERSION = b'torob-import-v3\0'

def text(value): return '' if value in (None, 'null') else str(value)
def js(value, fallback):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return fallback if parsed is None else parsed
    except (ValueError, TypeError): return fallback
def number(value):
    try: return float(value)
    except (ValueError, TypeError): return None

class Command(BaseCommand):
    help = 'Import Torob ZIP/CSV or sample; resume interrupted batches and skip completed imports.'
    def add_arguments(self, p):
        p.add_argument('source', nargs='?')
        p.add_argument('--sample', action='store_true')
        p.add_argument('--force', action='store_true', help='Re-import this source without deleting existing data.')
        p.add_argument('--batch-size', type=int, default=1000)
    def say(self, message):
        self.stdout.write(message)
        self.stdout.flush()
    @contextmanager
    def rows(self, source, name):
        if source.suffix.lower() == '.zip':
            with zipfile.ZipFile(source) as archive:
                matches = [x for x in archive.namelist() if (x.endswith('/'+name) or x == name) and '__MACOSX' not in x]
                if len(matches) != 1: raise CommandError(f'Missing/ambiguous {name} in ZIP')
                with archive.open(matches[0]) as stream:
                    yield csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8-sig', newline=''))
        else:
            with (source/name).open(encoding='utf-8-sig', newline='') as stream:
                yield csv.DictReader(stream)
    def fingerprint(self, source):
        digest = hashlib.sha256(IMPORT_VERSION)
        for file in ([source] if source.is_file() else [source/n for n in ('shops.csv','products.csv','offers.csv')]):
            with file.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024*1024), b''): digest.update(chunk)
        return digest.hexdigest()
    @contextmanager
    def exclusive(self):
        # OS locks are released even if Ctrl+C or the process stops unexpectedly.
        db = Path(str(connection.settings_dict['NAME']))
        lock_path = db.parent / ('.torob-import-'+hashlib.sha256(str(db).encode()).hexdigest()[:12]+'.lock')
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open('a+b') as lock:
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            try:
                if __import__('os').name == 'nt':
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise CommandError('Another dataset import is running. Stop it or wait before running setup again.') from error
            try: yield
            finally:
                lock.seek(0)
                if __import__('os').name == 'nt':
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_UN)
    def bulk(self, model, objects):
        if objects:
            model.objects.bulk_create(objects, batch_size=300, update_conflicts=True,
                unique_fields=['id'], update_fields=[f.name for f in model._meta.fields if f.name != 'id'])
    def stage(self, label, model, rows, convert, state, size):
        info = state.progress.get(label, {})
        if info.get('done'):
            self.say(f'{label}: already complete ({info["processed"]:,} input rows).'); return
        offset = info.get('processed', 0); processed = offset; skipped = info.get('skipped', 0)
        self.say(f'{label}: starting at committed row {offset:,} ...')
        batch = []; started = time.monotonic(); last = started
        def commit(done=False):
            nonlocal batch, last
            with transaction.atomic():
                self.bulk(model, batch)
                state.progress[label] = {'processed': processed, 'skipped': skipped, 'done': done}
                state.save(update_fields=['progress', 'updated_at'])
            batch = []
            now = time.monotonic()
            if done or processed % 5000 == 0 or now-last >= 2:
                self.say(f'{label}: {processed:,} rows committed; skipped {skipped:,}; elapsed {now-started:.1f}s' + (' [DONE]' if done else ''))
                last = now
        for index, row in enumerate(rows, 1):
            if index <= offset: continue
            obj = convert(row); processed = index
            if obj is None: skipped += 1
            else: batch.append(obj)
            if (index-offset) % size == 0: commit()
        commit(done=True)
    def handle(self, *args, **options):
        if not 1 <= options['batch_size'] <= 5000: raise CommandError('batch-size must be between 1 and 5000')
        sample = options['sample']
        preview=Path(__file__).resolve().parents[4]/'public/data/catalog.json.gz'
        if not preview.exists():preview=preview.with_suffix('')
        source = (preview if sample else Path(options['source'] or '../data/torob-dataset.zip')).resolve()
        if not source.exists(): raise CommandError(f'Dataset not found: {source}')
        csv.field_size_limit(10_000_000)
        self.say('Checking dataset fingerprint ...')
        with self.exclusive():
            state, _ = ImportState.objects.get_or_create(source_key=self.fingerprint(source))
            if state.completed and not options['force']:
                expected = state.progress.get('counts', {})
                if all(model.objects.count() >= expected.get(name, 0) for name,model in [('shops',Shop),('products',Product),('offers',Offer)]):
                    self.say('Dataset already imported successfully. Skipping import. Use --force to refresh.'); return
            if options['force'] or state.completed:
                state.progress = {}; state.completed = False; state.save()
            # Bulk imports rebuild once at the end; normal writes use FTS triggers.
            drop_index(connection)
            size = options['batch_size']
            if sample:
                opener=gzip.open if source.suffix=='.gz' else open
                with opener(source,'rt',encoding='utf-8') as stream:data=json.load(stream)
                self.stage('Shops',Shop,data['shops'],lambda r: Shop(**r),state,size)
                def product(r):
                    values = {k:v for k,v in r.items() if k != 'source_images'}
                    values['images'] = r.get('source_images',r.get('images',[])); return Product(**values)
                self.stage('Products',Product,data['products'],product,state,size)
                self.stage('Offers',Offer,data['offers'],lambda r: Offer(**r),state,size)
            else:
                def shop(r):
                    return Shop(id=r['shop_id'],name=r['name'],address=text(r['address']),categories=js(r['category_names'],[]),
                        contacts=js(r['contacts'],[]),lat=number(r['lat']),lon=number(r['lon']),location_label=text(r['location_label']),
                        weekly_hours=js(r['weekly_hours'],{}),payment_options=js(r['payment_options'],[]),supports_fast_delivery=js(r['supports_fast_delivery'],None),
                        website_url=text(r['website_url']),instagram=text(r['instagram']))
                with self.rows(source,'shops.csv') as rows: self.stage('Shops',Shop,rows,shop,state,size)
                def product(r):
                    specs = js(r['specs'],[]); title=text(r['persian_title']);brand=text(r['brand_name']);category=text(r['category_name'])
                    en=next((text(s.get('value')) for s in specs if s.get('key') in ['نام انگلیسی','نام محصول'] and any(c.isascii() and c.isalpha() for c in str(s.get('value','')))), '')
                    color=' '.join(text(s.get('value')) for s in specs if 'رنگ' in s.get('key',''))
                    return Product(id=r['product_id'],title=title,english_title=en,brand=brand,category=category,model=text(r['model']),images=js(r['image_urls'],[]),
                        specs=specs,search_text=normalize(' '.join([title,brand,category,text(r['model']),en])),color_text=normalize(color))
                with self.rows(source,'products.csv') as rows: self.stage('Products',Product,rows,product,state,size)
                self.say('Preparing offer references ...')
                product_ids=set(Product.objects.values_list('id',flat=True));shop_ids=set(Shop.objects.values_list('id',flat=True))
                def offer(r):
                    if r['product_id'] not in product_ids or r['shop_id'] not in shop_ids: return None
                    try: price=int(r['price_toman']) if r['price_toman'] not in ('','null') else None
                    except ValueError: price=None
                    if price is not None and price<0: price=None
                    return Offer(id=r['offer_id'],product_id=r['product_id'],shop_id=r['shop_id'],seller_title=text(r['seller_title']),description=text(r['description']),
                        price_toman=price,warranty=js(r['warranty'],text(r['warranty']) or None),last_price_changed_at=parse_datetime(r['last_price_changed_at']) if r['last_price_changed_at'] else None)
                with self.rows(source,'offers.csv') as rows: self.stage('Offers',Offer,rows,offer,state,size)
            self.say('Search index: rebuilding (this stage can take a while) ...')
            self.rebuild_fts()
            state.progress['counts']={'shops':Shop.objects.count(),'products':Product.objects.count(),'offers':Offer.objects.count()}
            state.completed=True;state.save();cache.delete('catalog_meta')
            self.say(self.style.SUCCESS('Import complete: '+str(state.progress['counts'])))
    def rebuild_fts(self):
        if connection.vendor != 'sqlite': return
        try:
            with transaction.atomic():
                rebuild_index(connection)
            self.say('Search index: ready.')
        except Exception as error:
            self.stderr.write(f'FTS unavailable; ORM search remains active: {type(error).__name__}')
