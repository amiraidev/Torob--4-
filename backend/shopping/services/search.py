import re
from datetime import datetime,timezone
from django.conf import settings
from django.db import connection
from django.db.models import Prefetch, Exists, OuterRef
from shopping.models import Product,Shop,Offer
from .common import normalize,distance_km,opening_status,payment_matches,safe_url,torob_search_url
from .preferences import variant_matches

def serialize_shop(shop,now=None):
    return {'id':shop.id,'name':shop.name,'business_type':shop.business_type or None,
        'description':shop.description or None,'categories':shop.categories,
        'images':[u for u in shop.images if safe_url(u)],'licenses':shop.licenses,'torob_since':shop.torob_since.isoformat() if shop.torob_since else None,
        'address':shop.address,'location_label':shop.location_label,'lat':shop.lat,'lon':shop.lon,
        'opening':opening_status(shop.weekly_hours,now),'weekly_hours':shop.weekly_hours,
        'contacts':[c for c in shop.contacts if c.get('channel')=='phone'] if settings.PUBLISH_PHONE_CONTACTS else [],
        'contacts_published':settings.PUBLISH_PHONE_CONTACTS,'payment_options':shop.payment_options,
        'supports_fast_delivery':shop.supports_fast_delivery,'supports_kalabarg':shop.supports_kalabarg,
        'website_url':safe_url(shop.website_url),'source':'uploaded_dataset'}

def serialize_offer(offer,location=None,now=None,visit=None,shop_cache=None):
    now=now or datetime.now(timezone.utc)
    days=max(0,(now-offer.last_price_changed_at).days) if offer.last_price_changed_at else None
    cached=shop_cache.get(offer.shop_id) if shop_cache is not None else None
    if cached is None:
        distance=distance_km(location['lat'],location['lon'],offer.shop.lat,offer.shop.lon) if location else None
        shop=serialize_shop(offer.shop,visit or now)
        cached=(distance,shop)
        if shop_cache is not None:shop_cache[offer.shop_id]=cached
    distance,shop=cached
    return {'id':offer.id,'product_id':offer.product_id,'seller_title':offer.seller_title,'description':offer.description,
        'price_toman':offer.price_toman,'currency':'تومان','warranty':offer.warranty,
        'last_price_changed_at':offer.last_price_changed_at.isoformat() if offer.last_price_changed_at else None,
        'price_age_days':days,'price_stale':days is None or days>settings.PRICE_FRESH_DAYS,
        'distance_km':distance,'distance_type':'straight_line','availability':'recorded_offer',
        'shop':shop,'source':'uploaded_dataset'}

