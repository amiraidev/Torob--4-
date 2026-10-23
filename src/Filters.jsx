import React,{useState} from 'react';
import {normalize} from './engine.mjs';
function TextFilter({label,name,value,onChange,placeholder=''}){
  return <label>{label}<input aria-label={label} key={name+value} defaultValue={value||''} placeholder={placeholder} onBlur={e=>{const v=e.target.value.trim();if(v!==(value||''))onChange(name,v);}} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();e.target.blur();}}}/></label>;
}
export default function Filters({prefs,location,onChange,disabled=false}){
  const [error,setError]=useState('');
  function price(key,value){
    const clean=normalize(value).replace(/[,٬\s]/g,'');const n=clean?Number(clean):key==='budget_min'?0:null;
    if(n!==null&&(!Number.isSafeInteger(n)||n<0||n>1e13||key==='budget_max'&&n===0)){setError('قیمت را به تومان و با عدد معتبر وارد کن.');return;}
    if((key==='budget_min'&&prefs.budget_max&&n>prefs.budget_max)||(key==='budget_max'&&n&&n<(prefs.budget_min||0))){setError('حداقل قیمت نباید از حداکثر بیشتر باشد.');return;}
    setError('');if(n!==prefs[key])onChange(key,n);
  }
  return <fieldset className="filter-panel unified-filters" disabled={disabled}><legend>شرایط جستجو در چت و ترب</legend>
    <label>منبع خرید حضوری<select value={prefs.search_mode||'live'} onChange={e=>onChange('search_mode',e.target.value)}><option value="live">جستجوی زنده ترب</option><option value="dataset">فایل داده ثبت‌شده</option></select></label>
    <TextFilter label="دسته محصول" name="category" value={prefs.category} onChange={onChange} placeholder="مثلاً گوشی موبایل"/>
    <TextFilter label="مدل دقیق" name="model" value={prefs.model||prefs.query} onChange={onChange} placeholder="مثلاً A55 یا LOQ 15IRH8"/>
    <TextFilter label="نوع محصول" name="product_type" value={prefs.product_type} onChange={onChange} placeholder="مثلاً بی سیم یا گیمینگ"/>
    <TextFilter label="برند" name="brand" value={prefs.brand} onChange={onChange}/>
    <TextFilter label="رنگ" name="color" value={prefs.color} onChange={onChange}/>
    <TextFilter label="سایز / اندازه" name="size" value={prefs.size} onChange={onChange}/>
    <label>وضعیت کالا<select value={prefs.condition||'any'} onChange={e=>onChange('condition',e.target.value)}><option value="any">همه وضعیت‌ها</option><option value="new">نو / آکبندِ اعلام‌شده</option><option value="used">کارکرده / استوکِ اعلام‌شده</option></select></label>
    {[['budget_min','حداقل قیمت (تومان)'],['budget_max','حداکثر قیمت (تومان)']].map(([key,label])=><label key={key}>{label}<input aria-label={label} inputMode="numeric" key={key+prefs[key]} defaultValue={prefs[key]||''} onBlur={e=>price(key,e.target.value)} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();e.target.blur();}}} placeholder="بدون محدودیت"/></label>)}
    <label>شعاع فاصله<select value={prefs.radius_km||''} disabled={!location} onChange={e=>onChange('radius_km',e.target.value?Number(e.target.value):null)}><option value="">بدون محدودیت</option>{[1,3,5,10,20].map(n=><option value={n} key={n}>{n} کیلومتر</option>)}</select></label>
    <label>زمان مراجعه (تهران)<input aria-label="زمان مراجعه" type="datetime-local" defaultValue={prefs.visit_at?.slice(0,16)||''} key={prefs.visit_at} onBlur={e=>{const v=e.target.value||null;if(v!==prefs.visit_at)onChange('visit_at',v);}}/></label>
    <div className="filter-checks">{[['only_open','باز طبق ساعت ثبت‌شده'],['installment','اقساط حضوری اعلام‌شده'],['torobpay','ترب‌پی حضوری'],['fast_delivery','ارسال فوری اعلام‌شده']].map(([key,label])=><label key={key}><input type="checkbox" checked={!!prefs[key]} onChange={e=>onChange(key,e.target.checked)}/>{label}</label>)}</div>
    <small className="filter-explainer">قیمت‌ها به تومان‌اند. اقساط فقط با پذیرش حضوری ثبت‌شده تأیید می‌شود؛ نبود اطلاعات، به معنی نداشتن اقساط نیست.</small>
    {error&&<p role="alert" className="form-error">{error}</p>}
  </fieldset>;
}
