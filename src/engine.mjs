// This snapshot engine makes the published UI useful without a Python host.
// The full application uses Django's validated API and the complete dataset.
const digits='۰۱۲۳۴۵۶۷۸۹';
export const fa=n=>n===null||n===undefined?'—':new Intl.NumberFormat('fa-IR',{maximumFractionDigits:1}).format(n);
export const money=n=>n===null||n===undefined?'قیمت ثبت نشده':fa(n);
export function displayValue(value){
  if(value===null||value===undefined||value==='')return 'ثبت نشده';
  if(Array.isArray(value))return value.map(displayValue).join('، ');
  if(typeof value==='object'){
    if('provider' in value||'period_months' in value)return [value.provider,value.period_months!=null?fa(value.period_months)+' ماه':null,value.description].filter(Boolean).join(' · ')||'ثبت نشده';
    return Object.values(value).filter(x=>x!=null).map(displayValue).join('، ')||'ثبت نشده';
  }
  return String(value).replace(/(?:\s*,\s*){2,}/g,'، ').replace(/^[\s،,]+|[\s،,]+$/g,'');
}
export const normalize=s=>String(s??'').replace(/[۰-۹]/g,c=>digits.indexOf(c)).replace(/[٠-٩]/g,c=>'٠١٢٣٤٥٦٧٨٩'.indexOf(c)).replace(/ي/g,'ی').replace(/ك/g,'ک').replace(/\u200c/g,' ').toLowerCase().replace(/\s+/g,' ').trim();
export const DEFAULT_PREFS={task:'shopping',store_query:'',model:'',product_type:'',condition:'any',size:'',query:'',category:'',brand:'',color:'',needs:'',visit_at:null,search_mode:'live',budget_max:null,budget_min:0,brand_any:false,color_any:false,budget_any:false,only_open:false,installment:false,torobpay:false,fast_delivery:false,radius_km:null,sort:'recommended'};
export const NEIGHBORHOODS=[
  {label:'صادقیه',lat:35.7215,lon:51.3355},{label:'میدان ولیعصر',lat:35.7114,lon:51.4070},
  {label:'انقلاب',lat:35.7010,lon:51.3910},{label:'جمهوری',lat:35.6950,lon:51.4130},
  {label:'تجریش',lat:35.8043,lon:51.4318},{label:'ونک',lat:35.7575,lon:51.4090},
  {label:'تهرانپارس',lat:35.7300,lon:51.5350},{label:'پونک',lat:35.7623,lon:51.3327},
  {label:'شهرک غرب',lat:35.7535,lon:51.3682},{label:'بازار بزرگ',lat:35.6725,lon:51.4208},
  {label:'میدان هفت تیر',lat:35.7159,lon:51.4251},{label:'نازی‌آباد',lat:35.6403,lon:51.4015}
].map(x=>({...x,approximate:true}));
const categories={
  'گوشی موبایل':['گوشی','موبایل','phone','iphone','آیفون'],
  'لپ تاپ و نوت بوک':['لپ تاپ','لپتاپ','نوت بوک','laptop','macbook','مک بوک'],
  'هدفون، هدست و هندزفری':['هدفون','هندزفری','هدست','ایرپاد','headphone','airpod'],
  'ساعت و مچ بند هوشمند':['ساعت هوشمند','smartwatch'],
  'مانیتور':['مانیتور','monitor'],'جارو برقی':['جاروبرقی','جارو برقی'],
  'قهوه و اسپرسو ساز':['اسپرسو','قهوه ساز'],'تلویزیون':['تلویزیون','tv'],'دوربین مدار بسته':['دوربین مداربسته','دوربین مدار بسته']
};
const brands={'سامسونگ':['سامسونگ','samsung'],'اپل':['اپل','apple','آیفون','iphone','مک بوک','macbook'],'شیائومی':['شیائومی','xiaomi','ردمی','redmi'],'سونی':['سونی','sony'],'ایسوس':['ایسوس','asus'],'لنوو':['لنوو','lenovo'],'دلونگی':['دلونگی','delonghi'],'انکر':['انکر','anker'],'جی بی ال':['جی بی ال','jbl']};
const colors=['مشکی','سفید','آبی','نقره ای','خاکستری','طلایی','صورتی','سبز','بنفش','قرمز'];
export function infer(message,previous={}){
  const p={...DEFAULT_PREFS,...previous},s=normalize(message);if(!s)return p;
  const brandEntry=Object.entries(brands).find(([,aliases])=>aliases.some(a=>s.includes(normalize(a))));
  if(/برند مهم نیست|فرقی نداره چه برندی|بدون محدودیت برند/.test(s)){p.brand='';p.brand_any=true;}
  else if(brandEntry){p.brand=brandEntry[0];p.brand_any=false;}
  if(/رنگ مهم نیست|هر رنگ|بدون محدودیت رنگ/.test(s)){p.color='';p.color_any=true;}
  else {const c=colors.find(c=>s.includes(normalize(c)));if(c){p.color=c;p.color_any=false;}}
  const nums=[...s.matchAll(/(\d[\d,٬]*(?:\.\d+)?)\s*(میلیون|میلیارد|هزار|تومن|تومان)/g)].map(m=>Number(m[1].replace(/[,٬]/g,''))*({'میلیون':1e6,'میلیارد':1e9,'هزار':1000}[m[2]]||1));
  if(nums.length){p.budget_any=false;if(nums.length>1&&/بین|از /.test(s)){p.budget_min=Math.min(...nums);p.budget_max=Math.max(...nums);}else p.budget_max=nums.at(-1);}
  if(/محدودیت بودجه ندارم|بدون محدودیت بودجه|بودجه مهم نیست/.test(s)){p.budget_max=null;p.budget_min=0;p.budget_any=true;}
  if(/فقط باز|الان باز|فروشگاه باز/.test(s))p.only_open=true;
  if(/بسته هم|همه فروشگاه/.test(s))p.only_open=false;
  if(s.includes('قسط'))p.installment=!/قسطی نمی|بدون قسط/.test(s);
  if(s.includes('ترب پی'))p.torobpay=true;
  if(s.includes('ارسال فوری'))p.fast_delivery=true;
  if(/نزدیک ترین|نزدیکتر|نزدیک تر/.test(s))p.sort='distance';
  if(/ارزان ترین|ارزون|کمترین قیمت/.test(s))p.sort='price';
  const category=Object.entries(categories).find(([,aliases])=>aliases.some(a=>s.includes(normalize(a))));
  if(category){if(p.category&&p.category!==category[0]){p.query='';p.brand=brandEntry?.[0]||'';}p.category=category[0];}
  const models=[...s.matchAll(/(?<![a-z0-9])(?:[as]\d{2}(?:\s*(?:fe|ultra))?|iphone\s*\d{1,2}(?:\s*pro(?:\s*max)?)?|wh[ -]?1000xm\d|ps[45])\b/gi)].map(m=>m[0]);
  if(models.length)p.query=models.join(' ');
  else if(!p.category&&!nums.length&&s.length>2){p.query=s.replace(/میخوام|می خوام|می خواهم|میخام|برای|بخرم|خرید|یک |یه |لطفا|مناسب|بهم|پیشنهاد|بده|دارم|نیاز/g,' ').trim().slice(0,200);}
  return p;
}
export function distanceKm(a,b){
  if(!a||b.lat==null||b.lon==null)return null;
  const rad=x=>x*Math.PI/180,la=rad(a.lat),lb=rad(b.lat),h=Math.sin((lb-la)/2)**2+Math.cos(la)*Math.cos(lb)*Math.sin(rad(b.lon-a.lon)/2)**2;
  return Math.round(6371*2*Math.asin(Math.min(1,Math.sqrt(h)))*100)/100;
}
export function openingStatus(hours={},now=new Date()){
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Tehran',weekday:'short',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(now).map(x=>[x.type,x.value]));
  const keys=['sun','mon','tue','wed','thu','fri','sat'],day=parts.weekday.toLowerCase(),today=hours?.[day]||{},yesterday=hours?.[keys[(keys.indexOf(day)+6)%7]]||{};
  const minute=+parts.hour*60+(+parts.minute),parse=t=>{const [h,m]=String(t??'').split(':').map(Number);return Number.isFinite(h)&&Number.isFinite(m)&&h>=0&&h<=24&&m>=0&&m<60&&(h<24||m===0)?h*60+m:null;};
  for(const s of yesterday.status==='declared'?yesterday.shifts||[]:[]){const a=parse(s.start_time),b=parse(s.end_time);if(a!==null&&b!==null&&a>b&&minute<b)return {state:'open',label:'طبق ساعت ثبت‌شده باز است',closes_at:s.end_time.slice(0,5)};}
  if(today.status==='closed')return {state:'closed',label:'طبق ساعت ثبت‌شده بسته است'};
  let valid=false;
  for(const s of today.status==='declared'?today.shifts||[]:[]){const a=parse(s.start_time),b=parse(s.end_time);if(a===null||b===null||a===b)continue;valid=true;if((a<b&&a<=minute&&minute<b)||(a>b&&minute>=a))return {state:'open',label:'طبق ساعت ثبت‌شده باز است',closes_at:s.end_time.slice(0,5)};}
  return valid?{state:'closed',label:'طبق ساعت ثبت‌شده بسته است'}:{state:'unknown',label:'ساعت کاری مشخص نیست'};
}
export const safeUrl=u=>{try{const p=new URL(u);return p.protocol==='https:'&&!p.username&&!p.password?u:'';}catch{return '';}};
export const torobUrl=title=>'https://torob.com/search/?query='+encodeURIComponent(title);
export const directionsUrl=shop=>'https://www.google.com/maps/dir/?api=1&destination='+encodeURIComponent(Number.isFinite(shop.lat)&&Number.isFinite(shop.lon)?shop.lat+','+shop.lon:[shop.name,shop.address].filter(Boolean).join(' '));
function paymentMatches(o,category,provider){return o.channel==='in_person'&&(!provider||normalize(o.provider_name)===normalize(provider))&&(!o.category_names?.length||o.category_names.some(c=>normalize(c)===normalize(category)));}
let catalogPromise;
export async function readPreviewCatalog(response){
  if(!response.ok)throw Error('داده‌های پیش‌نمایش بارگیری نشد.');
  const buffer=await response.arrayBuffer(),bytes=new Uint8Array(buffer);
  if(bytes[0]===0x1f&&bytes[1]===0x8b){
    return new Response(new Response(buffer).body.pipeThrough(new DecompressionStream('gzip'))).json();
  }
  return JSON.parse(new TextDecoder().decode(buffer));
}
export function loadCatalog(){return catalogPromise??=fetch('/data/catalog.json.gz').then(readPreviewCatalog).then(c=>{
  c.shopMap=new Map(c.shops.map(s=>[s.id,s]));c.offerMap=new Map();for(const o of c.offers){const arr=c.offerMap.get(o.product_id)||[];arr.push(o);c.offerMap.set(o.product_id,arr);}return c;
}).catch(e=>{catalogPromise=null;throw e;});}
export function searchSnapshot(c,p,location=null,now=new Date()){
  const priceNow=now;
  if(p.visit_at){const visit=new Date(/[zZ]|[+-]\d{2}:\d{2}$/.test(p.visit_at)?p.visit_at:p.visit_at+'+03:30');if(!Number.isNaN(+visit))now=visit;}
  const tokens=normalize(p.query).split(/[^\p{L}\p{N}]+/u).filter(Boolean).slice(0,8);
  const result=[];
  for(const product of c.products){
    if(p.category&&product.category!==p.category)continue;
    if(p.brand&&!product.search_text.includes(normalize(p.brand)))continue;
    if(p.color&&!product.color_text.includes(normalize(p.color)))continue;
    if(tokens.some(t=>!product.search_text.includes(t)))continue;
    const offers=[];
    for(const raw of c.offerMap.get(product.id)||[]){
      const s=c.shopMap.get(raw.shop_id);if(!s||!raw.price_toman||raw.price_toman<(p.budget_min||0)||(p.budget_max&&raw.price_toman>p.budget_max))continue;
      if(p.fast_delivery&&s.supports_fast_delivery!==true)continue;
      if(p.installment&&!s.payment_options.some(o=>paymentMatches(o,product.category)))continue;
      if(p.torobpay&&!s.payment_options.some(o=>paymentMatches(o,product.category,'ترب‌پی')))continue;
      const opening=openingStatus(s.weekly_hours,now),distance=distanceKm(location,s);
      if(p.only_open&&opening.state!=='open')continue;
      if(p.radius_km&&(distance===null||distance>p.radius_km))continue;
      const days=raw.last_price_changed_at?Math.max(0,Math.floor((priceNow-new Date(raw.last_price_changed_at))/86400000)):null;
      offers.push({...raw,currency:'تومان',source:'uploaded_dataset',price_age_days:days,price_stale:days===null||days>7,distance_km:distance,distance_type:'straight_line',availability:'recorded_offer',shop:{...s,contacts:[],contacts_published:false,opening}});
    }
    if(!offers.length)continue;
    const min=Math.min(...offers.map(o=>o.price_toman)),rank=o=>60*min/o.price_toman+(location?35/(1+(o.distance_km||0)/3):0)+3*(o.shop.opening.state==='open')+2*!o.price_stale;
    offers.sort((a,b)=>p.sort==='price'?a.price_toman-b.price_toman:p.sort==='distance'?(a.distance_km??Infinity)-(b.distance_km??Infinity)||a.price_toman-b.price_toman:rank(b)-rank(a));
    const best=offers[0],score=Math.min(99,Math.round(45+(p.brand?15:5)+(p.query?10:0)+15*min/best.price_toman+(location?14/(1+(best.distance_km||0)/3):0)));
    result.push({...product,best_offer:best,offers:offers.slice(0,100),offer_count:offers.length,min_price_toman:min,max_price_toman:Math.max(...offers.map(o=>o.price_toman)),score,
      reasons:['پیشنهاد فروش ثبت‌شده برای همین محصول',...(p.budget_max?['در محدوده بودجه انتخابی']:[]),...(location?['فاصله بر اساس مبدأ انتخابی']:[])],
      warnings:['قیمت و پیشنهاد فروش از فایل ثبت‌شده است؛ موجودی امروز را تأیید کنید.',...(best.price_stale?['قیمت ثبت‌شده قدیمی یا بدون زمان است.']:[]),...(p.color?['رنگ موجود نزد فروشنده نیاز به تأیید دارد.']:[])],source:'uploaded_dataset',torob_url:torobUrl(product.title)});
  }
  result.sort((a,b)=>p.sort==='price'?a.best_offer.price_toman-b.best_offer.price_toman:p.sort==='distance'?(a.best_offer.distance_km??Infinity)-(b.best_offer.distance_km??Infinity)||a.best_offer.price_toman-b.best_offer.price_toman:b.score-a.score||a.best_offer.price_toman-b.best_offer.price_toman);
  const cheapest=[...result].sort((a,b)=>a.min_price_toman-b.min_price_toman)[0]?.id,nearest=result.filter(r=>r.best_offer.distance_km!==null).sort((a,b)=>a.best_offer.distance_km-b.best_offer.distance_km)[0]?.id;
  for(const [i,r] of result.entries())r.badges=[...(i===0&&p.sort==='recommended'?['پیشنهاد ترب‌یار']:[]),...(r.id===cheapest?['کمترین قیمت']:[]),...(r.id===nearest?['نزدیک‌ترین پیشنهاد']:[])];
  return {products:result.slice(0,12),matched_count:result.length,source:'uploaded_dataset',origin:location};
}
export async function snapshotChat(message,previous,location){
  const p=infer(message,previous),c=await loadCatalog();
  const result=p.category||p.query?searchSnapshot(c,p,location):{products:[],matched_count:0};
  const questions=[];
  if(!p.category&&!p.query)questions.push({key:'product',text:'دنبال چه محصولی هستی؟',choices:['گوشی موبایل','لپ تاپ','هدفون','اسپرسو ساز']});
  else if(!p.budget_max&&!p.budget_any)questions.push({key:'budget',text:'حداکثر بودجه‌ات چقدر است؟',choices:['تا ۱۰ میلیون تومان','تا ۳۰ میلیون تومان','تا ۶۰ میلیون تومان','محدودیت بودجه ندارم']});
  else if(!p.brand&&!p.brand_any&&p.category==='گوشی موبایل')questions.push({key:'brand',text:'برند خاصی مدنظرت هست؟',choices:['سامسونگ','شیائومی','اپل','برند مهم نیست']});
  else if(!p.color&&!p.color_any)questions.push({key:'color',text:'چه رنگی را ترجیح می‌دهی؟',choices:['مشکی','سفید','رنگ مهم نیست']});
  if(!location)questions.push({key:'location',text:'برای دیدن نزدیک‌ترین فروشگاه، مبدأ خریدت را انتخاب کن.',choices:[]});
  const n=result.matched_count;
  return {...result,preferences:p,questions:questions.slice(0,2),llm:{configured:false,used:false,mode:'rules'},
    reply:!p.category&&!p.query?'بگو دنبال چه محصولی هستی تا قدم‌به‌قدم انتخابش کنیم.':n?`${fa(n)} محصول با پیشنهاد فروش ثبت‌شده با انتخاب‌های تو سازگار است. قیمت، فروشگاه و شرایط خرید را کنار هم ببین.`:'با همه این شرایط، پیشنهادی در داده‌های پیش‌نمایش پیدا نشد. بودجه، برند یا فیلترها را تغییر بده، یا در ترب جستجو کن.'};
}
