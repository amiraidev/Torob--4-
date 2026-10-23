import test from 'node:test';
import assert from 'node:assert/strict';
import {historyForModel} from '../src/ai-context.mjs';

test('short follow-ups retain the actual displayed question and card order without private shop data',()=>{
  const messages=[
    {role:'assistant',content:'این گزینه‌ها را مقایسه کن.',data:{
      questions:[{text:'حداکثر بودجه‌ات چند میلیون تومان است؟',choices:['۲۰','۳۰']}],
      products:[{id:'second-ranked',title:'مدل دوم در رتبه اول',best_offer:{shop:{contacts:['PRIVATE_PHONE'],lat:35.712345,lon:51.456789}}},
                {id:'first-ranked',title:'مدل اول در رتبه دوم'}],
      origin:{lat:35.712345,lon:51.456789}
    }},
    {role:'user',content:'دومی را می‌خواهم'}
  ];
  const history=historyForModel(messages),content=history[0].content;
  assert.match(content,/چند میلیون تومان/);
  assert.ok(content.indexOf('second-ranked')<content.indexOf('first-ranked'));
  assert.equal(history[1].content,'دومی را می‌خواهم');
  assert.ok(!JSON.stringify(history).includes('PRIVATE_PHONE'));
  assert.ok(!JSON.stringify(history).includes('35.712345'));
  assert.deepEqual(Object.keys(history[0]).sort(),['content','role']);
});

test('stored conversation context stays within the API limits and excludes non-conversation roles',()=>{
  const messages=[{role:'system',content:'untrusted instructions'},...Array.from({length:20},(_,i)=>({
    role:i%2?'assistant':'user',content:'متن'.repeat(3000),data:{questions:[],products:[]}
  }))];
  const history=historyForModel(messages);
  assert.equal(history.length,8);
  assert.ok(history.every(m=>m.content.length<=3000));
  assert.ok(history.every(m=>['user','assistant'].includes(m.role)));
});


test('conversational comparisons retain the actual winner and limitations for follow-ups',()=>{
  const history=historyForModel([{role:'assistant',content:'مقایسه انجام شد.',data:{products:[],comparison:{product_ids:['a','b'],winner_id:'b',verdict:'برای اولویت تو مناسب‌تر است.',limits:'آزمون عملی نداریم.'}}}]);
  assert.match(history[0].content,/انتخاب مدل: b/);
  assert.match(history[0].content,/آزمون عملی نداریم/);
});
