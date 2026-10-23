import React,{useEffect,useRef,useMemo,useState} from 'react';
import {Store,Navigation,MapPin,ExternalLink} from 'lucide-react';
import {fa,money,directionsUrl} from './engine.mjs';
import {request} from './api.js';
import {googleMapsUrl,neshanMapsUrl} from './shopping-tools.mjs';
let sdkPromise;
function loadSDK(config){
  if(window.maplibregl?.default)return Promise.resolve(window.maplibregl.default);
  if(sdkPromise)return sdkPromise;
  sdkPromise=new Promise((resolve,reject)=>{
    if(!document.getElementById('neshan-map-style')){const css=document.createElement('link');css.id='neshan-map-style';css.rel='stylesheet';css.href=config.sdk_css;document.head.appendChild(css);}
    const js=document.createElement('script');js.src=config.sdk_url;js.async=true;
    const timer=setTimeout(()=>{js.remove();sdkPromise=null;reject(new Error('مهلت بارگذاری نقشه نشان تمام شد.'));},20000);
    js.onload=()=>{clearTimeout(timer);if(window.maplibregl?.default)resolve(window.maplibregl.default);else{sdkPromise=null;reject(new Error('کتابخانه نقشه نشان بارگذاری نشد.'));}};
    js.onerror=()=>{clearTimeout(timer);js.remove();sdkPromise=null;reject(new Error('ارتباط با نقشه نشان برقرار نشد.'));};document.head.appendChild(js);
  });return sdkPromise;
}
function NeshanMapPanel({products=[],location,onDetail,places=[]}){
  const container=useRef(null),map=useRef(null),markers=useRef([]),sdk=useRef(null);
  const [ready,setReady]=useState(0),[error,setError]=useState(''),[config,setConfig]=useState(null);
  const sellers=useMemo(()=>{const seen=new Set();return products.flatMap(p=>p.offers.map(o=>({...o,product:p}))).filter(o=>{if(seen.has(o.shop.id)||!Number.isFinite(o.shop.lat)||!Number.isFinite(o.shop.lon))return false;seen.add(o.shop.id);return true;}).slice(0,50);},[products]);
  const points=useMemo(()=>[...sellers.map(o=>({...o.shop,product:o.product,price:o.price_toman})),...places.filter(p=>Number.isFinite(p.lat)&&Number.isFinite(p.lon))].slice(0,60),[sellers,places]);
  useEffect(()=>{let alive=true;request('map-config/').then(c=>{if(alive){setConfig(c);if(!c.map_key)setError('برای نمایش نقشه نشان، کلید وب NESHAN_MAP_KEY را در تنظیمات سرور وارد کن.');}}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[]);
  useEffect(()=>{if(!config?.map_key||!container.current)return;let alive=true,observer;
    loadSDK(config).then(lib=>{if(!alive)return;sdk.current=lib;const m=new lib.Map({container:container.current,style:config.style,center:[51.405,35.716],zoom:12,apiKey:config.map_key,rtl:{lazy:false},trackResize:true});map.current=m;m.addControl(new lib.NavigationControl(),'bottom-left');m.on('load',()=>{if(alive)setReady(x=>x+1);});m.on('error',()=>{if(alive)setError('نمایش نقشه کامل نشد؛ کلید وب، دامنه مجاز و دسترسی شبکه نشان را بررسی کن.');});observer=new ResizeObserver(()=>m.resize());observer.observe(container.current);}).catch(e=>{if(alive)setError(e.message);});
    return()=>{alive=false;observer?.disconnect();markers.current.forEach(m=>m.remove());markers.current=[];map.current?.remove();map.current=null;};
  },[config]);
  useEffect(()=>{const m=map.current,lib=sdk.current;if(!m||!lib||!ready)return;markers.current.forEach(x=>x.remove());markers.current=[];const bounds=new lib.LngLatBounds();let count=0;
    points.forEach((s,i)=>{const pos=[s.lon,s.lat];bounds.extend(pos);count++;const el=document.createElement('button');el.className='neshan-shop-marker';el.textContent=fa(i+1);el.setAttribute('aria-label',s.name);const box=document.createElement('div');box.dir='rtl';for(const value of [s.name,s.price?money(s.price)+' تومان':s.identity_status==='selected_candidate'?'فروشگاه انتخاب‌شده':'نتیجه جست‌وجو؛ هویت را تطبیق بده',s.address]){const p=document.createElement('p');p.textContent=value||'';box.appendChild(p);}markers.current.push(new lib.Marker({element:el}).setLngLat(pos).setPopup(new lib.Popup({offset:18}).setDOMContent(box)).addTo(m));});
    if(location){const pos=[location.lon,location.lat];bounds.extend(pos);count++;const el=document.createElement('span');el.className='neshan-user-marker';el.title=location.approximate?'مبدأ تقریبی':`GPS با دقت گزارش‌شده ${location.accuracy_m??'نامشخص'} متر`;markers.current.push(new lib.Marker({element:el}).setLngLat(pos).addTo(m));}
    if(count)m.fitBounds(bounds,{padding:55,maxZoom:16,duration:450});
  },[points,location,ready]);
  return <div className="map-layout"><div className="neshan-map-area"><div className="map-canvas" ref={container} aria-label="نقشه نشان فروشگاه‌ها"/>{error&&<div className="map-provider-notice" role="status"><MapPin size={24}/><p>{error}</p><a href="https://platform.neshan.org/panel/" target="_blank" rel="noreferrer">تنظیم کلید نشان</a></div>}</div><div className="map-seller-panel"><header><Store size={17}/><strong>{fa(points.length)} فروشگاه و نتیجه مکانی</strong><small>نقشه نشان</small></header>{points.length?points.map((s,i)=><article className="map-seller" key={s.id}><div><span className="map-index">{fa(i+1)}</span><h3>{s.name}</h3></div><p>{s.address||s.location_label}</p>{s.price&&<strong>{money(s.price)} <small>تومان</small></strong>}{s.identity_status==='candidate'&&<small>نام و آدرس این نتیجه را تطبیق بده.</small>}<div className="map-seller-actions">{s.product&&<button onClick={()=>onDetail(s.product)}>جزئیات</button>}<a href={neshanMapsUrl(s)} target="_blank" rel="noreferrer">نشان<Navigation size={13}/></a><a href={googleMapsUrl(s)} target="_blank" rel="noreferrer">گوگل‌مپ<ExternalLink size={13}/></a></div></article>):<div className="map-empty"><MapPin size={27}/><p>فروشگاه‌های دارای مختصات اینجا نمایش داده می‌شوند.</p></div>}</div></div>;
}

const EMPTY=[];
function GoogleMapPanel({products=EMPTY,location,places=EMPTY,onDetail,apiKey=''}){
  const [selected,setSelected]=useState(0);
  const sellers=useMemo(()=>{const seen=new Set();return [...products.flatMap(p=>(p.offers||[]).map(o=>({...o,product:p}))),...places.map(p=>({id:p.id,shop:p,price_toman:null}))].filter(o=>{const key=(o.shop.provider||'torob')+o.shop.id;if(seen.has(key)||!Number.isFinite(o.shop.lat)||!Number.isFinite(o.shop.lon))return false;seen.add(key);return true;}).slice(0,60);},[products,places]);
  useEffect(()=>setSelected(0),[sellers]);
  const shop=sellers[selected]?.shop||sellers[0]?.shop||location;
  const q=shop?.lat!=null&&shop?.lon!=null?shop.lat+','+shop.lon:'تهران';
  const src=apiKey?'https://www.google.com/maps/embed/v1/place?'+new URLSearchParams({key:apiKey,q,language:'fa'}):'https://maps.google.com/maps?'+new URLSearchParams({q,z:'14',hl:'fa',output:'embed'});
  return <div className="map-layout"><div className="map-canvas"><iframe className="google-map-frame" title="موقعیت فروشگاه در گوگل‌مپ" src={src} loading="lazy" allowFullScreen referrerPolicy="strict-origin-when-cross-origin"/></div><div className="map-seller-panel"><header><Store size={17}/><strong>{fa(sellers.length)} فروشگاه و مکان</strong></header>{sellers.map((o,i)=><article className={'map-seller '+(selected===i?'selected':'')} key={(o.shop.provider||'torob')+o.shop.id}><button className="map-select" onClick={()=>setSelected(i)}><span className="map-index">{fa(i+1)}</span><h3>{o.shop.name}</h3></button><p>{o.shop.address||o.shop.location_label}</p>{o.price_toman!=null&&<strong>{money(o.price_toman)} تومان</strong>}<div className="map-seller-actions">{o.product&&<button onClick={()=>onDetail(o.product)}>جزئیات</button>}<a href={directionsUrl(o.shop)} target="_blank" rel="noreferrer">مسیریابی گوگل<Navigation size={13}/></a><a href={neshanMapsUrl(o.shop)} target="_blank" rel="noreferrer">نشان</a></div></article>)}{!sellers.length&&<div className="map-empty"><MapPin size={25}/><p>پس از جستجوی محصول، فروشنده‌های دارای مختصات اینجا نمایش داده می‌شوند.</p></div>}</div></div>;
}
export default function MapPanel({products=EMPTY,location,onDetail,places=EMPTY}){
  const [provider,setProvider]=useState('google'),[config,setConfig]=useState({});
  useEffect(()=>{request('map-config/').then(setConfig).catch(()=>{});},[]);
  const neshanPlaces=useMemo(()=>places.filter(p=>!['google','google_places'].includes(p.provider)),[places]);
  return <div className="maps-section"><div className="map-provider-switch" role="group" aria-label="سرویس نقشه"><button className={provider==='google'?'active':''} onClick={()=>setProvider('google')}>گوگل‌مپ <small>پیش‌فرض</small></button><button className={provider==='neshan'?'active':''} onClick={()=>setProvider('neshan')}>نشان</button></div>{provider==='google'?<GoogleMapPanel products={products} location={location} onDetail={onDetail} places={places} apiKey={config.google_browser_key}/>:<NeshanMapPanel products={products} location={location} onDetail={onDetail} places={neshanPlaces}/>}<p className="map-caption">با انتخاب فروشگاه، مختصات ثبت‌شده همان مکان نمایش داده می‌شود. فاصله مستقیم است؛ طبقه و واحد فقط از اطلاعات ثبت‌شده یا اعلام خودت مشخص می‌شوند.</p></div>;
}
