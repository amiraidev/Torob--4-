"""Create a small, real-data catalog for the static preview. Full data stays in Django."""
import csv
import gzip
import io
import json
import sys
import zipfile
from pathlib import Path
from collections import Counter
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'backend'))
from shopping.services.common import normalize

def js(s,default=None):
    try: return json.loads(s) if s not in ('','null') else default
    except (ValueError,TypeError): return default
def text(s): return '' if s in (None,'null') else str(s)

def main(source):
    selected={};counts=Counter();category_counts=Counter()
    caps={'گوشی موبایل':814,'لپ تاپ و نوت بوک':260,'هدفون، هدست و هندزفری':220,
        'مانیتور':120,'جارو برقی':123,'قهوه و اسپرسو ساز':86,'ساعت و مچ بند هوشمند':160,
        'دوربین مدار بسته':70,'اسپیکر (بلندگو)':80,'کنسول بازی':50,'تلویزیون':70}
    with zipfile.ZipFile(source) as z:
        def rows(name):return csv.DictReader(io.TextIOWrapper(z.open('torob-dataset/'+name),encoding='utf-8-sig'))
        for r in rows('products.csv'):
            cat=r['category_name'];category_counts[cat]+=1
            if counts[cat]>=caps.get(cat,1): continue
            specs=js(r['specs'],[]) or []
            title=r['persian_title'];brand=text(r['brand_name'])
            colors=' '.join(str(s.get('value','')) for s in specs if 'رنگ' in s.get('key',''))
            en=next((str(s.get('value','')) for s in specs if s.get('key') in ('نام محصول','نام انگلیسی') and any(c.isascii() and c.isalpha() for c in str(s.get('value','')))),'')
            selected[r['product_id']]={'id':r['product_id'],'title':title,'english_title':en,'brand':brand,'category':cat,'model':text(r['model']),
                'images':(js(r['image_urls'],[]) or [])[:3],'specs':specs[:12],
                'color_text':normalize(colors),'search_text':normalize(' '.join([title,brand,cat,en,text(r['model'])]))}
            counts[cat]+=1
        offers=[];shop_ids=set();linked=set();earliest=None;latest=None
        for r in rows('offers.csv'):
            if r['product_id'] not in selected: continue
            try: price=int(r['price_toman'])
            except ValueError: price=None
            if price is not None and price<0: price=None
            offers.append({'id':r['offer_id'],'product_id':r['product_id'],'shop_id':r['shop_id'],
                'price_toman':price,'seller_title':r['seller_title'],'description':r['description'][:1000],
                'warranty':js(r['warranty'],None),'last_price_changed_at':text(r['last_price_changed_at']) or None})
            shop_ids.add(r['shop_id']);linked.add(r['product_id'])
            t=text(r['last_price_changed_at'])
            if t: earliest=min(earliest or t,t);latest=max(latest or t,t)
        selected={k:v for k,v in selected.items() if k in linked}
        shops=[]
        for r in rows('shops.csv'):
            if r['shop_id'] not in shop_ids:continue
            shops.append({'id':r['shop_id'],'name':r['name'],'business_type':'','description':'','categories':js(r['category_names'],[]),
                'images':[],'licenses':[],'torob_since':None,'address':text(r['address']),'location_label':text(r['location_label']),
                'lat':js(r['lat']),'lon':js(r['lon']),'weekly_hours':js(r['weekly_hours'],{}),
                'contacts':[], 'payment_options':js(r['payment_options'],[]),'supports_fast_delivery':js(r['supports_fast_delivery']),
                'supports_kalabarg':None,'website_url':text(r['website_url']),'instagram':text(r['instagram'])})
    # Product photography comes from the actual product's dataset image, with a local copy for four starter cards.
    hero=[]
    for key,cat,term in [('phone','گوشی موبایل','A55'),('audio','هدفون، هدست و هندزفری','WH-1000'),('laptop','لپ تاپ و نوت بوک','VivoBook'),('home','قهوه و اسپرسو ساز','دلونگی')]:
        choices=[p for p in selected.values() if p['category']==cat and p['images']]
        p=next((p for p in choices if term.lower() in p['title'].lower()),next(iter(choices),None))
        if not p and key=='home':p=next((p for p in selected.values() if 'اسپرسو' in p['title'] and p['images']),None)
        if p:hero.append({'key':key,'product_id':p['id'],'image':p['images'][0],'title':p['title']})
    def download(h):
        try:
            from PIL import Image
            data=urlopen(h['image'],timeout=20).read()
            img=Image.open(io.BytesIO(data)).convert('RGB');img.thumbnail((500,500))
            path=ROOT/'public/images'/f'{h["key"]}.webp';img.save(path,'WEBP',quality=86)
            h['image']='/images/'+path.name
        except Exception as e:print('Image unavailable:',h['key'],type(e).__name__)
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(download,hero))
    data={'meta':{'source':'uploaded_dataset','total_products':225903,'total_offers':331506,'total_shops':6476,
        'preview_products':len(selected),'preview_offers':len(offers),'preview_shops':len(shops),
        'price_dates':{'from':earliest,'to':latest},'contacts_published':False,'categories':[{'name':k,'count':v} for k,v in category_counts.most_common()]},
        'products':list(selected.values()),'offers':offers,'shops':shops,'hero':hero}
    out=ROOT/'public/data/catalog.json.gz';out.write_bytes(gzip.compress(json.dumps(data,ensure_ascii=False,separators=(',',':')).encode('utf-8'),mtime=0))
    (ROOT/'public/data/catalog.json').unlink(missing_ok=True)
    (ROOT/'public/data/summary.json').write_text(json.dumps({'meta':data['meta'],'hero':hero},ensure_ascii=False,separators=(',',':')))
    print('Exported',len(selected),'products,',len(offers),'offers,',len(shops),'shops;',out.stat().st_size,'bytes')
    print('Hero:',json.dumps(hero,ensure_ascii=False))
if __name__=='__main__':main(sys.argv[1])
