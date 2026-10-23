import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import statistics
import sys
import time

p = argparse.ArgumentParser()
p.add_argument('app', type=Path)
p.add_argument('database', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--timing-only', action='store_true')
p.add_argument('--data-only', action='store_true')
args = p.parse_args()
if not args.database.is_file():p.error('Database file does not exist')
os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', DJANGO_DEBUG='false',
                  DJANGO_SECRET_KEY='benchmark-only-not-deployed', LLM_ENABLED='false',
                  DJANGO_DB_PATH=str(args.database.resolve()), DJANGO_DB_READONLY='true', TOROB_BUILDING_IMAGE='true')
sys.path.insert(0, str(args.app.resolve()/'backend'))
import django
django.setup()
from shopping.services.search import search_products
from shopping.models import Product, Shop, Offer
from datetime import datetime, timezone
import shopping.services.search as search_module

class FixedDate(datetime):
    @classmethod
    def now(cls,tz=None):
        instant=datetime(2026,10,23,12,0,0,tzinfo=timezone.utc)
        return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

search_module.datetime=FixedDate

cases = [
    {'query': 'سامسونگ a55', 'category': 'گوشی موبایل'},
    {'query': 'asus', 'category': 'لپ تاپ و نوت بوک', 'sort': 'price'},
    {'category': 'گوشی موبایل', 'budget_max': 20_000_000, 'sort': 'price'},
    {'query': 'هدفون', 'budget_max': 5_000_000},
    {'category': 'گوشی موبایل', 'installment': True},
    {'budget_max': 50_000_000},
]
report = {'database_bytes': args.database.stat().st_size, 'searches': []}
for prefs in ([] if args.data_only else cases):
    times=[]
    for _ in range(4):
        start=time.perf_counter()
        result=search_products(prefs)
        times.append((time.perf_counter()-start)*1000)
    signature=hashlib.sha256(json.dumps(result,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
    report['searches'].append({'preferences':prefs,'first_ms':round(times[0],3),
        'median_warm_ms':round(statistics.median(times[1:]),3),
        'matched_count':result['matched_count'],'result_signature':signature,
        'ids':[x['id'] for x in result['products']]})
if args.timing_only:
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('warm_ms', [x['median_warm_ms'] for x in report['searches']])
    raise SystemExit(0)
report['logical_data']={}
for model in (Shop,Product,Offer):
    digest=hashlib.sha256();count=0
    fields=[f.attname for f in model._meta.concrete_fields]
    for values in model.objects.order_by('pk').values_list(*fields).iterator(chunk_size=500):
        count+=1
        digest.update(json.dumps(values,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode())
        digest.update(b'\n')
    report['logical_data'][model._meta.db_table]={'count':count,'sha256':digest.hexdigest()}
with sqlite3.connect(args.database) as db:
    report['sqlite_check']=db.execute('pragma quick_check').fetchone()[0]
    report['foreign_key_errors']=len(db.execute('pragma foreign_key_check').fetchall())
    report['storage']=[{'name':n,'bytes':s} for n,s in db.execute('select name,sum(pgsize) from dbstat group by name order by 2 desc')]
args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k not in ('storage','searches')},ensure_ascii=False))
print('warm_ms', [x['median_warm_ms'] for x in report['searches']])
