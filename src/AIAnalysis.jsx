import React from 'react';
import {Sparkles,Info,ChevronDown,ArrowUpLeft} from 'lucide-react';
import {displayValue} from './engine.mjs';
import './ai-analysis.css';

export function ModelReason({product,onDetail}){
  const analysis=product.ai_analysis;
  if(!analysis)return null;
  return <article className="model-reason">
    {onDetail&&<button className="model-product-title" onClick={()=>onDetail(product)}>{product.title}<ArrowUpLeft size={15}/></button>}
    {analysis.verdict&&<p>{analysis.verdict}</p>}
    {analysis.supporting_specs?.length>0&&<dl className="model-specs">{analysis.supporting_specs.map(s=><div key={s.key}><dt>{s.key}</dt><dd>{displayValue(s.value)}</dd></div>)}</dl>}
    {analysis.tradeoff&&<p className="model-tradeoff"><strong>نکته تصمیم:</strong> {analysis.tradeoff}</p>}
    {analysis.unknowns?.length>0&&<div className="model-unknowns"><strong>هنوز نیاز به بررسی دارد</strong><ul>{analysis.unknowns.map((text,i)=><li key={i}>{text}</li>)}</ul></div>}
  </article>;
}

export default function AIAnalysis({data,onDetail}){
  if(!data.llm?.analysis_status)return null;
  const analyzed=data.llm.analysis_used===true;
  const products=(data.products||[]).filter(p=>p.ai_analysis).slice(0,3);
  return <section className={'ai-analysis '+(analyzed?'analyzed':'rules')} aria-label="وضعیت تحلیل خرید">
    <div className="ai-analysis-heading">{analyzed?<Sparkles size={17}/>:<Info size={17}/>}<strong>{analyzed?'تحلیل هوش مصنوعی':'راهنمای داده‌محور'}</strong></div>
    <p className="ai-analysis-status" role="status">{data.llm.message}</p>
    {analyzed&&products.length>0&&<div className="model-comparisons">{products.map(product=><ModelReason key={product.id} product={product} onDetail={onDetail}/>)}</div>}
    {analyzed&&data.analysis?.shopping_tips?.length>0&&<details className="model-tips"><summary>پیش از مراجعه بررسی کن<ChevronDown size={14}/></summary><ul>{data.analysis.shopping_tips.map((tip,i)=><li key={i}>{tip}</li>)}</ul></details>}
    {analyzed&&<small className="model-basis">تحلیل بر پایه اطلاعات همین نتایج است؛ مشخصات ثبت‌شده، آزمون عملی کیفیت و تضمین موجودی نیست.</small>}
  </section>;
}

