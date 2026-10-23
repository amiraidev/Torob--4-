import test from 'node:test';
import assert from 'node:assert/strict';
import {gzipSync} from 'node:zlib';
import {readPreviewCatalog} from '../src/engine.mjs';

test('compressed preview keeps all product data',async()=>{
  const catalog={products:[{id:'p',title:'گوشی',specs:[{key:'رنگ',value:'مشکی'}]}],shops:[],offers:[]};
  assert.deepEqual(await readPreviewCatalog(new Response(gzipSync(JSON.stringify(catalog)))),catalog);
});
test('preview also accepts a body already decompressed by the browser',async()=>{
  const catalog={products:[],shops:[],offers:[]};
  assert.deepEqual(await readPreviewCatalog(new Response(JSON.stringify(catalog),{headers:{'Content-Encoding':'gzip'}})),catalog);
});
test('missing preview stays a visible error',async()=>{
  await assert.rejects(readPreviewCatalog(new Response('',{status:404})),/بارگیری/);
});
