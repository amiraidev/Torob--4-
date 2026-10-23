// Send the visible question and card order, never entire stored catalog records.
const clip=(value,max)=>typeof value==='string'?value.slice(0,max):'';
export function historyForModel(messages){
  return messages.filter(m=>m&&['user','assistant'].includes(m.role)).slice(-8).map(m=>{
    let content=clip(m.content,m.role==='assistant'?1200:2000);
    if(m.role==='assistant'&&m.data){
      const questions=(Array.isArray(m.data.questions)?m.data.questions:[]).slice(0,2).map(q=>{
        const choices=(Array.isArray(q.choices)?q.choices:[]).slice(0,4).map(c=>clip(c,50)).filter(Boolean);
        return clip(q.text,180)+(choices.length?' ['+choices.join(' / ')+']':'');
      }).filter(Boolean);
      const cards=(Array.isArray(m.data.products)?m.data.products:[]).slice(0,4).map((p,i)=>
        (i+1)+'. '+clip(p.title,140)+' [product_id='+clip(p.id,80)+']');
      if(questions.length)content+='\nسؤال‌های نمایش‌داده‌شده: '+questions.join('؛ ');
      if(cards.length)content+='\nترتیب کارت‌های نمایش‌داده‌شده: '+cards.join('؛ ');
      const c=m.data.comparison;
      if(c?.product_ids?.length)content+='\nمقایسه نمایش‌داده‌شده: '+c.product_ids.map(id=>clip(id,80)).join(' / ')+
        '; انتخاب مدل: '+clip(c.winner_id,80)+'; '+clip(c.verdict,450)+'; محدودیت: '+clip(c.limits,180);
    }
    return {role:m.role,content:content.slice(0,3000)};
  });
}

