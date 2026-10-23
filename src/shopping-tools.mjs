import {comparePayment} from './purchase.mjs';
export function googleMapsUrl(shop){return Number.isFinite(shop.lat)&&Number.isFinite(shop.lon)?'https://www.google.com/maps/search/?api=1&query='+encodeURIComponent(shop.lat+','+shop.lon):'https://www.google.com/maps/search/?api=1&query='+encodeURIComponent([shop.name,shop.address].filter(Boolean).join(' '));}
export function changedPreference(prefs,key,value){
  const next={...prefs,[key]:value};
  if(key==='budget_max'){next.budget_any=value===null;if(value===null)next.budget_min=0;}
  if(key==='brand'||key==='color')next[key+'_any']=!value;
  if(key==='model'){next.query='';next.task='shopping';}
  if(key==='category'){for(const k of ['query','model','product_type','brand','color','needs','size'])next[k]='';next.condition='any';next.brand_any=false;next.color_any=false;next.task='shopping';}
  return next;
}
export function installmentTotal({cash,down,monthly,count,fees=0}){
  const result=comparePayment({cash:Number(cash),upfront:Number(down),months:Number(count),monthly:Number(monthly),fees:Number(fees)});
  return result.error?null:{total:result.total,extra:result.difference,extraPercent:result.markupPercent};
}
export const neshanMapsUrl=shop=>Number.isFinite(shop.lat)&&Number.isFinite(shop.lon)?'https://nshn.ir/?lat='+shop.lat+'&lng='+shop.lon:'https://neshan.org/maps/?search='+encodeURIComponent([shop.name,shop.address].filter(Boolean).join(' '));
