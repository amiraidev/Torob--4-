import {createClient,validateHealth,validateChat} from './transport.mjs';
const BASE=(import.meta.env.VITE_API_BASE_URL||'').trim();
export const IS_STATIC_PREVIEW=!BASE&&typeof window!=='undefined'&&window.location.hostname.endsWith('.chatgpt.site');
export const request=createClient(BASE);
export const health=()=>request('health/',{timeout:10000}).then(data=>validateHealth(data,import.meta.env.VITE_BACKEND_INSTANCE||''));
export const chat=body=>request('agent/chat/',{method:'POST',body:JSON.stringify(body)}).then(validateChat);
