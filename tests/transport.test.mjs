import test from 'node:test';
import assert from 'node:assert/strict';
import {apiBase,createClient,validateHealth,validateChat} from '../src/transport.mjs';

test('origin rejection is translated and never treated as a successful assistant response',async()=>{
  for(const status of [200,403]){
    const request=createClient('',async()=>({ok:status===200,status,json:async()=>({error:'origin_not_allowed'})}));
    await assert.rejects(request('chat/',{method:'POST',body:'{}'}),e=>e.code==='origin_not_allowed'&&!e.message.includes('origin_not_allowed')&&e.message.includes('Django'));
  }
});
test('public Torob API cannot be accidentally configured as the Django API',()=>{
  assert.throws(()=>apiBase('https://api.torob.com/'),e=>e.code==='api_configuration');
  assert.equal(apiBase('http://127.0.0.1:8000/api/'),'http://127.0.0.1:8000');
});
test('same-origin proxy is used for localhost requests',async()=>{
  let url;const request=createClient('',async(u)=>{url=u;return {ok:true,status:200,json:async()=>({status:'ok'})};});
  await request('health/');assert.equal(url,'/api/health/');
});
test('an unrelated JSON health response cannot enable API mode',()=>{
  assert.throws(()=>validateHealth({status:'ok'}),e=>e.code==='wrong_backend');
  assert.equal(validateHealth({status:'ok',backend:'django',service:'torob-yar',api_version:3}).service,'torob-yar');
});
test('HTML and malformed chat payloads remain connection errors',async()=>{
  const request=createClient('',async()=>({ok:true,status:200,json:async()=>{throw Error('HTML');}}));
  await assert.rejects(request('health/'),e=>e.code==='not_django_api');
  assert.throws(()=>validateChat({error:'origin_not_allowed'}),e=>e.code==='invalid_chat_response');
});

test('a stale backend or another local project instance cannot pass health validation',()=>{
  const health={status:'ok',backend:'django',service:'torob-yar',api_version:3,instance_id:'current'};
  assert.equal(validateHealth(health,'current').api_version,3);
  assert.throws(()=>validateHealth({...health,api_version:2}),e=>e.code==='wrong_backend');
  assert.throws(()=>validateHealth(health,'other'),e=>e.code==='wrong_backend');
});
