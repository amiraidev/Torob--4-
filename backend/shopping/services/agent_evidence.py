"""Server-owned evidence: the model selects references, never writes table values."""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
import re
from django.conf import settings
from django.core import signing
from django.utils.dateparse import parse_datetime
from .common import normalize,distance_km,opening_status,payment_matches
from .preferences import product_matches,variant_matches

SALT='torob-yar-agent-state-v1'
MAX_PRODUCTS=8

def text(value,limit=500):
    if value is None:return ''
    return (value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,default=str))[:limit]

def compact_product(product):
    p=deepcopy(product)
    keep={'id','live_id','title','english_title','brand','category','model','source','retrieved_at','torob_url','images','specs','offers','min_price_toman','max_price_toman','offer_count','warnings','best_offer','focus_spec_keys'}
    p={k:v for k,v in p.items() if k in keep}
    p['specs']=[{'key':text(s.get('key'),150),'value':text(s.get('value'),450)} for s in p.get('specs',[]) if isinstance(s,dict) and s.get('key')][:120]
    p['images']=p.get('images',[])[:4]
    offers=p.get('offers',[])[:6]
    if p.get('best_offer') and not any(o['id']==p['best_offer']['id'] for o in offers):offers.insert(0,p['best_offer'])
    for o in offers:
        o['description']=text(o.get('description'),650);o['seller_title']=text(o.get('seller_title'),350)
        o['distance_km']=None  # Recomputed from this request; exact GPS never enters the token.
        shop=o.get('shop',{});shop.pop('distance_km',None)
        for key in ('images','licenses'):shop[key]=(shop.get(key) or [])[:3]
    p['offers']=offers
    p['best_offer']=next((o for o in offers if o['id']==p.get('best_offer',{}).get('id')),offers[0] if offers else {})
    p.update(score=None,reasons=[],badges=[],agentic=True)
    return p

def seal(products):
    payload={'v':1,'captured_at':datetime.now(timezone.utc).isoformat(),'products':[compact_product(p) for p in products[:MAX_PRODUCTS]]}
    while len(json.dumps(payload,ensure_ascii=False,default=str).encode())>300000 and payload['products']:payload['products'].pop()
    return signing.dumps(payload,salt=SALT,compress=True)

def unseal(token):
    if not token:return [],'empty'
    try:
        d=signing.loads(token,salt=SALT,max_age=settings.AGENT_STATE_TTL)
        if not isinstance(d,dict) or d.get('v')!=1 or not isinstance(d.get('products'),list):return [],'invalid'
        return [compact_product(p) for p in d['products'][:MAX_PRODUCTS] if isinstance(p,dict) and isinstance(p.get('id'),str)],'ok'
    except signing.SignatureExpired:return [],'expired'
    except (signing.BadSignature,ValueError,TypeError,KeyError):return [],'invalid'

def eligible(products,prefs,location):
    result=[]
    visit=prefs.get('visit_at');visit=parse_datetime(visit) if isinstance(visit,str) else visit
    for raw in products[:MAX_PRODUCTS]:
        p=deepcopy(raw)
        if prefs.get('category') and p.get('category') and p['category']!=prefs['category']:continue
        if not product_matches(p.get('title',''),p.get('english_title',''),prefs):continue
        offers=[]
        for o in p.get('offers',[]):
            price=o.get('price_toman');shop=o.get('shop') or {}
            if isinstance(price,bool) or not isinstance(price,int) or price<=0 or price<prefs.get('budget_min',0) or prefs.get('budget_max') and price>prefs['budget_max']:continue
            if not variant_matches(o.get('description','')+' '+o.get('seller_title',''),prefs,p.get('title','')):continue
            payments=shop.get('payment_options') or []
            if prefs.get('installment') and not any(payment_matches(x,prefs.get('category','')) for x in payments):continue
            if prefs.get('torobpay') and not any(payment_matches(x,prefs.get('category',''),'ترب‌پی') for x in payments):continue
            if prefs.get('fast_delivery') and shop.get('supports_fast_delivery') is not True:continue
            o['distance_km']=distance_km(location['lat'],location['lon'],shop.get('lat'),shop.get('lon')) if location else None
            if shop.get('weekly_hours'):shop['opening']=opening_status(shop['weekly_hours'],visit)
            shop.setdefault('opening',{'state':'unknown','label':'ساعت کاری مشخص نیست'})
            if prefs.get('only_open') and shop['opening']['state']!='open':continue
            if prefs.get('radius_km') and (o['distance_km'] is None or o['distance_km']>prefs['radius_km']):continue
            offers.append(o)
        if not offers:continue
        p['offers']=offers
        p['best_offer']=next((o for o in offers if o['id']==p.get('best_offer',{}).get('id')),offers[0])
        p['min_price_toman']=min(o['price_toman'] for o in offers);p['max_price_toman']=max(o['price_toman'] for o in offers)
        p['offer_count']=len(offers);p.update(agentic=True,score=None,reasons=[],badges=[])
        result.append(p)
    return result

