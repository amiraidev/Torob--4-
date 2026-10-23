import test from 'node:test';
import assert from 'node:assert/strict';
import {infer,DEFAULT_PREFS,openingStatus,distanceKm,searchSnapshot,safeUrl} from '../src/engine.mjs';

test('Persian budget + model + brand are parsed without reading storage as money',()=>{
  const p=infer('گوشی سامسونگ A55 حافظه ۲۵۶ با بودجه ۱۲۰ میلیون تومان');
  assert.equal(p.budget_max,120000000);assert.equal(p.query,'a55');assert.equal(p.brand,'سامسونگ');
  assert.equal(infer('گوشی سامسونگ حافظه ۲۵۶ رم ۸').budget_max,null);
});
test('No-preference answers do not create a question loop',()=>{
  const p=infer('رنگ مهم نیست',infer('برند مهم نیست',infer('محدودیت بودجه ندارم')));
  assert.equal(p.color_any,true);assert.equal(p.brand_any,true);assert.equal(p.budget_any,true);
});
test('Unknown hours are never reported as open',()=>{
  assert.equal(openingStatus({}).state,'unknown');
  assert.equal(openingStatus({thu:{status:'declared',shifts:[{start_time:'00:00:00',end_time:'00:00:00'}]}},new Date('2026-10-22T10:00:00Z')).state,'unknown');
});
test('Tehran overnight opening is handled at both sides of midnight',()=>{
  const h={wed:{status:'declared',shifts:[{start_time:'22:00:00',end_time:'02:00:00'}]},thu:{status:'closed'}};
  assert.equal(openingStatus(h,new Date('2026-10-21T20:00:00Z')).state,'open');
  assert.equal(openingStatus(h,new Date('2026-10-21T21:30:00Z')).state,'open');
  assert.equal(openingStatus(h,new Date('2026-10-22T06:00:00Z')).state,'closed');
});
test('Distance is zero at origin and null without origin',()=>{
  assert.equal(distanceKm({lat:35.7,lon:51.4},{lat:35.7,lon:51.4}),0);
  assert.equal(distanceKm(null,{lat:35.7,lon:51.4}),null);
});
function fixture(){
  const shops=[{id:'s1',name:'Actual offer',lat:35.7,lon:51.4,weekly_hours:{},payment_options:[],categories:['گوشی موبایل']},
    {id:'category-only',name:'Category only',lat:35.7,lon:51.4,weekly_hours:{},payment_options:[],categories:['گوشی موبایل']}];
  const products=[{id:'p',title:'گوشی سامسونگ',category:'گوشی موبایل',brand:'سامسونگ',search_text:'گوشی سامسونگ',color_text:'مشکی',images:[],specs:[]}];
  const offers=[{id:'o',product_id:'p',shop_id:'s1',price_toman:100,last_price_changed_at:null}];
  return {products,shopMap:new Map(shops.map(s=>[s.id,s])),offerMap:new Map([['p',offers]])};
}
test('Hard constraints never silently relax budget, open status or installment type',()=>{
  const c=fixture();assert.equal(searchSnapshot(c,{...DEFAULT_PREFS,budget_max:99}).matched_count,0);
  assert.equal(searchSnapshot(c,{...DEFAULT_PREFS,only_open:true}).matched_count,0);
  c.shopMap.get('s1').payment_options=[{provider_name:'ترب‌پی',channel:'unknown',category_names:[]}];
  assert.equal(searchSnapshot(c,{...DEFAULT_PREFS,torobpay:true}).matched_count,0);
  c.shopMap.get('s1').payment_options=[{provider_name:'ترب‌پی',channel:'in_person',category_names:[]}];
  assert.equal(searchSnapshot(c,{...DEFAULT_PREFS,torobpay:true}).matched_count,1);
});
test('A shop with category only is not presented as owning the product',()=>{
  const r=searchSnapshot(fixture(),DEFAULT_PREFS);assert.equal(r.products[0].offer_count,1);assert.equal(r.products[0].best_offer.shop.id,'s1');assert.equal(r.products[0].best_offer.price_stale,true);
});
test('Active links reject javascript and credential URLs',()=>{
  assert.equal(safeUrl('javascript:alert(1)'),'');assert.equal(safeUrl('https://user:secret@example.com'),'');assert.equal(safeUrl('https://torob.com/'),'https://torob.com/');
});
