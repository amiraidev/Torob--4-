"""Google search evidence. Snippets are not live seller prices or verified facts."""
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
from django.conf import settings
from .places import api_json,ProviderError,timestamp
from .common import safe_url
from .pages import read_result
from .request_budget import submit

def google_search(query):
    manual='https://www.google.com/search?'+urlencode({'q':query})
    if not settings.WEB_RESEARCH_ENABLED:return {'status':'disabled','sources':[],'search_url':manual}
    if not settings.SERPER_API_KEY:return {'status':'not_configured','sources':[],'search_url':manual,
        'message':'برای جست‌وجوی خودکار گوگل، SERPER_API_KEY را تنظیم کن؛ لینک جست‌وجوی دستی در دسترس است.'}
    try:
        data=api_json('google_search','POST','https://google.serper.dev/search',json={'q':query,'gl':'ir','hl':'fa','num':5},headers={'X-API-KEY':settings.SERPER_API_KEY,'Content-Type':'application/json'})
        sources=[]
        for row in data.get('organic',[])[:5]:
            if not isinstance(row,dict):continue
            url=safe_url(row.get('link'))
            if url:sources.append({'title':str(row.get('title') or '')[:250],'url':url,
                'snippet':str(row.get('snippet') or '')[:1200],'published_text':str(row.get('date') or '')[:80],
                'retrieved_at':timestamp(),'evidence_type':'search_snippet','provider':'google_via_serper'})
        if sources and settings.WEB_PAGE_FETCH_ENABLED:
            with ThreadPoolExecutor(max_workers=2) as pool:
                checked=[j.result() for j in [submit(pool,read_result,s,query) for s in sources[:2]]]
            sources=checked+sources[2:]
        return {'status':'ok','sources':sources,'search_url':manual,'retrieved_at':timestamp(),
                'note':'خلاصه نتایج گوگل است؛ قیمت، موجودی، شماره تماس و شرایط اقساط باید در منبع اصلی تأیید شوند.'}
    except ProviderError as e:return {'status':e.code,'sources':[],'search_url':manual}

def research_product(prefs,products):
    query=' '.join(str(prefs.get(k) or '') for k in ('category','brand','query','model','product_type','needs')).strip()
    if not query:return {'status':'not_run','sources':[]}
    result=google_search(query+' مشخصات بررسی')
    for p in products[:3]:
        p.setdefault('research',{})['web_sources']=result['sources']
    return result