def ref(*parts):return 'f_'+hashlib.sha256('|'.join(map(str,parts)).encode()).hexdigest()[:18]

def catalogue(products,web,stores,calculations):
    facts={};cards=[]
    def fact(pid,key,label,value,source,url='',at=None,offer_id=None):
        fid=ref(pid,key);facts[fid]={'id':fid,'product_id':pid,'label':label,'value':text(value,500) or 'ثبت نشده',
            'source':source,'url':url or '', 'retrieved_at':at,'offer_id':offer_id};return fid
    for p in products[:MAX_PRODUCTS]:
        pid=p['id'];url=p.get('torob_url','');source=p.get('source','unknown');at=p.get('retrieved_at')
        spec_facts=[];focus=p.get('focus_spec_keys',[])
        specs=p.get('specs',[])
        if focus:specs=sorted(specs,key=lambda s:not any(normalize(k) in normalize(s['key']) for k in focus))
        for s in specs[:24]:spec_facts.append(fact(pid,'spec:'+s['key'],s['key'],s['value'],source,url,at))
        offer_cards=[]
        for o in p.get('offers',[])[:6]:
            shop=o['shop'];oid=o['id'];payment=[x for x in shop.get('payment_options',[]) if x.get('channel')=='in_person']
            vals={'price':('قیمت همین فروشنده (تومان)',o['price_toman']),
                'shop':('نام فروشنده',shop.get('name')),'distance':('فاصله مستقیم (کیلومتر)',o.get('distance_km')),
                'opening':('ساعت کار',shop.get('opening',{}).get('label')),'warranty':('گارانتی اعلام‌شده',o.get('warranty')),
                'installments':('اقساط حضوری اعلام‌شده',payment if payment else 'ثبت نشده'),
                'variant':('شرح دقیق پیشنهاد',o.get('description') or o.get('seller_title'))}
            ids={k:fact(pid,oid+':'+k,label,value,source,url,o.get('retrieved_at') or at,oid) for k,(label,value) in vals.items()}
            facts[ids['price']].update(price_stale=o.get('price_stale',True),last_price_changed_at=o.get('last_price_changed_at'),
                                      price_age_days=o.get('price_age_days'),last_price_change_text=o.get('last_price_change_text'),shop_name=shop.get('name'))
            offer_cards.append({'id':oid,'shop':shop.get('name'),'facts':ids,'price_stale':o.get('price_stale',True)})
        cards.append({'id':pid,'title':p.get('title'),'brand':p.get('brand'),'category':p.get('category'),
            'source':source,'retrieved_at':at,'spec_fact_ids':spec_facts,'offers':offer_cards,'available_spec_keys':[s['key'] for s in p.get('specs',[])][:60]})
    return {'products':cards,'facts':facts,'web_research':web,'stores':stores,'calculations':calculations},facts

def render_comparison(raw,by_id,facts):
    if not raw:return None
    if not isinstance(raw,dict):raise ValueError('comparison must be an object')
    ids=raw.get('product_ids',[])
    if not isinstance(ids,list) or not 2<=len(ids)<=4 or any(not isinstance(i,str) or i not in by_id for i in ids) or len(set(ids))!=len(ids):raise ValueError('comparison IDs must be known')
    rows=[]
    raw_rows=raw.get('rows',[])
    if not isinstance(raw_rows,list):raise ValueError('comparison rows must be a list')
    for row in raw_rows[:12]:
        if not isinstance(row,dict) or not isinstance(row.get('label'),str) or not isinstance(row.get('fact_refs'),dict):raise ValueError('invalid comparison row')
        cells=[]
        for pid in ids:
            fid=row['fact_refs'].get(pid);f=facts.get(fid) if isinstance(fid,str) else None
            if fid is not None and (not f or f['product_id']!=pid):raise ValueError('comparison fact belongs to another product')
            cells.append({'product_id':pid,'fact_id':fid if f else None,'value':f['value'] if f else 'در منابع دریافت‌شده ثبت نشده',
                'source':f['source'] if f else None,'url':f['url'] if f else '', 'offer_id':f['offer_id'] if f else None,
                **({k:f.get(k) for k in ('retrieved_at','price_stale','last_price_changed_at','price_age_days','last_price_change_text','shop_name')} if f else {})})
        winner=row.get('winner_id')
        if winner is not None and (winner not in ids or not row['fact_refs'].get(winner)):raise ValueError('winner needs evidence')
        rows.append({'label':row['label'][:160],'cells':cells,'winner_id':winner,'explanation':text(row.get('explanation'),650)})
    if not rows:raise ValueError('a comparison requires sourced rows')
    overall=raw.get('winner_id')
    if overall is not None and overall not in ids:raise ValueError('unknown comparison winner')
    return {'product_ids':ids,'products':[{'id':i,'title':by_id[i]['title']} for i in ids],
        'rows':rows,'winner_id':overall,'verdict':text(raw.get('verdict'),1600),
        'limits':text(raw.get('limits'),1000),'basis':'server_resolved_facts'}
