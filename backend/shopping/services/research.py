"""Product research is evidence selection, never an invented product review."""
from .common import normalize

NEED_KEYS = {
 'عکاسی': ['دوربین','عکاسی','فیلم','لرزش','camera','ois'],
 'دوربین': ['دوربین','عکاسی','فیلم','لرزش','camera','ois'],
 'باتری': ['باتری','شارژ','battery','charge'],
 'بازی': ['تراشه','پردازنده','گرافیک','رم','نرخ','تاخیر','chip','gpu','refresh'],
 'برنامه نویسی': ['پردازنده','رم','حافظه','صفحه','وزن','cpu','ram'],
 'موسیقی': ['صدا','درایور','نویز','بلوتوث','باتری','audio','anc'],
 'کیفیت صدا': ['صدا','درایور','نویز','audio','anc'],
 'سبک': ['وزن','ابعاد','weight'],
 'کار روزمره': ['باتری','وزن','حافظه','پردازنده','شارژ'],
 'گیمینگ': ['تراشه','پردازنده','گرافیک','رم','نرخ','تاخیر','chip','gpu','refresh'],
 'تدوین': ['پردازنده','گرافیک','رم','حافظه','صفحه','cpu','gpu','ram'],
 'حمل': ['وزن','ابعاد','باتری','weight'],
 'وزن': ['وزن','ابعاد','weight'],
 'نویز': ['نویز','صدا','میکروفون','anc','noise'],
 'حافظه': ['رم','حافظه','ram','storage','ssd'],
 'اسپرسو': ['فشار','توان','بخار','مخزن','پمپ','bar','power'],
 'قهوه': ['فشار','توان','بخار','مخزن','پمپ','bar','power'],
}

def attach_research(products, prefs):
    requested = normalize(prefs.get('needs',''))
    for product in products:
        specs = [s for s in product.get('specs',[]) if isinstance(s,dict) and s.get('key') and s.get('value')]
        groups=[];seen=set();selected=[]
        for need, keys in NEED_KEYS.items():
            if normalize(need) not in requested: continue
            evidence=[s for s in specs if any(normalize(k) in normalize(s['key']) for k in keys)]
            groups.append({'need':need,'specs':evidence[:8],'status':'recorded_specs' if evidence else 'unknown'})
            for item in evidence:
                if item['key'] not in seen: selected.append(item);seen.add(item['key'])
        if not groups: selected=specs[:10]
        product['research']={'basis':'registered_specifications','needs':groups,'relevant_specs':selected[:36],
            'note':'این بررسی از مشخصات ثبت‌شده است؛ آزمون عملی، نقد مستقل و تضمین کیفیت محصول نیست.'}
    return products
