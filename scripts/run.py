"""Launch React and Django together. Probe bind permissions as well as port availability."""
import argparse
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
def available_port(preferred,extra):
    for port in dict.fromkeys([preferred,*extra]):
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:s.bind(('0.0.0.0',port))
            return port
        except OSError:continue
    raise SystemExit('No permitted port found. Try --port 5200 --api-port 8200.')
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=4173);parser.add_argument('--api-port',type=int,default=8000);parser.add_argument('--host',default='127.0.0.1',choices=['127.0.0.1','0.0.0.0']);args=parser.parse_args()
    python=ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.exists() or not (ROOT/'node_modules/vite').exists():raise SystemExit('First run: python scripts/setup.py')
    if not (ROOT/'backend/db.sqlite3').exists():raise SystemExit('Database missing. Run: python scripts/setup.py')
    node=shutil.which('node')
    if not node:raise SystemExit('Node.js 20.19+ is required.')
    port=available_port(args.port,[4175,5173,5175,5200,3000,8088])
    api=available_port(args.api_port,[8001,8010,8100,8200])
    if api==port:api=available_port(8001,[8010,8100,8200])
    env={**os.environ,'VIRTUAL_ENV':str(ROOT/'.venv'),'PORT':str(port),'DJANGO_PORT':str(api),'DJANGO_API_URL':f'http://127.0.0.1:{api}','FRONTEND_HOST':args.host}
    origins=[x.strip() for x in os.getenv('DJANGO_CORS_ORIGINS','').split(',') if x.strip()]
    env['DJANGO_CORS_ORIGINS']=','.join(dict.fromkeys([*origins,f'http://localhost:{port}',f'http://127.0.0.1:{port}']))
    print('Starting Django; the launcher will verify its identity before starting React ...',flush=True)
    child=subprocess.Popen([node,'scripts/dev.mjs'],cwd=ROOT,env=env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0,start_new_session=os.name!='nt')
    try:child.wait()
    except KeyboardInterrupt:
        print('\nStopping...',flush=True)
        if os.name=='nt':subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        else:
            import signal
            try:os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError:pass
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:child.kill()
    raise SystemExit(child.returncode or 0)
if __name__=='__main__':main()
