export class ApiError extends Error {
  constructor(message,code='connection_failed',status=0){super(message);this.name='ApiError';this.code=code;this.status=status;}
}
export function apiBase(value=''){
  if(!value.trim())return '';
  let url;
  try{url=new URL(value.trim());}catch{throw new ApiError('آدرس API معتبر نیست؛ آدرس سرور Django را در VITE_API_BASE_URL قرار بده.','api_configuration');}
  if(!['https:','http:'].includes(url.protocol)||url.username||url.password||url.search||url.hash||url.hostname==='api.torob.com')
    throw new ApiError('VITE_API_BASE_URL باید آدرس بک‌اند Django باشد؛ آدرس ترب یا سرویس مدل را اینجا نگذار.','api_configuration');
  return url.href.replace(/\/$/,'').replace(/\/api$/,'');
}
export function errorMessage(data,status){
  const code=String(data?.code||data?.error?.code||(typeof data?.error==='string'?data.error:'')||'');
  if(code.startsWith('torob_'))return {code,message:typeof data?.detail==='string'?data.detail:'ارتباط سرور با ترب برقرار نشد؛ این خطا به معنی پیدا نشدن محصول نیست.'};
  if(code==='origin_not_allowed'||data?.detail==='origin_not_allowed')return {code:'origin_not_allowed',message:'سرور، مبدأ این صفحه را نپذیرفت. آدرس API باید به Django اشاره کند؛ برنامه را با python scripts/run.py اجرا کن و آدرس چاپ‌شده را باز کن.'};
  if(status===429)return {code:'rate_limited',message:'تعداد درخواست‌ها زیاد شده؛ کمی صبر کن و دوباره تلاش کن.'};
  if(status===401||status===403)return {code:'access_denied',message:'اجازه ارتباط با این سرور داده نشده است. آدرس بک‌اند و تنظیمات مبدأ مجاز را بررسی کن.'};
  if(status>=500)return {code:'backend_error',message:'بک‌اند پاسخ مناسبی نداد. وضعیت Django را در ترمینال بررسی کن.'};
  const detail=typeof data?.detail==='string'&&/[\u0600-\u06ff]/.test(data.detail)?data.detail:null;
  return {code:code||'invalid_request',message:detail||'درخواست قابل پردازش نبود؛ ورودی‌ها و آدرس بک‌اند را بررسی کن.'};
}
export function createClient(base='',fetcher=globalThis.fetch){
  return async function request(path,options={}){
    const baseUrl=apiBase(base),controller=new AbortController();
    const {timeout=240000,...init}=options;
    const timer=setTimeout(()=>controller.abort(),timeout);
    try{
      const response=await fetcher(baseUrl+'/api/'+path,{...init,headers:{'Accept':'application/json',...(init.body?{'Content-Type':'application/json'}:{}),...init.headers},signal:controller.signal});
      let data;try{data=await response.json();}catch{throw new ApiError('به‌جای API جنگو، یک صفحه وب پاسخ داده است. آدرس بک‌اند و اجرای هم‌زمان دو سرور را بررسی کن.','not_django_api',response.status);}
      if(!response.ok||data?.error||data?.code==='origin_not_allowed'){
        const issue=errorMessage(data,response.status);throw new ApiError(issue.message,issue.code,response.status);
      }
      return data;
    }catch(e){
      if(e instanceof ApiError)throw e;
      if(e.name==='AbortError')throw new ApiError('پاسخ سرور طول کشید؛ دوباره تلاش کن.','timeout');
      throw new ApiError('ارتباط با بک‌اند برقرار نشد. Django و React را با python scripts/run.py با هم اجرا کن.','connection_failed');
    }finally{clearTimeout(timer);}
  };
}
export function validateHealth(data,instance=''){
  if(data?.status!=='ok'||data?.backend!=='django'||data?.service!=='torob-yar'||data?.api_version!==3||(instance&&data?.instance_id!==instance))
    throw new ApiError('این آدرس به بک‌اند ترب‌یار نسخه جدید وصل نیست. هر دو بخش React و Django را از بسته جدید اجرا کن.','wrong_backend');
  return data;
}
export function validateChat(data){
  if(typeof data?.reply!=='string'||!Array.isArray(data.products)||!data.preferences||!data.llm)
    throw new ApiError('پاسخ دریافتی، پاسخ معتبر دستیار خرید نیست. آدرس API و نسخه بک‌اند را بررسی کن.','invalid_chat_response');
  return data;
}
