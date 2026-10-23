import test from 'node:test';
import assert from 'node:assert/strict';
import {changedPreference,googleMapsUrl,installmentTotal,neshanMapsUrl} from '../src/shopping-tools.mjs';
import {directionsUrl} from '../src/engine.mjs';
test('Google directions are primary and the Neshan option keeps coordinate order',()=>{
 const shop={lat:35.7,lon:51.4};assert.equal(new URL(directionsUrl(shop)).searchParams.get('destination'),'35.7,51.4');assert.equal(neshanMapsUrl(shop),'https://nshn.ir/?lat=35.7&lng=51.4');
 assert.equal(new URL(googleMapsUrl(shop)).searchParams.get('query'),'35.7,51.4');
});
test('explicit any choices do not trigger repeated questions',()=>{
 assert.equal(changedPreference({},'color','').color_any,true);assert.equal(changedPreference({},'brand','').brand_any,true);
 assert.deepEqual(changedPreference({budget_min:10},'budget_max',null),{budget_min:0,budget_max:null,budget_any:true});
});
test('changing model clears the old query and returns to product shopping',()=>{
 const p=changedPreference({query:'a55',task:'store'},'model','s25 fe');assert.equal(p.query,'');assert.equal(p.task,'shopping');
});
test('installment comparison counts down payment, every installment and fees',()=>{
 const p=installmentTotal({cash:100,down:20,monthly:25,count:4,fees:5});assert.equal(p.total,125);assert.equal(p.extra,25);assert.equal(p.extraPercent,25);
 assert.equal(installmentTotal({cash:100,down:0,monthly:5,count:2.5}),null);assert.equal(installmentTotal({cash:0,down:0,monthly:5,count:2}),null);
});

test('invalid installment offers never yield misleading totals',()=>{
 for(const p of [{cash:1,down:0,monthly:-1,count:2},{cash:1,down:0,monthly:5,count:121},{cash:1,down:0,monthly:Number.MAX_SAFE_INTEGER,count:120}])assert.equal(installmentTotal(p),null);
});
