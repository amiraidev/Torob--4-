"""Neshan v3/v5/v1 and Google Places; keep each business's evidence separate."""
import json
import math
import re
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
import requests
from django.conf import settings
from django.core import signing
from .common import safe_url,distance_km,opening_status,normalize
from .request_budget import http_timeout,submit,BudgetExceeded

class ProviderError(Exception):
    def __init__(self,provider,code):self.provider=provider;self.code=code

def timestamp():return datetime.now(timezone.utc).isoformat()

def selectable(place):
    evidence={k:v for k,v in place.items() if k not in ('selection_token','distance_km')}
    return {**place,'selection_token':signing.dumps(evidence,salt='shopping-place-v2',compress=True)}

def selected_place(token):
    try:
        data=signing.loads(token,salt='shopping-place-v2',max_age=300)
        if isinstance(data,dict) and data.get('provider') in ('neshan','google_places'):
            return {**data,'identity_status':'selected_candidate'}
    except (signing.BadSignature,ValueError,TypeError):pass
    return None

def api_json(provider,method,url,**kwargs):
    try:
        r=requests.request(method,url,timeout=http_timeout(3,settings.RESEARCH_TIMEOUT),allow_redirects=False,**kwargs)
        if r.status_code in (401,403,480,483,484,485):raise ProviderError(provider,'access_denied')
        if r.status_code in (429,481,482):raise ProviderError(provider,'rate_limited')
        if not 200<=r.status_code<300:raise ProviderError(provider,'unavailable')
        if len(r.content)>2_000_000:raise ProviderError(provider,'invalid_response')
        data=r.json()
        if not isinstance(data,dict):raise ValueError()
        return data
    except BudgetExceeded:raise ProviderError(provider,'timeout') from None
    except (requests.RequestException,ValueError,TypeError):raise ProviderError(provider,'unavailable') from None

def links(name,lat=None,lon=None):
    if lat is not None and lon is not None:
        return {'neshan_url':'https://nshn.ir/?'+urlencode({'lat':lat,'lng':lon}),
                'google_maps_url':'https://www.google.com/maps/search/?'+urlencode({'api':1,'query':f'{lat},{lon}'})}
    return {'neshan_url':'https://neshan.org/maps/?'+urlencode({'search':name}),
            'google_maps_url':'https://www.google.com/maps/search/?'+urlencode({'api':1,'query':name})}

def point(value):
    try:
        lat=float(value.get('y',value.get('latitude')));lon=float(value.get('x',value.get('longitude')))
        if all(math.isfinite(x) for x in (lat,lon)) and -90<=lat<=90 and -180<=lon<=180:return lat,lon
    except (ValueError,TypeError,AttributeError):pass
    return None,None

def phone(value):
    if not isinstance(value,str):return ''
    p=normalize(value).replace(' ','').replace('-','').replace('(','').replace(')','')
    return p if re.fullmatch(r'\+?\d{7,15}',p) else ''

def website(value):
    if not isinstance(value,str) or not value:return ''
    if re.match(r'^[a-z][a-z0-9+.-]*:',value,re.I) and not value.lower().startswith('https://'):return ''
    url=safe_url(value if '://' in value else 'https://'+value)
    try:
        from urllib.parse import urlsplit
        parsed=urlsplit(url)
        if parsed.port not in (None,443) or not parsed.hostname or '.' not in parsed.hostname:return ''
    except ValueError:return ''
    return url

def neshan_search(query,location):
    if not settings.NESHAN_SERVICE_KEY:raise ProviderError('neshan','not_configured')
    if not location:raise ProviderError('neshan','location_required')
    q={'term':query,'center':{'latitude':location['lat'],'longitude':location['lon']}}
    data=api_json('neshan','GET','https://api.neshan.org/v3/search',params={'q':json.dumps(q,ensure_ascii=False)},headers={'Api-Key':settings.NESHAN_SERVICE_KEY})
    rows=data.get('items')
    if not isinstance(rows,list):raise ProviderError('neshan','invalid_response')
    result=[]
    for row in rows[:15]:
        if not isinstance(row,dict):continue
        if row.get('category') and row['category']!='place':continue
        lat,lon=point(row.get('location'))
        result.append({'id':'neshan:'+str(row.get('poiHash') or len(result)), 'provider':'neshan',
            'poi_hash':str(row.get('poiHash') or ''),'name':str(row.get('title') or ''),
            'address':str(row.get('address') or ''),'region':row.get('region') or '',
            'category':row.get('category'),'lat':lat,'lon':lon,'contacts':[], 'weekly_hours':{},
            'opening':{'state':'unknown','label':'ساعت کاری مشخص نیست'},'website_url':'',
            'distance_km':distance_km(location['lat'],location['lon'],lat,lon),
            'retrieved_at':timestamp(),'identity_status':'candidate','source_url':'https://platform.neshan.org',
            **links(row.get('title',''),lat,lon)})
    return result

