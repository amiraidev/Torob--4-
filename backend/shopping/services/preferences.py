"""Shared hard filters for agent and market cards. Unknown is never a match."""
import re
from .common import normalize
from .intent import BRANDS, mentions

def product_matches(title, english, prefs):
    text=normalize(str(title)+' '+str(english))
    if prefs.get('brand'):
        aliases=[prefs['brand'],*BRANDS.get(prefs['brand'],[])]
        if not any(mentions(text,a) for a in aliases): return False
    for value in (prefs.get('query'),prefs.get('model'),prefs.get('product_type')):
        for token in re.findall(r'[^\W_]+',normalize(value),re.UNICODE)[:12]:
            if not mentions(text,token): return False
    if prefs.get('category')=='گوشی موبایل' and re.match(r'^(قاب|کاور|گلس|شارژر|باتری|کیف|کابل)\b',text):return False
    return True

def variant_matches(text,prefs,base_title=''):
    text=normalize(text)
    if prefs.get('color') and not mentions(text,prefs['color']):return False
    if prefs.get('size') and not mentions(text,prefs['size']):return False
    condition_text=text+' '+normalize(base_title)
    used=bool(re.search(r'کار\s*کرده|دست\s*دوم|استوک|used|refurbished',condition_text))
    new=bool(re.search(r'\bنو\b|آکبند|اکبند|پلمپ|\bnew\b',condition_text))
    if prefs.get('condition')=='used' and not used:return False
    if prefs.get('condition')=='new' and (used or not new):return False
    return True

def missing_questions(prefs,location=None):
    if not prefs.get('category') and not prefs.get('query') and not prefs.get('model'):
        return [{'key':'product','text':'چه محصولی می‌خواهی بخری؟','choices':['گوشی موبایل','لپ تاپ','هدفون','کفش']}]
    questions=[]
    if not prefs.get('budget_max') and not prefs.get('budget_any'):
        questions.append({'key':'budget','text':'بازه یا سقف بودجه‌ات چند تومان است؟','choices':['فعلاً محدودیت بودجه ندارم']})
    if not any(prefs.get(k) for k in ('query','model','product_type','needs')):
        kind=prefs.get('category') or 'این محصول'
        choices=['برای کار و برنامه نویسی','برای بازی','کار روزمره'] if 'لپ' in kind else ['مقایسه مدل‌های مختلف','کار روزمره']
        questions.append({'key':'type','text':f'برای {kind}، مدل یا نوع خاصی می‌خواهی یا بر اساس کاربردت پیشنهاد بدهم؟','choices':choices})
    if not prefs.get('color') and not prefs.get('color_any'):
        questions.append({'key':'color','text':'رنگ خاصی مدنظرت هست؟ اگر مهم نیست همان را بگو.','choices':['مشکی','سفید','رنگ مهم نیست']})
    return questions[:2]
