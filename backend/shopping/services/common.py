import math
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlencode, urlsplit

TEHRAN = ZoneInfo('Asia/Tehran')
TRANSLATE = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩يك','01234567890123456789یک')
def normalize(value):
    return re.sub(r'\s+',' ',str(value or '').translate(TRANSLATE).replace('\u200c',' ').replace('٫','.').lower()).strip()

def safe_url(value, allowed_hosts=None):
    try:
        parsed = urlsplit(value or '')
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            return ''
        if allowed_hosts and parsed.hostname not in allowed_hosts: return ''
        return value
    except (ValueError,TypeError): return ''

def torob_search_url(title):
    return 'https://torob.com/search/?' + urlencode({'query':title})

def distance_km(lat1,lon1,lat2,lon2):
    if None in (lat1,lon1,lat2,lon2): return None
    a,b,c,d = map(math.radians,[lat1,lon1,lat2,lon2])
    h = math.sin((c-a)/2)**2 + math.cos(a)*math.cos(c)*math.sin((d-b)/2)**2
    return round(6371*2*math.asin(min(1,math.sqrt(h))),2)

def opening_status(hours,now=None):
    """Declared local shifts only. Yesterday's overnight shift may still be open."""
    now = (now or datetime.now(TEHRAN)).astimezone(TEHRAN)
    keys = ['mon','tue','wed','thu','fri','sat','sun']
    day = hours.get(keys[now.weekday()],{}) if isinstance(hours,dict) else {}
    minute = now.hour*60+now.minute
    def parse(t):
        try:
            h,m = str(t).split(':')[:2]
            h,m = int(h),int(m)
            if 0 <= h <= 24 and 0 <= m < 60 and (h<24 or m==0): return h*60+m
        except (ValueError,TypeError): pass
        return None
    yesterday = hours.get(keys[(now.weekday()-1)%7],{}) if isinstance(hours,dict) else {}
    for shift in yesterday.get('shifts',[]) if yesterday.get('status') == 'declared' else []:
        start,end = parse(shift.get('start_time')),parse(shift.get('end_time'))
        if start is not None and end is not None and start>end and minute<end:
            return {'state':'open','label':'طبق ساعت ثبت‌شده باز است','closes_at':shift.get('end_time','')[:5]}
    if day.get('status') == 'closed': return {'state':'closed','label':'طبق ساعت ثبت‌شده بسته است'}
    valid = False
    for shift in day.get('shifts',[]) if day.get('status') == 'declared' else []:
        start,end = parse(shift.get('start_time')),parse(shift.get('end_time'))
        if start is None or end is None or start==end: continue
        valid = True
        if (start<end and start<=minute<end) or (start>end and minute>=start):
            return {'state':'open','label':'طبق ساعت ثبت‌شده باز است','closes_at':shift.get('end_time','')[:5]}
    if valid: return {'state':'closed','label':'طبق ساعت ثبت‌شده بسته است'}
    return {'state':'unknown','label':'ساعت کاری مشخص نیست'}

def payment_matches(option,category,provider=None):
    if option.get('channel') != 'in_person': return False
    if provider and normalize(option.get('provider_name')) != normalize(provider): return False
    cats = option.get('category_names') or []
    return not cats or normalize(category) in {normalize(x) for x in cats}