def neshan_detail(poi_hash):
    if not settings.NESHAN_SERVICE_KEY:raise ProviderError('neshan','not_configured')
    if not re.fullmatch(r'[A-Za-z0-9_-]{3,500}',poi_hash):raise ProviderError('neshan','invalid_id')
    data=api_json('neshan','GET','https://api.neshan.org/v1/point',params={'hash':poi_hash},headers={'Api-Key':settings.NESHAN_SERVICE_KEY})
    if not data.get('name'):raise ProviderError('neshan','invalid_response')
    lat,lon=point(data.get('location'));hours={}
    days={'شنبه':'sat','یکشنبه':'sun','دوشنبه':'mon','سهشنبه':'tue','چهارشنبه':'wed','پنجشنبه':'thu','جمعه':'fri'}
    for row in data.get('workHours',[]) if isinstance(data.get('workHours'),list) else []:
        if not isinstance(row,dict):continue
        key=days.get(normalize(row.get('day')).replace(' ',''))
        if not key:continue
        shifts=[{'start_time':x['start'],'end_time':x['end']} for x in row.get('ranges',[]) if isinstance(x,dict) and re.fullmatch(r'\d{2}:\d{2}',str(x.get('start',''))) and re.fullmatch(r'\d{2}:\d{2}',str(x.get('end','')))]
        hours[key]={'status':'declared' if shifts else 'closed','shifts':shifts}
    p=phone(data.get('phoneNumber'))
    return selectable({'id':'neshan:'+poi_hash,'poi_hash':poi_hash,'provider':'neshan','name':str(data['name']),
        'address':str(data.get('address') or ''),'lat':lat,'lon':lon,'weekly_hours':hours,
        'opening':opening_status(hours),'website_url':website(data.get('website')),
        'contacts':[{'channel':'phone','display_number':p,'source':'neshan_poi','retrieved_at':timestamp()}] if p and settings.PUBLISH_PHONE_CONTACTS else [],
        'retrieved_at':timestamp(),'identity_status':'selected_candidate',
        'source_url':links(data['name'],lat,lon)['neshan_url'],**links(data['name'],lat,lon)})

def reverse(location):
    if not settings.NESHAN_SERVICE_KEY:raise ProviderError('neshan','not_configured')
    data=api_json('neshan','GET','https://api.neshan.org/v5/reverse',params={'lat':location['lat'],'lng':location['lon']},headers={'Api-Key':settings.NESHAN_SERVICE_KEY})
    return {'address':str(data.get('formatted_address') or ''),'neighbourhood':data.get('neighbourhood'),
            'city':data.get('city'),'place':data.get('place'),'source':'neshan_reverse','retrieved_at':timestamp(),
            'indoor_precision':False,'accuracy_m':location.get('accuracy_m'),
            'note':'این آدرس محدوده GPS است؛ نام مغازه، طبقه و واحد از آن قابل تشخیص قطعی نیست.'}

GOOGLE_FIELDS='places.id,places.displayName,places.formattedAddress,places.location,places.nationalPhoneNumber,places.internationalPhoneNumber,places.websiteUri,places.googleMapsUri,places.currentOpeningHours,places.attributions'
def google_places(query,location=None):
    if not settings.GOOGLE_PLACES_API_KEY:raise ProviderError('google_places','not_configured')
    body={'textQuery':query,'languageCode':'fa','pageSize':5}
    if location:body['locationBias']={'circle':{'center':{'latitude':location['lat'],'longitude':location['lon']},'radius':1500.0}}
    data=api_json('google_places','POST','https://places.googleapis.com/v1/places:searchText',json=body,
        headers={'X-Goog-Api-Key':settings.GOOGLE_PLACES_API_KEY,'X-Goog-FieldMask':GOOGLE_FIELDS})
    result=[]
    for row in data.get('places',[])[:5]:
        if not isinstance(row,dict):continue
        lat,lon=point(row.get('location'));p=phone(row.get('nationalPhoneNumber') or row.get('internationalPhoneNumber'))
        name=str((row.get('displayName') or {}).get('text') or '')
        result.append({'id':'google:'+str(row.get('id') or len(result)),'provider':'google_places','name':name,
            'address':str(row.get('formattedAddress') or ''),'lat':lat,'lon':lon,
            'website_url':website(row.get('websiteUri')),'weekly_hours':{},
            'opening':{'state':'open' if (row.get('currentOpeningHours') or {}).get('openNow') is True else 'closed' if (row.get('currentOpeningHours') or {}).get('openNow') is False else 'unknown',
                'label':'طبق وضعیت دریافت‌شده از گوگل اکنون باز است' if (row.get('currentOpeningHours') or {}).get('openNow') is True else 'طبق وضعیت دریافت‌شده از گوگل اکنون بسته است' if (row.get('currentOpeningHours') or {}).get('openNow') is False else 'ساعت کاری مشخص نیست'},
            'reported_open_now':(row.get('currentOpeningHours') or {}).get('openNow'),
            'hours_text':(row.get('currentOpeningHours') or {}).get('weekdayDescriptions') or [],
            'contacts':[{'channel':'phone','display_number':p,'source':'google_places','retrieved_at':timestamp()}] if p and settings.PUBLISH_PHONE_CONTACTS else [],
            'attributions':row.get('attributions') or [],'source_url':safe_url(row.get('googleMapsUri')) or links(name,lat,lon)['google_maps_url'],
            'retrieved_at':timestamp(),'identity_status':'candidate','distance_km':distance_km(location['lat'],location['lon'],lat,lon) if location else None,
            **links(name,lat,lon)})
    return result

def search_places(query,location=None):
    statuses={};candidates=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[('neshan',submit(pool,neshan_search,query,location)),('google_places',submit(pool,google_places,query,location))]
        for name,job in jobs:
            try:candidates.extend(job.result());statuses[name]='ok'
            except ProviderError as e:statuses[name]=e.code
    return {'candidates':[selectable(p) for p in candidates],'providers':statuses,'requires_selection':bool(candidates),
            'note':'نام و آدرس نتیجه را تطبیق بده؛ ورود به پاساژ به معنی شناسایی خودکار مغازه نیست.'}
