"""Read public search-result pages without executing scripts or bypassing access blocks."""
import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin
from urllib.robotparser import RobotFileParser
import requests
from django.core.cache import cache
from .common import safe_url,normalize
from .request_budget import http_timeout,check,BudgetExceeded

AGENT='TorobYarResearch/2.0'
class PageUnavailable(Exception):pass

def public_url(url):
    if not safe_url(url):return False
    try:
        p=urlsplit(url)
        if p.port not in (None,443) or p.hostname.lower().endswith(('.localhost','.local','.internal')):return False
        addresses=socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(x[4][0]).is_global for x in addresses)
    except (ValueError,OSError):return False

def public_text(url,limit=800000):
    for _ in range(3):
        if not public_url(url):raise PageUnavailable()
        try:
            with requests.get(url,headers={'User-Agent':AGENT,'Accept':'text/html,text/plain'},timeout=http_timeout(3,6),allow_redirects=False,stream=True) as r:
                if r.status_code in (301,302,303,307,308):url=urljoin(url,r.headers.get('Location',''));continue
                if r.status_code!=200:raise PageUnavailable()
                kind=r.headers.get('Content-Type','').lower()
                if 'text/' not in kind and 'application/xhtml' not in kind:raise PageUnavailable()
                chunks=[];size=0
                for chunk in r.iter_content(16384):
                    check()
                    size+=len(chunk)
                    if size>limit:raise PageUnavailable()
                    chunks.append(chunk)
                return b''.join(chunks).decode('utf-8',errors='replace'),url
        except (requests.RequestException,BudgetExceeded):raise PageUnavailable() from None
    raise PageUnavailable()

def may_read(url):
    p=urlsplit(url);robots_url=p.scheme+'://'+p.netloc+'/robots.txt';key='robots:'+robots_url
    text=cache.get(key)
    if text is None:
        try:text,_=public_text(robots_url,100000)
        except PageUnavailable:return False
        cache.set(key,text,3600)
    parser=RobotFileParser();parser.parse(text.splitlines())
    return parser.can_fetch(AGENT,url)

class PageParser(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.skip=0;self.jsonld=False;self.current=[];self.documents=[];self.text=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ('script','style','noscript','nav','footer'):self.skip+=1
        if tag=='script' and attrs.get('type','').lower()=='application/ld+json':self.jsonld=True;self.current=[]
    def handle_endtag(self,tag):
        if tag=='script' and self.jsonld:
            try:self.documents.append(json.loads(''.join(self.current)))
            except (ValueError,TypeError):pass
            self.jsonld=False
        if tag in ('script','style','noscript','nav','footer'):self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if self.jsonld:self.current.append(data)
        elif not self.skip and data.strip():self.text.append(' '.join(data.split()))

def extract_page(html,query):
    parser=PageParser();parser.feed(html)
    tokens=[x for x in normalize(query).split() if len(x)>2]
    ranked=[(sum(t in normalize(line) for t in tokens),i,line) for i,line in enumerate(parser.text) if len(line)>25]
    chosen=sorted(sorted(ranked,key=lambda x:(-x[0],x[1]))[:12],key=lambda x:x[1])
    excerpt='\n'.join(x[2] for x in chosen)[:4500]
    facts=[]
    def visit(value,depth=0):
        if depth>6:return
        if isinstance(value,list):
            for x in value[:20]:visit(x,depth+1)
        elif isinstance(value,dict):
            kind=value.get('@type');kinds=kind if isinstance(kind,list) else [kind]
            if any(k in ('Product','LocalBusiness','Store','ElectronicsStore','ShoppingCenter','ShoeStore') for k in kinds):
                facts.append({k:value[k] for k in ('@type','name','telephone','address','openingHours','model','brand','color','sku') if k in value})
            if '@graph' in value:visit(value['@graph'],depth+1)
    for value in parser.documents[:10]:visit(value)
    return {'page_excerpt':excerpt,'structured_facts':facts[:8],'evidence_type':'public_page_excerpt'}

def read_result(source,query):
    try:
        if not may_read(source['url']):return {**source,'page_status':'not_permitted_or_unavailable'}
        html,final=public_text(source['url'])
        return {**source,**extract_page(html,query),'resolved_url':final,'page_status':'ok'}
    except (PageUnavailable,ValueError,TypeError):return {**source,'page_status':'unavailable'}
