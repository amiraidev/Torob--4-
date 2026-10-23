import {spawn,spawnSync} from 'node:child_process';
import {existsSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import net from 'node:net';
import http from 'node:http';
import {randomUUID} from 'node:crypto';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const candidates=process.platform==='win32'?[path.join(root,'.venv/Scripts/python.exe'),process.env.VIRTUAL_ENV&&path.join(process.env.VIRTUAL_ENV,'Scripts/python.exe'),'python']:[path.join(root,'.venv/bin/python'),process.env.VIRTUAL_ENV&&path.join(process.env.VIRTUAL_ENV,'bin/python'),'python3'];
const python=candidates.filter(Boolean).find(p=>!p.includes(path.sep)||existsSync(p));
const children=[];
let stopping=false;
function stop(code=0){if(stopping)return;stopping=true;process.exitCode=code;for(const c of children)c.kill('SIGTERM');setTimeout(()=>{for(const c of children)c.kill('SIGKILL');process.exit(code);},650);}
function start(args,cwd,env,command=process.execPath){const c=spawn(command,args,{cwd,stdio:'inherit',env});children.push(c);c.on('error',e=>{console.error(e.message);stop(1);});c.on('exit',code=>{if(!stopping)stop(code??1);});return c;}
process.on('SIGINT',()=>stop());process.on('SIGTERM',()=>stop());
async function choosePort(preferred,others){for(const port of [...new Set([Number(preferred),...others])]){if(!Number.isInteger(port)||port<1||port>65535)continue;const free=await new Promise(resolve=>{const s=net.createServer();s.once('error',()=>resolve(false));s.listen(port,'0.0.0.0',()=>s.close(()=>resolve(true)));});if(free)return port;}throw Error('No permitted port found. Try python scripts/run.py --port 5200 --api-port 8200');}
function getHealth(port){return new Promise(resolve=>{const req=http.get({hostname:'127.0.0.1',port,path:'/api/health/',timeout:1000},res=>{let data='';res.on('data',part=>{data+=part;if(data.length>10000)req.destroy();});res.on('end',()=>{try{resolve(JSON.parse(data));}catch{resolve(null);}});});req.on('timeout',()=>req.destroy());req.on('error',()=>resolve(null));});}
try{
 if(spawnSync(python,['-c','import django,rest_framework'],{cwd:root,stdio:'ignore'}).status!==0)throw Error('Django dependencies are missing. Run python scripts/setup.py first.');
 const frontPort=await choosePort(process.env.PORT||4173,[4175,5173,5200,3000]);
 const backPort=await choosePort(process.env.DJANGO_PORT||8000,[8001,8010,8100,8200].filter(p=>p!==frontPort));
 if(frontPort===backPort)throw Error('React and Django must use different ports.');
 const instance=randomUUID();
 const origins=[process.env.DJANGO_CORS_ORIGINS,'http://localhost:'+frontPort,'http://127.0.0.1:'+frontPort].filter(Boolean).join(',');
 const localEnv={...process.env,DJANGO_CORS_ORIGINS:origins,DJANGO_API_URL:'http://127.0.0.1:'+backPort,VITE_API_BASE_URL:'',TOROB_INSTANCE_ID:instance,VITE_BACKEND_INSTANCE:instance,PYTHONUNBUFFERED:'1'};
 start(['manage.py','runserver','127.0.0.1:'+backPort,'--noreload'],path.join(root,'backend'),localEnv,python);
 let ready=false;
 for(let attempt=0;attempt<80&&!stopping;attempt++){
  const health=await getHealth(backPort);
  if(health?.service==='torob-yar'&&health.api_version===3&&health.instance_id===instance){ready=true;break;}
  await new Promise(resolve=>setTimeout(resolve,250));
 }
 if(!ready)throw Error('The current Django backend did not become ready. Check its error above; run setup to apply migrations.');
 if(!stopping){
  console.log('\nBackend verified: TorobYar 1.2.0 (this project instance)\nReact: http://localhost:'+frontPort+'\nDjango API: http://127.0.0.1:'+backPort+'/api/health/\nCtrl+C stops both servers.\n');
  start([path.join(root,'node_modules/vite/bin/vite.js'),'--host',process.env.FRONTEND_HOST||'127.0.0.1','--port',String(frontPort),'--strictPort'],root,localEnv);
 }
}catch(error){console.error(error.message);stop(1);}
