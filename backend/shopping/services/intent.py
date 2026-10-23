import re
from .common import normalize

CATEGORIES = {
    'گوشی موبایل':['گوشی','موبایل','phone','iphone','آیفون'],
    'لپ تاپ و نوت بوک':['لپ تاپ','لپتاپ','نوت بوک','laptop','macbook','مک بوک'],
    'هدفون، هدست و هندزفری':['هدفون','هندزفری','هدست','ایرپاد','headphone','airpod'],
    'ساعت و مچ بند هوشمند':['ساعت هوشمند','ساعت اسمارت','smartwatch'],
    'مانیتور':['مانیتور','monitor'],
    'جارو برقی':['جاروبرقی','جارو برقی'],
    'قهوه و اسپرسو ساز':['اسپرسو','قهوه ساز','قهوه ساز'],
    'تلویزیون':['تلویزیون','tv'],
    'دوربین مدار بسته':['دوربین مداربسته','دوربین مدار بسته'],
    'کارت گرافیک':['کارت گرافیک','gpu','graphics card'],
    'کفش':['کفش','کتانی','کتونی','کفش ورزشی'],
    'پوشاک':['لباس','پیراهن','شلوار','مانتو','پالتو'],
}
BRANDS = {'سامسونگ':['سامسونگ','samsung'],'اپل':['اپل','apple','آیفون','iphone','مک بوک','macbook'],'شیائومی':['شیائومی','xiaomi','ردمی','redmi'],
    'سونی':['سونی','sony'],'ایسوس':['ایسوس','asus'],'لنوو':['لنوو','lenovo'],'دلونگی':['دلونگی','delonghi'],'انکر':['انکر','anker'],'جی بی ال':['جی بی ال','jbl']}
COLORS=['مشکی','سفید','آبی','نقره ای','خاکستری','طلایی','صورتی','سبز','بنفش','قرمز']
def mentions(text,alias):
    return bool(re.search(r'(?<!\w)'+re.escape(normalize(alias))+r'(?!\w)',text))