def search_products(prefs,location=None,product_id=None,limit=12):
    qs=Product.objects.all()
    if product_id:qs=qs.filter(pk=product_id)
    else:
        category=prefs.get('category','')
        if category:qs=qs.filter(category=category)
        if prefs.get('brand'):qs=qs.filter(search_text__contains=normalize(prefs['brand']))
        if prefs.get('color'):qs=qs.filter(color_text__contains=normalize(prefs['color']))
        for key in ('model','product_type'):
            if prefs.get(key):qs=qs.filter(search_text__contains=normalize(prefs[key]))
        tokens=re.findall(r'[^\W_]+',normalize(prefs.get('query','')),re.UNICODE)[:8]
        if tokens:
            ids=None
            if connection.vendor=='sqlite':
                try:
                    with connection.cursor() as c:
                        c.execute('SELECT product_id FROM product_fts WHERE product_fts MATCH %s LIMIT 3000',
                            [' AND '.join('"'+t.replace('"','')+'"*' for t in tokens)])
                        ids=[r[0] for r in c.fetchall()]
                except Exception:pass
            if ids is not None:qs=qs.filter(pk__in=ids)
            else:
                for token in tokens:qs=qs.filter(search_text__contains=token)
    eligible_offers=Offer.objects.filter(price_toman__gt=0)
    if prefs.get('budget_min'):eligible_offers=eligible_offers.filter(price_toman__gte=prefs['budget_min'])
    if prefs.get('budget_max'):eligible_offers=eligible_offers.filter(price_toman__lte=prefs['budget_max'])
    if prefs.get('fast_delivery'):eligible_offers=eligible_offers.filter(shop__supports_fast_delivery=True)
    qs=qs.filter(Exists(eligible_offers.filter(product_id=OuterRef('pk'))))
    # Load each shop once even when it sells many matching products. Large product
    # documents are fetched together only after ranking the final visible cards.
    qs=qs.defer('specs','images').order_by('id').prefetch_related(Prefetch('offers',
        queryset=eligible_offers.order_by('price_toman','id').prefetch_related('shop')))
    now=datetime.now(timezone.utc);results=[];shop_cache={}
    # Bound memory for broad categories; a specific query and filters narrow candidates before this cap.
    for p in qs[:1500]:
        offers=[]
        for o in p.offers.all():
            if not variant_matches((o.seller_title or '')+' '+(o.description or ''),prefs,p.title):continue
            if not o.price_toman or o.price_toman < prefs.get('budget_min',0):continue
            if prefs.get('budget_max') and o.price_toman>prefs['budget_max']:continue
            if prefs.get('fast_delivery') and o.shop.supports_fast_delivery is not True:continue
            if prefs.get('installment') and not any(payment_matches(x,p.category) for x in o.shop.payment_options):continue
            if prefs.get('torobpay') and not any(payment_matches(x,p.category,'ترب‌پی') for x in o.shop.payment_options):continue
            serialized=serialize_offer(o,location,now,prefs.get('visit_at'),shop_cache)
            if prefs.get('only_open') and serialized['shop']['opening']['state']!='open':continue
            if prefs.get('radius_km') and (serialized['distance_km'] is None or serialized['distance_km']>prefs['radius_km']):continue
            offers.append(serialized)
        if not offers:continue
        min_price=min(o['price_toman'] for o in offers)
        def rank_offer(o):
            price_factor=min_price/o['price_toman']
            distance_factor=1/(1+o['distance_km']/3) if location and o['distance_km'] is not None else 0
            return 60*price_factor+35*distance_factor+3*(o['shop']['opening']['state']=='open')+2*(not o['price_stale'])
        order=prefs.get('sort','recommended')
        offers.sort(key=lambda o:o['price_toman'] if order=='price' else
            (o['distance_km'] if o['distance_km'] is not None else float('inf'),o['price_toman']) if order=='distance' else -rank_offer(o))
        best=offers[0];warnings=['قیمت و وجود پیشنهاد از فایل ثبت‌شده است؛ موجودی امروز را پیش از مراجعه تأیید کنید.']
        if best['price_stale']:warnings.append('قیمت ثبت‌شده قدیمی یا بدون زمان است.')
        if prefs.get('color'):warnings.append('رنگ در مشخصات پایه دیده شده؛ رنگ موجود نزد این فروشنده نیاز به تأیید دارد.')
        reasons=['پیشنهاد فروش ثبت‌شده برای همین محصول']
        if prefs.get('budget_max'):reasons.append('در محدوده بودجه انتخابی')
        if location:reasons.append('فاصله بر اساس مبدأ انتخابی محاسبه شده')
        if best['shop']['opening']['state']=='open':reasons.append('طبق برنامه ثبت‌شده باز است')
        score=round(min(99,45+(15 if prefs.get('brand') else 5)+(10 if prefs.get('query') else 0)+
            15*min_price/best['price_toman']+(14/(1+best['distance_km']/3) if location and best['distance_km'] is not None else 0)))
        results.append({'id':p.id,'title':p.title,'english_title':p.english_title,'brand':p.brand,'category':p.category,
            'model':p.model,'color_text':p.color_text,
            'best_offer':best,'offers':offers[:150 if product_id else 6],'offer_count':len(offers),
            'min_price_toman':min_price,'max_price_toman':max(o['price_toman'] for o in offers),'score':score,
            'reasons':reasons,'warnings':warnings,'visit_at':prefs.get('visit_at'),'source':'uploaded_dataset','torob_url':torob_search_url(p.title)})
    order=prefs.get('sort','recommended')
    if order=='price':results.sort(key=lambda r:r['best_offer']['price_toman'])
    elif order=='distance':results.sort(key=lambda r:(r['best_offer']['distance_km'] if r['best_offer']['distance_km'] is not None else float('inf'),r['best_offer']['price_toman']))
    else:results.sort(key=lambda r:(-r['score'],r['best_offer']['price_toman']))
    if results:
        cheapest=min(results,key=lambda r:r['min_price_toman'])['id']
        nearby=[r for r in results if r['best_offer']['distance_km'] is not None]
        closest=min(nearby,key=lambda r:r['best_offer']['distance_km'])['id'] if nearby else None
        for i,r in enumerate(results):r['badges']=(['پیشنهاد ترب‌یار'] if i==0 and order=='recommended' else [])+(['کمترین قیمت'] if r['id']==cheapest else [])+(['نزدیک‌ترین پیشنهاد'] if r['id']==closest else [])
    visible=results[:limit]
    documents={p.id:p for p in Product.objects.filter(pk__in=[r['id'] for r in visible]).only('id','images','specs')}
    for result in visible:
        document=documents[result['id']]
        result['images']=[u for u in document.images if safe_url(u)]
        result['specs']=document.specs
    return {'products':visible,'matched_count':len(results),'candidate_cap':1500,'source':'uploaded_dataset',
        'origin':location,'distance_note':'فاصله خط مستقیم است؛ مسافت و زمان مسیر خیابانی نیست.'}
