"""Observed public read endpoints. Browser origins and credentials are never forwarded."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import re
import uuid
from urllib.parse import urljoin, urlsplit
import requests
from django.conf import settings
from django.core.cache import cache
from .common import safe_url, torob_search_url, normalize, opening_status, distance_km, payment_matches
from .request_budget import http_timeout,submit,BudgetExceeded

API = 'https://api.torob.com'
ALLOWED_PATHS = {'/v4/base-product/search/', '/v4/base-product/details/',
                 '/v4/base-product/map/sellers/', '/v4/product-in-store/contact-info/'}

class LiveSearchError(Exception):
    def __init__(self, message, code='torob_unavailable'):
        super().__init__(message)
        self.code = code

def get_json(url, params=None):
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == 'https' and parsed.hostname == 'api.torob.com'
                 and parsed.port in (None, 443) and parsed.path in ALLOWED_PATHS
                 and not parsed.username and not parsed.password)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise LiveSearchError('مسیر دریافت اطلاعات از ترب معتبر نیست.', 'invalid_torob_endpoint')
    try:
        response = requests.get(url, params=params,
            headers={'User-Agent': 'TorobYar/1.1 (in-person shopping assistant)'},
            timeout=http_timeout(12,15), allow_redirects=False)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        code = str(payload.get('error', payload.get('code', ''))) if isinstance(payload, dict) else ''
        if 'origin_not_allowed' in code:
            raise LiveSearchError('ترب مبدأ این درخواست سروری را نپذیرفت. پاسخ زنده در دسترس نیست؛ این خطا به معنی پیدا نشدن محصول نیست.', 'torob_origin_not_allowed')
        if response.status_code in (403, 429):
            raise LiveSearchError('ترب این درخواست را نپذیرفت. کمی بعد دوباره تلاش کن یا جستجو را در خود ترب باز کن.', 'torob_access_limited')
        if 300 <= response.status_code < 400:
            raise LiveSearchError('ترب درخواست را به مسیر دیگری هدایت کرد؛ اتصال نیاز به بررسی دارد.', 'torob_redirect')
        response.raise_for_status()
        if not isinstance(payload, dict) or not payload:
            raise LiveSearchError('قالب پاسخ ترب تغییر کرده یا پاسخ خالی است.', 'torob_invalid_response')
        return payload
    except LiveSearchError:
        raise
    except (requests.Timeout,BudgetExceeded):
        raise LiveSearchError('مهلت اتصال سرور به ترب تمام شد. اینترنت یا پراکسی سرور را بررسی کن و دوباره تلاش کن.','torob_timeout')
    except requests.exceptions.SSLError:
        raise LiveSearchError('اعتبارسنجی گواهی امن اتصال به ترب ناموفق بود. تنظیم گواهی‌های سیستم یا پراکسی را بررسی کن.','torob_tls_error')
    except (requests.RequestException, ValueError, TypeError, KeyError):
        raise LiveSearchError('ارتباط سرور Django با ترب برقرار نشد. اتصال اینترنت یا پراکسی سرور را بررسی کن.')

def route_key(kind, value):
    return 'torob:' + kind + ':' + hashlib.sha256(str(value).encode()).hexdigest()

def search_live(query):
    if not settings.TOROB_LIVE_ENABLED:
        raise LiveSearchError('جستجوی زنده در تنظیمات سرور غیرفعال است.', 'torob_disabled')
    key = route_key('search', query)
    saved = cache.get(key)
    if saved is not None:
        return {**saved, 'cached': True}
    payload = get_json(API + '/v4/base-product/search/', {
        'page': 0, 'sort': 'popularity', 'size': 24, 'query': query, 'q': query, 'source': 'next_desktop'})
    if not isinstance(payload.get('results'), list):
        raise LiveSearchError('قالب پاسخ جستجوی ترب تغییر کرده است.', 'torob_invalid_response')
    products = []
    for row in payload['results']:
        if not isinstance(row, dict) or row.get('is_adv') or not row.get('name1'):
            continue
        product_id = str(row.get('random_key', ''))
        url = safe_url(urljoin('https://torob.com', row.get('web_client_absolute_url') or ''), {'torob.com'})
        price = row.get('price')
        products.append({'id': product_id, 'title': row['name1'], 'english_title': row.get('name2', ''),
            'image': safe_url(row.get('image_url', ''), {'image.torob.com'}),
            'price_toman': int(price) if isinstance(price, (int, float)) and price > 0 else None,
            'shop_text': row.get('shop_text', ''), 'url': url or torob_search_url(row['name1']),
            'source': 'torob_live', 'local_shop_match': False})
        cache.set(route_key('base-route', product_id), {'details_url': row.get('more_info_url'), 'url': url}, 300)
    result = {'products': products[:24], 'source': 'torob_live',
        'retrieved_at': datetime.now(timezone.utc).isoformat(), 'cached': False,
        'search_url': torob_search_url(query), 'status': 'ok',
        'note': 'قیمت بازار ترب؛ برای خرید حضوری، پیشنهاد و مختصات همان فروشنده جداگانه بررسی می‌شود.'}
    cache.set(key, result, 300)
    return result

def raw_product(product_id):
    try:
        uuid.UUID(product_id)
    except (ValueError, TypeError):
        raise LiveSearchError('شناسه محصول ترب معتبر نیست.', 'invalid_product_id')
    key = route_key('detail', product_id)
    saved = cache.get(key)
    if saved is not None:
        return saved
    route = cache.get(route_key('base-route', product_id)) or {}
    url = route.get('details_url') or API + '/v4/base-product/details/?prk=' + product_id + '&source=next_desktop'
    data = get_json(url)
    if data.get('random_key') != product_id:
        raise LiveSearchError('پاسخ جزئیات به این محصول تعلق ندارد.', 'product_identity_mismatch')
    block = data.get('products_in_store_info') or {}
    if not isinstance(block,dict):raise LiveSearchError('قالب فروشندگان حضوری ترب تغییر کرده است.','torob_invalid_response')
    map_url = block.get('map_sellers_api_url')
    rows = block.get('result') or []
    if not isinstance(rows,list):raise LiveSearchError('قالب فهرست فروشندگان ترب معتبر نیست.','torob_invalid_response')
    map_failed = False
    if map_url:
        try:
            mapped = get_json(map_url)
            if isinstance(mapped.get('result'), list):
                rows = mapped['result']
        except LiveSearchError:
            map_failed = True  # Keep declared city data; never invent missing coordinates.
    value = {'base': data, 'sellers': rows, 'map_failed':map_failed, 'retrieved_at': datetime.now(timezone.utc).isoformat()}
    cache.set(key, value, 300)
    return value

DAY_KEYS = {'شنبه': 'sat', 'یکشنبه': 'sun', 'دوشنبه': 'mon', 'سه شنبه': 'tue',
            'چهارشنبه': 'wed', 'پنجشنبه': 'thu', 'جمعه': 'fri'}

def schedule_hours(working):
    hours = {}
    if not isinstance(working,(dict,type(None))):return hours
    for item in (working or {}).get('schedule', []):
        if not isinstance(item,dict):continue
        title = normalize(item.get('title', '')).replace('(امروز)', '').strip()
        key = next((value for label,value in DAY_KEYS.items() if label.replace(' ','')==title.replace(' ','')),None)
        if not key:
            continue
        text = normalize(item.get('text', ''))
        if 'تعطیل' in text or 'بسته' in text:
            hours[key] = {'status': 'closed', 'shifts': []}
            continue
        times = re.findall(r'\b([0-2]?\d:[0-5]\d)\b', text)
        if len(times) >= 2 and len(times) % 2 == 0:
            hours[key] = {'status': 'declared', 'shifts': [
                {'start_time': a + ':00', 'end_time': b + ':00'} for a, b in zip(times[::2], times[1::2])]}
    return hours

def price_age(text):
    text = normalize(text)
    if any(value in text for value in ['دقیقه', 'ساعت', 'امروز', 'همین الان']):
        return 0
    if 'دیروز' in text:
        return 1
    units = {'روز': 1, 'هفته': 7, 'ماه': 30, 'سال': 365}
    found = re.findall(r'(\d+)\s*(روز|هفته|ماه|سال)', text)
    return sum(int(n) * units[unit] for n, unit in found) if found else None

def coordinates(row):
    location = row.get('location') or row.get('coordinates') or {}
    try:
        lat, lon = float(location['lat']), float(location['lon'])
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    except (ValueError, TypeError, KeyError):
        pass
    return None, None

def is_tehran(row, lat, lon):
    city = normalize(row.get('shop_name2', '')).split('،')[0].strip()
    if city:
        return city in ('تهران', 'شهر تهران')
    return lat is not None and 35.5 <= lat <= 35.9 and 51.05 <= lon <= 51.65

def payments_for(row):
    installment = row.get('installment') or {}
    return [{'provider_name': p.get('name') or p.get('short_title') or 'اقساط اعلام‌شده',
             'channel': p.get('channel') if p.get('channel') in ('in_person','online') else 'in_person' if p.get('supports_in_person') is True else 'unknown', 'category_names': [],
             'description': p.get('description') or p.get('title') or ''}
            for p in installment.get('providers', []) if isinstance(p, dict)]

def normalize_live_product(raw, prefs, location=None):
    base = raw['base']
    product_id = base['random_key']
    offers = []
    now = datetime.now(timezone.utc)
    visit = prefs.get('visit_at') or now
    if isinstance(visit, str):
        from django.utils.dateparse import parse_datetime
        visit = parse_datetime(visit) or now
    specs = []
    for section in (base.get('structural_specs') or {}).get('headers', []):
        for key, value in (section.get('specs') or {}).items():
            specs.append({'key': key, 'value': value, 'section': section.get('header', '')})
    color_values = ' '.join(str(s['value']) for s in specs if 'رنگ' in s['key'])
    title = str(base.get('name1', ''))
    from .preferences import product_matches,variant_matches
    if not product_matches(title,base.get('name2',''),prefs):return None
    for row in raw['sellers']:
        if not isinstance(row, dict):
            continue
        lat, lon = coordinates(row)
        if not is_tehran(row, lat, lon):
            continue
        price = row.get('price')
        if not isinstance(price, (int, float)) or price <= 0 or row.get('is_price_unreliable'):
            continue
        if price < prefs.get('budget_min', 0) or (prefs.get('budget_max') and price > prefs['budget_max']):
            continue
        seller_text = str(row.get('name2') or '')
        if not variant_matches(seller_text+' '+str(row.get('name1') or ''),prefs,title):
            continue
        hours = schedule_hours(row.get('working_hours'))
        opening = opening_status(hours, visit)
        if prefs.get('only_open') and opening['state'] != 'open':
            continue
        distance = distance_km(location['lat'], location['lon'], lat, lon) if location else None
        if prefs.get('radius_km') and (distance is None or distance > prefs['radius_km']):
            continue
        payments = payments_for(row)
        if prefs.get('installment') and not any(payment_matches(p,prefs.get('category','')) for p in payments):
            continue
        if prefs.get('torobpay') and not any(payment_matches(p, prefs.get('category', ''), 'ترب‌پی') for p in payments):
            continue
        if prefs.get('fast_delivery') and row.get('supports_fast_delivery') is not True:
            continue
        images = [m['url'] for m in (row.get('media') or []) if m.get('type') == 'image'
                  and safe_url(m.get('url', ''), {'image.torob.com'})]
        if not images:
            thumb = (row.get('image_info') or {}).get('thumbnail_image_url')
            if safe_url(thumb, {'image.torob.com'}):
                images = [thumb]
        shop_id = 'torob_shop_' + str(row.get('shop_id', ''))
        offer_id = 'torob_offer_' + str(row.get('prk', ''))
        contact_url = row.get('map_seller_card_page_url') or row.get('page_url')
        if contact_url:
            cache.set(route_key('offer-route', offer_id), {'url': contact_url, 'product_id': product_id}, 300)
        age = price_age(row.get('last_price_change_date', ''))
        offers.append({'id': offer_id, 'product_id': 'torob_' + product_id, 'seller_title': title,
            'description': seller_text, 'price_toman': int(price), 'currency': 'تومان',
            'warranty': seller_text if re.search('گارانتی|ضمانت',seller_text) else None, 'last_price_changed_at': None,
            'last_price_change_text': row.get('last_price_change_date') or 'ثبت نشده',
            'price_age_days': age, 'price_age_approximate': True,
            'price_stale': age is None or age > settings.PRICE_FRESH_DAYS,
            'distance_km': distance, 'distance_type': 'straight_line', 'availability': 'live_listing',
            'source': 'torob_live', 'retrieved_at': raw['retrieved_at'],
            'shop': {'id': shop_id, 'name': row.get('shop_name') or 'فروشگاه',
                'business_type': None, 'description': None, 'categories': [prefs['category']] if prefs.get('category') else [],
                'images': images, 'licenses': [], 'torob_since': None,
                'address': row.get('address') or row.get('name1') or '', 'address_complete': False,
                'location_label': row.get('shop_name2') or '', 'lat': lat, 'lon': lon,
                'opening': opening, 'weekly_hours': hours, 'contacts': [],
                'contacts_published': settings.PUBLISH_PHONE_CONTACTS,
                'payment_options': payments, 'supports_fast_delivery': row.get('supports_fast_delivery'),
                'supports_kalabarg': None, 'website_url': '', 'source': 'torob_live'}})
    if not offers:
        return None
    cheapest = min(o['price_toman'] for o in offers)
    def score(offer):
        return (45 * cheapest / offer['price_toman'] +
                (35 / (1 + offer['distance_km'] / 3) if location and offer['distance_km'] is not None else 0) +
                {'open': 20, 'unknown': 4, 'closed': 0}[offer['shop']['opening']['state']])
    sort = prefs.get('sort', 'recommended')
    offers.sort(key=lambda o: o['price_toman'] if sort == 'price' else
        (o['distance_km'] if o['distance_km'] is not None else float('inf'), o['price_toman'])
        if sort == 'distance' else -score(o))
    best = offers[0]
    reasons = ['ارتباط محصول و فروشنده حضوری از ترب دریافت شده است']
    if prefs.get('budget_max'):
        reasons.append('قیمت همین فروشنده در بودجه تو است')
    if best['distance_km'] is not None:
        reasons.append('فاصله بر اساس مختصات همین فروشگاه و مبدأ تو')
    reasons.append(best['shop']['opening']['label'])
    warnings = ['دریافت زنده آگهی، تضمین موجودی لحظه‌ای یا حضور فروشنده نیست.']
    if best['price_stale']:
        warnings.append('تاریخ تغییر قیمت این فروشنده قدیمی یا نامشخص است.')
    if prefs.get('color'):
        warnings.append('تطبیق رنگ از متن ثبت‌شده است؛ موجودی همان رنگ نیاز به تأیید دارد.')
    images = base.get('image_urls') or [m.get('url') for m in base.get('media_urls', []) if m.get('type') == 'image']
    if not images:
        images = [base.get('image_url')]
    return {'id': 'torob_' + product_id, 'live_id': product_id, 'title': title,
        'english_title': base.get('name2', ''), 'brand': prefs.get('brand', ''),
        'category': prefs.get('category', ''), 'model': prefs.get('model') or prefs.get('query', ''),
        'specs': specs, 'images': [u for u in images if safe_url(u, {'image.torob.com'})],
        'best_offer': best, 'offers': offers, 'offer_count': len(offers),
        'min_price_toman': cheapest, 'max_price_toman': max(o['price_toman'] for o in offers),
        'score': round(min(99, 35 + score(best) * .64)), 'reasons': reasons, 'warnings': warnings,
        'source': 'torob_live', 'badges': [], 'retrieved_at': raw['retrieved_at'], 'visit_at':prefs.get('visit_at'),
        'torob_url': safe_url(urljoin('https://torob.com', base.get('web_client_absolute_url') or ''), {'torob.com'}) or torob_search_url(title)}

def search_live_in_person(prefs, location=None, *, product_limit=None):
    from .preferences import product_matches
    query = ' '.join(dict.fromkeys(x for x in [prefs.get('category'),prefs.get('brand'),prefs.get('query'),prefs.get('model'),prefs.get('product_type')] if x)).strip()
    market = search_live(query)
    candidates = [p for p in market['products'] if product_matches(p['title'],p.get('english_title',''),prefs)]
    if prefs.get('brand'):
        from .intent import BRANDS, mentions
        aliases=[prefs['brand'],*BRANDS.get(prefs['brand'],[])]
        candidates=[p for p in candidates if any(mentions(normalize(p['title']+' '+p.get('english_title','')),a) for a in aliases)]
    from .intent import mentions
    tokens = re.findall(r'[^\W_]+', normalize(prefs.get('query', '')), re.UNICODE)
    if tokens:
        candidates = [p for p in candidates if all(mentions(normalize(p['title']+' '+p.get('english_title','')),t) for t in tokens)]
    if prefs.get('category')=='گوشی موبایل':
        candidates=[p for p in candidates if not re.match(r'^(قاب|کاور|گلس|شارژر|باتری|کیف|کابل)\b',normalize(p['title']))]
    if prefs.get('budget_max'):
        maximum=prefs['budget_max'];minimum=prefs.get('budget_min',0)
        # Market prices choose which products to inspect first, never replace an in-person seller's price.
        candidates=sorted(candidates,key=lambda p:(0,0) if p.get('price_toman') and minimum<=p['price_toman']<=maximum else
            (1,abs((p.get('price_toman') or maximum*2)-maximum)))
    candidates = candidates[:min(settings.TOROB_LIVE_PRODUCT_LIMIT,product_limit) if product_limit is not None else settings.TOROB_LIVE_PRODUCT_LIMIT]
    products = []
    failures = 0
    with ThreadPoolExecutor(max_workers=min(3, len(candidates) or 1)) as pool:
        jobs = [submit(pool,raw_product, p['id']) for p in candidates]
        for job in as_completed(jobs):
            try:
                raw = job.result()
                if raw.get('map_failed'):failures += 1
                product = normalize_live_product(raw, prefs, location)
                if product:
                    products.append(product)
            except (LiveSearchError,ValueError,TypeError,KeyError,AttributeError):
                failures += 1
    sort = prefs.get('sort', 'recommended')
    products.sort(key=lambda p: p['best_offer']['price_toman'] if sort == 'price' else
        (p['best_offer']['distance_km'] if p['best_offer']['distance_km'] is not None else float('inf'), p['best_offer']['price_toman'])
        if sort == 'distance' else -p['score'])
    for i, product in enumerate(products):
        product['badges'] = ['پیشنهاد زنده ترب‌یار' if i == 0 else 'فروشنده حضوری ترب']
    # Both tabs show the matching seller and variant, never an unrelated online minimum.
    market = {**market,'products':[{'id':p['live_id'],'title':p['title'],'english_title':p['english_title'],
        'image':(p['images'] or [''])[0],'price_toman':p['best_offer']['price_toman'],
        'shop_text':p['best_offer']['shop']['name'],'url':p['torob_url'],
        'source':'torob_live','local_shop_match':True,'price_scope':'matching_in_person_offer',
        'retrieved_at':p['retrieved_at']} for p in products], 'filters_applied':True,
        'note':'قیمت پیشنهاد حضوری سازگار با تمام فیلترها؛ اقساط ناشناخته یا صرفاً آنلاین پذیرفته نمی‌شود.'}
    if failures:
        market={**market,'status':'partial','message':'جزئیات بعضی از محصولات از ترب دریافت نشد؛ نتیجه فقط بر اساس داده‌های دریافت‌شده است.'}
    return {'products': products, 'matched_count': len(products), 'source': 'torob_live',
        'origin': location, 'visit_at': prefs.get('visit_at'), 'market': market,
        'checked_product_count': len(candidates), 'detail_failures': failures,
        'distance_note': 'فاصله خط مستقیم است؛ ساعت کاری بر اساس برنامه ثبت‌شده و زمان مراجعه محاسبه می‌شود.'}

def enrich_offer(offer, product_id):
    route = cache.get(route_key('offer-route', offer['id']))
    if not route or route['product_id'] != product_id:
        return offer
    key = route_key('contact', offer['id'])
    contact = cache.get(key)
    if contact is None:
        contact = get_json(route['url'])
        cache.set(key, contact, 300)
    shop = {**offer['shop']}
    if contact.get('address'):
        shop['address'] = contact['address']
        shop['address_complete'] = True
    lat, lon = coordinates(contact)
    if lat is not None:
        shop['lat'], shop['lon'] = lat, lon
    if isinstance(contact.get('images'), list):
        shop['images'] = [u for u in contact['images'] if safe_url(u, {'image.torob.com'})]
    if settings.PUBLISH_PHONE_CONTACTS:
        shop['contacts'] = [{'channel': 'phone', 'display_number': contact[k]}
                            for k in ('phone', 'second_phone') if isinstance(contact.get(k), str)]
    return {**offer, 'shop': shop}

def live_product_detail(product_id, prefs, location=None):
    product = normalize_live_product(raw_product(product_id), prefs, location)
    if product:
        best = product['best_offer']
        try:
            best = enrich_offer(best, product_id)
        except LiveSearchError:
            pass
        product['best_offer'] = best
        product['offers'] = [best if o['id'] == best['id'] else o for o in product['offers']]
    return product

def live_offer_detail(product_id,offer_id,prefs,location=None):
    product=normalize_live_product(raw_product(product_id),prefs,location)
    offer=next((o for o in product['offers'] if o['id']==offer_id),None) if product else None
    if not offer:return None
    result=enrich_offer(offer,product_id)
    if location:result['distance_km']=distance_km(location['lat'],location['lon'],result['shop']['lat'],result['shop']['lon'])
    return result
