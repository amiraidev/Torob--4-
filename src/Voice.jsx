import React,{useEffect,useRef,useState} from 'react';
import {Mic,Square,Volume2,VolumeX} from 'lucide-react';

// Progressive enhancement: permissions and recognition start only after a click.
export function VoiceInput({onTranscript,disabled=false}){
  const Recognition=globalThis.SpeechRecognition||globalThis.webkitSpeechRecognition;
  const recognition=useRef(null),final=useRef(''),callback=useRef(onTranscript);
  const [listening,setListening]=useState(false),[interim,setInterim]=useState(''),[error,setError]=useState('');
  callback.current=onTranscript;
  useEffect(()=>()=>{if(recognition.current){recognition.current.onend=null;recognition.current.abort();}},[]);
  useEffect(()=>{if(disabled&&recognition.current){final.current='';recognition.current.abort();}},[disabled]);
  function toggle(){
    if(listening){recognition.current?.stop();return;}
    if(!Recognition)return;
    const r=new Recognition();recognition.current=r;final.current='';setError('');setInterim('');
    r.lang='fa-IR';r.continuous=false;r.interimResults=true;r.maxAlternatives=1;
    r.onstart=()=>setListening(true);
    r.onresult=e=>{let pending='';for(let i=e.resultIndex;i<e.results.length;i++){const t=e.results[i][0]?.transcript||'';if(e.results[i].isFinal)final.current+=' '+t;else pending+=t;}setInterim((final.current+' '+pending).trim());};
    r.onerror=e=>{setError(({ 'not-allowed':'مجوز میکروفون داده نشد؛ دسترسی مرورگر را بررسی کن.','service-not-allowed':'سرویس گفتار مرورگر در دسترس نیست.','audio-capture':'میکروفون در دسترس نیست.','network':'اتصال سرویس تشخیص گفتار مرورگر برقرار نشد.','no-speech':'صدایی تشخیص داده نشد؛ دوباره امتحان کن.'})[e.error]||'تشخیص گفتار کامل نشد؛ می‌توانی پیام را تایپ کنی.');};
    r.onend=()=>{setListening(false);setInterim('');const value=final.current.trim();final.current='';recognition.current=null;if(value)callback.current(value);};
    try{globalThis.speechSynthesis?.cancel();r.start();}catch{recognition.current=null;setListening(false);setError('شروع میکروفون ممکن نشد. صفحه را با HTTPS یا localhost باز کن.');}
  }
  return <span className="voice-input"><button type="button" className={'icon-button voice-button '+(listening?'listening':'')} disabled={disabled||!Recognition} onClick={toggle} aria-label={listening?'پایان ضبط صدا':'گفتن پیام با میکروفون'} aria-pressed={listening} title={Recognition?'تشخیص گفتار توسط مرورگر؛ ممکن است از سرویس آنلاین آن استفاده کند. متن پیش از ارسال قابل ویرایش است.':'این مرورگر تشخیص گفتار ندارد؛ پیام را تایپ کن.'}>{listening?<Square size={18}/>:<Mic size={19}/>}</button>{(listening||error)&&<span className="voice-feedback" role="status">{error||interim||'گوش می‌دهم… پس از پایان، متن را بررسی و ارسال کن.'}</span>}</span>;
}

export function ReadAloud({text}){
  const utterance=useRef(null);const [speaking,setSpeaking]=useState(false),[error,setError]=useState('');
  useEffect(()=>()=>{if(utterance.current){utterance.current.onend=null;utterance.current.onerror=null;globalThis.speechSynthesis?.cancel();}},[]);
  if(!globalThis.speechSynthesis||!globalThis.SpeechSynthesisUtterance)return null;
  function toggle(){
    if(speaking){globalThis.speechSynthesis.cancel();setSpeaking(false);return;}
    setError('');globalThis.speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);utterance.current=u;u.lang='fa-IR';
    const voice=globalThis.speechSynthesis.getVoices().find(v=>v.lang?.toLowerCase().startsWith('fa'));
    if(voice)u.voice=voice;
    else setError('پخش فارسی به صداهای نصب‌شده در مرورگر بستگی دارد.');
    u.onend=()=>setSpeaking(false);u.onerror=e=>{setSpeaking(false);if(!['interrupted','canceled'].includes(e.error))setError('خواندن پاسخ در این مرورگر ممکن نشد.');};
    try{globalThis.speechSynthesis.speak(u);setSpeaking(true);}catch{setError('سرویس خواندن متن در دسترس نیست.');}
  }
  return <span className="read-aloud"><button type="button" className="text-button" onClick={toggle} aria-label={speaking?'توقف خواندن پاسخ':'خواندن پاسخ با صدا'}>{speaking?<VolumeX size={16}/>:<Volume2 size={16}/>}<span>{speaking?'توقف پخش':'شنیدن پاسخ'}</span></button>{error&&<small role="status">{error}</small>}</span>;
}