def infer(message,previous=None):
    prefs=dict(previous or {})
    s=normalize(message)
    if not s:return prefs
    changed=next((category for category,aliases in CATEGORIES.items() if any(mentions(s,a) for a in aliases)),None)
    if changed and prefs.get('category') and changed!=prefs['category']:
        for key in ('query','model','product_type','brand','color','needs','size'):prefs[key]=''
        prefs.update(condition='any',brand_any=False,color_any=False,task='shopping',store_query='')
    if changed:prefs['task']='shopping'
    if re.search(r'شماره(?: تماس| تلفن)?|آدرس|ادرس|وارد|الان|اینجا|تو[ی ]',s) and re.search(r'فروشگاه|مغازه|پاساژ|مرکز خرید',s) and not changed:
        prefs['task']='store'
        if not prefs.get('store_query') or re.search(r'(?:فروشگاه|مغازه|پاساژ)\s+\S+',s):
            q=re.sub(r'شماره(?: تماس| تلفن)?|آدرس|ادرس|رو بده|را بده|پیدا کن|بهم بگو|الان|هستم|داخل|وارد شدم',' ',s)
            prefs['store_query']=' '.join(q.split())[:250]
    if 'مقایسه مدل' in s or 'پیشنهاد بده' in s:prefs['needs']='مقایسه مدل‌ها بر اساس بودجه'
    if re.search(r'کار\s*کرده|دست\s*دوم|استوک|\bused\b',s):prefs['condition']='used'
    if re.search(r'\bنو\b|آکبند|اکبند|پلمپ',s):prefs['condition']='new'
    if 'نو یا کارکرده مهم نیست' in s or 'وضعیت مهم نیست' in s:prefs['condition']='any'
    size=re.search(r'(?:سایز|اندازه)\s*([\w.-]+)',s)
    if size:prefs['size']=size.group(1)[:80]
    needs=[x for x in ['عکاسی','دوربین','باتری','بازی','برنامه نویسی','موسیقی','کیفیت صدا','کار روزمره','سبک'] if x in s]
    if needs:prefs['needs']='، '.join(dict.fromkeys([*(prefs.get('needs','').split('، ') if prefs.get('needs') else []),*needs]))[:350]
    if any(x in s for x in ['برند مهم نیست','فرقی نداره چه برندی','بدون محدودیت برند']):prefs['brand']='';prefs['brand_any']=True
    else:
        for brand,aliases in BRANDS.items():
            if any(mentions(s,a) for a in aliases):prefs['brand']=brand;prefs['brand_any']=False;break
    if any(x in s for x in ['رنگ مهم نیست','هر رنگ','بدون محدودیت رنگ']):prefs['color']='';prefs['color_any']=True
    else:
        for color in COLORS:
            if normalize(color) in s:prefs['color']=color;prefs['color_any']=False;break
    # Monetary quantities require a unit or budget context; 256 GB is never a budget.
    sums=[]
    for match in re.finditer(r'(\d[\d,٬]*(?:\.\d+)?)\s*(میلیون|میلیارد|هزار|تومن|تومان|ریال)(?:\s*(تومان|تومن|ریال))?',s):
        n=float(match.group(1).replace(',','').replace('٬',''))
        amount=n*{'میلیون':10**6,'میلیارد':10**9,'هزار':1000}.get(match.group(2),1)
        if match.group(2)=='ریال' or match.group(3)=='ریال':amount/=10
        sums.append(int(amount))
    if sums:
        prefs['budget_any']=False
        if len(sums)>1 and ('بین' in s or 'از ' in s):prefs['budget_min'],prefs['budget_max']=min(sums),max(sums)
        else:prefs['budget_max']=sums[-1]
    shared_range=re.search(r'(?:(?:بین|از)\s*)?(\d+(?:\.\d+)?)\s*(?:تا|و|الی)\s*(\d+(?:\.\d+)?)\s*(میلیون|میلیارد|هزار)(?:\s*(تومان|تومن|ریال))?',s)
    if shared_range:
        multiplier={'میلیون':10**6,'میلیارد':10**9,'هزار':1000}[shared_range.group(3)]
        if shared_range.group(4)=='ریال':multiplier/=10
        prefs['budget_min'],prefs['budget_max']=sorted(int(float(shared_range.group(i))*multiplier) for i in (1,2))
        prefs['budget_any']=False
    if any(x in s for x in ['محدودیت بودجه ندارم','بدون محدودیت بودجه','بودجه مهم نیست']):prefs['budget_max']=None;prefs['budget_min']=0;prefs['budget_any']=True
    if 'فقط باز' in s or 'الان باز' in s or 'فروشگاه باز' in s:prefs['only_open']=True
    if 'بسته هم' in s or 'همه فروشگاه' in s:prefs['only_open']=False
    if re.search(r'قسط|اقساط|اقضاط',s):prefs['installment']=not any(x in s for x in ['قسطی نمی','بدون قسط','نقدی میخوام','اقساط نمی'])
    if 'ترب پی' in s:prefs['torobpay']=True
    if 'ارسال فوری' in s:prefs['fast_delivery']=True
    if 'نزدیک ترین' in s or 'نزدیکتر' in s or 'نزدیک تر' in s:prefs['sort']='distance'
    if 'ارزان ترین' in s or 'ارزون' in s or 'کمترین قیمت' in s:prefs['sort']='price'
    for category,aliases in CATEGORIES.items():
        if any(mentions(s,a) for a in aliases):
            if prefs.get('category') and prefs['category']!=category:
                prefs['query']='';prefs['brand']=next((b for b,aa in BRANDS.items() if any(mentions(s,a) for a in aa)),'')
            prefs['category']=category;break
    models=re.findall(r'(?<![a-z0-9])(?:[as]\d{2}(?:\s*(?:fe|ultra))?|iphone\s*\d{1,2}(?:\s*pro(?:\s*max)?)?|wh[ -]?1000xm\d|ps[45])\b',s,re.I)
    if models:prefs['query']=' '.join(models)
    elif any(mentions(s,a) for aliases in CATEGORIES.values() for a in aliases):
        latin=re.findall(r'[a-z][a-z0-9-]*|\d+(?:\.\d+)?',s)
        brand_words={normalize(a) for aliases in BRANDS.values() for a in aliases if a.isascii()}
        latin=[t for t in latin if t not in brand_words and t not in {'phone','laptop','headphone','monitor','tv','gb','ram','tb'}]
        # Only keep a model-like phrase; numeric budgets/storage alone are not model names.
        if any(re.search('[a-z]',t) for t in latin):
            cutoff=re.split(r'تا\s*\d|بین\s*\d|برای|بودجه',s,maxsplit=1)[0]
            prefs['query']=' '.join(t for t in latin if t in cutoff)[:200]
    elif not prefs.get('category') and not sums and len(s)>2:
        clean=re.sub(r'\b(میخوام|می خوام|می خواهم|میخام|برای|بخرم|خرید|یک|یه|لطفا|مناسب|بهم|پیشنهاد|بده|دارم|نیاز)\b',' ',s)
        clean=' '.join(x for x in clean.split() if x not in COLORS)[:200].strip()
        if clean:prefs['query']=clean
    return prefs
