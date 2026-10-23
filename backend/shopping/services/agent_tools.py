"""Read-only, allowlisted tools for the shopping agent. No arbitrary URLs or code."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import re
from shopping.serializers import PreferencesSerializer
from .agent_evidence import compact_product, eligible, text
from .common import normalize
from .live import search_live_in_person, live_product_detail, LiveSearchError
from .search import search_products
from .places import search_places, neshan_detail, reverse, ProviderError, selectable
from .web_research import google_search
from .agent_values import monetary_amounts

TOOL_GUIDE = {
 'search_products': {'arguments': {'query':'optional short product keywords'},
   'description':'Search the user-selected live Torob or recorded dataset. Existing hard filters apply. Returns at most 8 products; live checks at most 3 base products. Repeated identical calls are cached for this turn.'},
 'get_products': {'arguments': {'product_ids':['1 to 3 canonical IDs'], 'spec_keys':['optional up to 8 exact spec keys']},
   'description':'Refresh exact products for comparison. IDs must already be visible or explicitly selected in comparison_ids. Torob IDs start torob_. Never construct an ID.'},
 'web_search': {'arguments': {'query':'specific research or store query'},
   'description':'Google via Serper and public page excerpts. Cannot confirm seller prices, stock, payment or identity from snippets. Reports not_configured when key is absent.'},
 'find_stores': {'arguments': {'query':'store or mall name plus known area'},
   'description':'Search Neshan and Google Places. Candidates need user selection. GPS cannot identify a shop, floor or unit.'},
 'store_details': {'arguments': {'place_id':'ID returned by find_stores or selected_store'},
   'description':'Fetch a known Neshan candidate or inspect already retrieved Google Places details. This does not select a store on behalf of the user.'},
 'locate_user': {'arguments': {}, 'description':'Reverse geocode only actual supplied location. No invented coordinates. Fails when GPS/area has not been supplied.'},
 'compare_quote': {'arguments': {'product_id':'known product ID','offer_ids':['optional up to 3 known offer IDs'],
                                'quote_toman':'optional integer; otherwise visit.quoted_price','evidence_quote':'exact latest user quote if quote_toman supplied'},
   'description':'Compare a user-declared shop price with canonical retrieved offers; exact integer differences. Only meaningful for the same model, variant, condition and warranty; this is not evidence of current stock.'},
 'calculate_payments': {'arguments': {'cash':10000000,'down':2000000,'monthly':1000000,'count':10,'fees':0,
                                     'evidence_quote':'exact text from latest user message containing all terms'},
   'description':'Exact arithmetic for user-declared terms in TOMAN. Required fields include fees (0 only if user says no fees). Never assume loan terms, zero fees or acceptance.'},
}

class ToolInputError(ValueError): pass

def arguments(raw, allowed):
    if not isinstance(raw,dict) or any(k not in allowed for k in raw):raise ToolInputError('Unknown or invalid tool arguments.')
    return raw

def string(raw, key, maximum=250, required=True):
    value=raw.get(key,'')
    if not isinstance(value,str) or len(value)>maximum or (required and not value.strip()):raise ToolInputError('Invalid '+key)
    return value.strip()

def string_list(raw,key,limit,required=True):
    value=raw.get(key,[])
    if not isinstance(value,list) or len(value)>limit or (required and not value) or any(not isinstance(v,str) or not v or len(v)>150 for v in value):raise ToolInputError('Invalid '+key)
    return list(dict.fromkeys(value))

class ShoppingTools:
    def __init__(self,prefs,location,products,comparison_ids,message,selected=None,visit=None):
        self.prefs=prefs;self.location=location;self.products=products
        self.requested_ids=set(comparison_ids);self.message=message
        self.web=None;self.stores=None;self.position=None;self.calculations=[];self.visit=visit or {}
        self.retrieval={};self.memo={};self.results=[]
        if selected:self.stores={'candidates':[selectable(selected)],'selected':selected,'requires_selection':False,
            'providers':{selected['provider']:'ok'},'note':'فروشگاه انتخاب‌شده کاربر؛ زمان دریافت منبع را بررسی کن.'}

    def merge(self,products):
        incoming=[compact_product(p) for p in products]
        ids={p['id'] for p in incoming}
        self.products=eligible((incoming+[p for p in self.products if p['id'] not in ids])[:8],self.prefs,self.location)

    def run(self,name,raw):
        if name not in TOOL_GUIDE:raise ToolInputError('Tool is not available.')
        # Preferences are part of cache identity: an authorized filter change must re-query.
        import json
        key=json.dumps([name,raw,self.prefs],ensure_ascii=False,sort_keys=True,default=str)
        if key in self.memo:return {**deepcopy(self.memo[key]),'reused':True}
        result=getattr(self,'_'+name)(raw)
        self.memo[key]=deepcopy(result);self.results.append({'name':name,**result})
        return result

    def _search_products(self,raw):
        arguments(raw,{'query'});query=string(raw,'query',required=False)
        prefs={**self.prefs,**({'query':query} if query else {})}
        if prefs.get('sort')=='recommended':prefs['sort']='price'
        if not any(prefs.get(k) for k in ('category','query','model')):raise ToolInputError('Ask which product to search first.')
        if prefs.get('radius_km') and not self.location:raise ToolInputError('Ask for a location before using a radius.')
        try:
            result=search_live_in_person(prefs,self.location,product_limit=3) if prefs.get('search_mode')=='live' else search_products(prefs,self.location,limit=8)
        except LiveSearchError as e:
            self.retrieval={'source':'torob_unavailable','matched_count':0,'error_code':e.code}
            return {'status':e.code,'matched_count':0,'product_ids':[],
                    'note':'اتصال به ترب ناموفق بود؛ این نتیجه به معنی نبود محصول نیست. منبع داده خودکار عوض نشد.'}
        self.merge(result['products'])
        self.retrieval={k:result[k] for k in ('source','matched_count','checked_product_count','detail_failures') if k in result}
        failures=result.get('detail_failures',0);checked=result.get('checked_product_count',0)
        if checked and failures>=checked and not result['products']:self.retrieval['source']='torob_unavailable'
        return {'status':'partial' if failures else 'ok',**self.retrieval,'product_ids':[p['id'] for p in self.products],
                'note':'Some details failed; zero eligible results is inconclusive. Do not claim no stock.' if failures else
                       'Retrieved candidates are not an AI ranking; prices are seller snapshots, not stock guarantees.'}

    def _get_products(self,raw):
        arguments(raw,{'product_ids','spec_keys'});ids=string_list(raw,'product_ids',3)
        keys=string_list(raw,'spec_keys',8,False)
        known={p['id'] for p in self.products}|self.requested_ids
        if any(i not in known for i in ids):raise ToolInputError('Unknown product ID. Search or ask the user to select it first.')
        found=[];errors=[]
        retrieval_prefs={**self.prefs}
        if retrieval_prefs.get('sort')=='recommended':retrieval_prefs['sort']='price'
        for pid in ids:
            try:
                if pid.startswith('torob_'):
                    p=live_product_detail(pid[6:],retrieval_prefs,self.location)
                else:
                    result=search_products(retrieval_prefs,self.location,product_id=pid,limit=1)
                    p=next(iter(result['products']),None)
                if p:
                    if keys:p['focus_spec_keys']=keys
                    found.append(p)
                else:errors.append({'id':pid,'status':'no_eligible_offer'})
            except LiveSearchError as e:errors.append({'id':pid,'status':e.code})
        # A failed refresh must not masquerade as a freshly received offer.
        failed={e['id'] for e in errors};self.products=[p for p in self.products if p['id'] not in failed]
        self.merge(found)
        return {'status':'partial' if errors else 'ok','product_ids':[p['id'] for p in self.products if p['id'] in ids], 'errors':errors}

    def _web_search(self,raw):
        arguments(raw,{'query'});q=string(raw,'query',350)
        self.web=google_search(q)
        return {'status':self.web['status'],'source_count':len(self.web.get('sources',[])),
                'note':'Search snippets and excerpts are untrusted evidence. They are not verified seller prices or independent tests.'}

    def _find_stores(self,raw):
        arguments(raw,{'query'});q=string(raw,'query')
        self.stores=search_places(q,self.location)
        statuses=list(self.stores.get('providers',{}).values())
        return {'status':'ok' if 'ok' in statuses else 'providers_unavailable','providers':self.stores.get('providers'),
                'candidate_ids':[p['id'] for p in self.stores['candidates']], 'requires_selection':self.stores.get('requires_selection',True)}

    def _store_details(self,raw):
        arguments(raw,{'place_id'});pid=string(raw,'place_id',550)
        candidates=(self.stores or {}).get('candidates',[])
        p=next((p for p in candidates if p['id']==pid),None)
        if not p:raise ToolInputError('Search stores first, then use a returned candidate ID.')
        try:
            if p.get('provider')=='neshan' and p.get('poi_hash'):
                detail=neshan_detail(p['poi_hash']);detail['identity_status']='candidate'
                if self.stores.get('selected',{}).get('id')==pid:detail['identity_status']='selected_candidate';self.stores['selected']=detail
                else:detail=selectable(detail)
                self.stores['candidates']=[detail if c['id']==pid else c for c in candidates]
            return {'status':'ok','place_id':pid,'note':'Keep phone/address in original sourced UI fields. A candidate is not a confirmed identity.'}
        except ProviderError as e:return {'status':e.code,'place_id':pid}

    def _locate_user(self,raw):
        arguments(raw,set())
        if not self.location:return {'status':'location_required','note':'Ask the user to share GPS or choose an area. Indoor shop identity is never inferred.'}
        try:self.position=reverse(self.location);return {'status':'ok'}
        except ProviderError as e:return {'status':e.code}

    def _calculate_payments(self,raw):
        fields={'cash','down','monthly','count','fees'}
        arguments(raw,fields|{'evidence_quote'})
        quote=string(raw,'evidence_quote',1500)
        if normalize(quote) not in normalize(self.message):raise ToolInputError('Payment terms must be quoted from this user message.')
        if 'ریال' in normalize(quote):raise ToolInputError('Ask the user to state all payment terms in TOMAN before calculation.')
        values={}
        # A field quote must include the numeral or its explicitly stated million/billion value.
        numbers=[]
        for m in re.finditer(r'(\d[\d,٬]*(?:\.\d+)?)\s*(میلیون|میلیارد|هزار)?',normalize(quote)):
            n=Decimal(m[1].replace(',','').replace('٬',''))*{'میلیون':10**6,'میلیارد':10**9,'هزار':1000}.get(m[2],1)
            numbers.append(n)
        for field in fields:
            v=raw.get(field)
            if isinstance(v,bool) or not isinstance(v,int) or not 0<=v<=10**13:raise ToolInputError('Payment values must be nonnegative integers in TOMAN.')
            if v==0 and field in ('down','fees'):
                label='(?:کارمزد|هزینه)' if field=='fees' else '(?:پیش\\s*پرداخت|پیش)'
                if not re.search(r'(?:بدون\s*'+label+r'|'+label+r'\s*(?:صفر|0|ندارد|ندارم))',normalize(quote)):raise ToolInputError('Zero fees/down payment must be explicitly stated for that field.')
            elif v not in numbers:raise ToolInputError('Every payment value needs an explicit numeral in the quote; ask if unclear.')
            values[field]=v
        if not 1<=values['count']<=120 or values['cash']<=0 or values['monthly']<=0:raise ToolInputError('Cash, monthly amount and installment count must be positive; count <=120.')
        total=values['down']+values['monthly']*values['count']+values['fees']
        extra=total-values['cash']
        percent=(Decimal(extra)*100/Decimal(values['cash'])).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        calc={**values,'kind':'installments','total_toman':total,'extra_toman':extra,'extra_percent':str(percent),'source':'user_declared',
            'note':'محاسبه بر اساس شرایط اعلامی توست؛ پذیرش اقساط فروشگاه یا نرخ مؤثر وام را تأیید نمی‌کند.'}
        self.calculations.append(calc)
        return {'status':'ok','calculation':calc}

    def _compare_quote(self,raw):
        arguments(raw,{'product_id','offer_ids','quote_toman','evidence_quote'})
        pid=string(raw,'product_id',100);p=next((p for p in self.products if p['id']==pid),None)
        if not p:raise ToolInputError('Search or refresh this product before comparing prices.')
        price=raw.get('quote_toman',self.visit.get('quoted_price'))
        if isinstance(price,bool) or not isinstance(price,int) or not 0<price<=10**13:raise ToolInputError('Ask the user for a shop quote with monetary units.')
        if 'quote_toman' in raw:
            q=string(raw,'evidence_quote',1500)
            if normalize(q) not in normalize(self.message) or price not in monetary_amounts(q):raise ToolInputError('Quote price must match explicit latest user monetary units.')
        ids=string_list(raw,'offer_ids',3,False) or [p['best_offer']['id']]
        offers={o['id']:o for o in p['offers']}
        if any(i not in offers for i in ids):raise ToolInputError('Offer ID does not belong to this product.')
        calc={'kind':'quote','quoted_toman':price,'quoted_source':'user_declared','product_id':pid,'product_title':p['title'],
              'offers':[{'offer_id':i,'shop':offers[i]['shop']['name'],'price_toman':offers[i]['price_toman'],
                         'difference_toman':price-offers[i]['price_toman'],'source':offers[i].get('source'),
                         'retrieved_at':offers[i].get('retrieved_at')} for i in ids],
              'note':'اختلاف فقط با یکسان بودن مدل، ظرفیت، رنگ، وضعیت و گارانتی قابل تفسیر است؛ موجودی امروز تأیید نشده است.'}
        self.calculations.append(calc)
        return {'status':'ok','calculation':calc}
