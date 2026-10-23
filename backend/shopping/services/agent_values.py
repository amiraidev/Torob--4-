"""Validate model-extracted monetary values against explicitly stated user units."""
from decimal import Decimal
import re
from .common import normalize

def monetary_amounts(value):
    q=normalize(value);amounts=[]
    for m in re.finditer(r'(\d[\d,٬]*(?:\.\d+)?)\s*(میلیون|میلیارد|هزار|تومن|تومان|ریال)(?:\s*(تومان|تومن|ریال))?',q):
        n=Decimal(m[1].replace(',','').replace('٬',''))*{'میلیون':10**6,'میلیارد':10**9,'هزار':1000}.get(m[2],1)
        amounts.append(n/10 if m[2]=='ریال' or m[3]=='ریال' else n)
    shared=re.search(r'(\d+(?:\.\d+)?)\s*(?:تا|و|الی)\s*(\d+(?:\.\d+)?)\s*(میلیون|میلیارد|هزار)(?:\s*(تومان|تومن|ریال))?',q)
    if shared:
        factor=Decimal({'میلیون':10**6,'میلیارد':10**9,'هزار':1000}[shared[3]])/(10 if shared[4]=='ریال' else 1)
        amounts.extend([Decimal(shared[1])*factor,Decimal(shared[2])*factor])
    return amounts
