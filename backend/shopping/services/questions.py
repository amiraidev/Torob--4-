"""Clarification choices grounded in the prices actually retrieved."""
def clarifications(prefs,result):
    questions=[]
    market=result.get('market') or {}
    prices=sorted(set(p.get('price_toman') for p in market.get('products',[]) if isinstance(p.get('price_toman'),(int,float)) and p['price_toman']>0))
    dataset_prices=False
    if not prices and result.get('source')=='uploaded_dataset':
        prices=sorted(set(p['best_offer']['price_toman'] for p in result.get('products',[]) if p.get('best_offer',{}).get('price_toman')))
        dataset_prices=True
    if not prefs.get('budget_max') and not prefs.get('budget_any'):
        if prices:
            choices=['تا '+f'{int(prices[min(len(prices)-1,int((len(prices)-1)*q))]):,}'+' تومان' for q in (.25,.6,1)]
            choices=list(dict.fromkeys(choices))+['محدودیت بودجه ندارم']
            text=f'قیمت‌های {"ثبت‌شده در فایل" if dataset_prices else "دریافت‌شده"} برای نتایج بررسی‌شده از {int(prices[0]):,} تا {int(prices[-1]):,} تومان است؛ سقف بودجه‌ات چقدر است؟'
        else:
            choices=['محدودیت بودجه ندارم'];text='سقف بودجه‌ات چند تومان است؟ هنوز بازه قیمت قابل اتکایی برای این جستجو دریافت نشده است.'
        questions.append({'key':'budget','text':text,'choices':choices,'basis':'retrieved_prices' if prices else 'missing_evidence'})
    if not prefs.get('color') and not prefs.get('color_any'):
        questions.append({'key':'color','text':'چه رنگی می‌خواهی یا رنگ برایت مهم نیست؟','choices':['مشکی','سفید','رنگ مهم نیست']})
    if not prefs.get('model') and not prefs.get('query') and not prefs.get('product_type') and not prefs.get('product_type_any'):
        choices={'هدفون، هدست و هندزفری':['بی سیم','باسیم','روگوشی'],
            'لپ تاپ و نوت بوک':['گیمینگ','سبک و قابل حمل']}.get(prefs.get('category'),[])
        questions.append({'key':'product_type','text':'نوع یا مدل مشخصی مدنظرت هست؟ می‌توانم بر اساس کاربردت پیشنهاد بدهم.',
            'choices':choices+['بر اساس کاربرد پیشنهاد بده']})
    if not prefs.get('needs'):
        choices={'گوشی موبایل':['کار روزمره','عکاسی و باتری','بازی'],
            'لپ تاپ و نوت بوک':['برنامه نویسی','بازی','کار روزمره'],
            'قهوه و اسپرسو ساز':['مصرف خانگی','مصرف کافه']}.get(prefs.get('category'),['کار روزمره','کیفیت بیشتر'])
        questions.append({'key':'needs','text':'بیشتر برای چه کاری می‌خواهی از محصول استفاده کنی؟','choices':choices})
    if not prefs.get('brand') and not prefs.get('brand_any') and not prefs.get('model'):
        choices=['سامسونگ','شیائومی','اپل'] if prefs.get('category')=='گوشی موبایل' else []
        questions.append({'key':'brand','text':'برند خاصی مدنظرت هست یا مقایسه را بین برندها انجام بدهم؟','choices':choices+['برند مهم نیست']})
    return questions
