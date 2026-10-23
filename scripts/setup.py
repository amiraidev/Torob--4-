"""One-time portable setup. Run with Python 3.10+ from any working directory."""
import argparse
import os
import shutil
import subprocess
import sys
import venv
import time
import secrets
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
def run(args,cwd=ROOT):
    print('>', subprocess.list2cmdline(list(map(str,args))),flush=True)
    started=time.monotonic()
    child=subprocess.Popen(list(map(str,args)),cwd=cwd,env={**os.environ,'PYTHONUNBUFFERED':'1'})
    try:
        while True:
            try:
                code=child.wait(timeout=20)
                if code:raise subprocess.CalledProcessError(code,args)
                break
            except subprocess.TimeoutExpired:
                print(f'[setup] Still running: {Path(str(args[0])).name}; elapsed {time.monotonic()-started:.0f}s. Import progress appears above.',flush=True)
    except KeyboardInterrupt:
        child.terminate()
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:child.kill();child.wait()
        raise
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dataset',type=Path);parser.add_argument('--sample',action='store_true');parser.add_argument('--skip-import',action='store_true',help='Prepare live search without importing the offline catalog');parser.add_argument('--skip-deps',action='store_true',help='Reuse installed Python/Node dependencies');parser.add_argument('--force-import',action='store_true');args=parser.parse_args()
    if args.skip_import and (args.sample or args.dataset or args.force_import):parser.error('--skip-import cannot be combined with dataset import options')
    if sys.version_info<(3,10):raise SystemExit('Python 3.10+ is required; Python 3.12 is recommended.')
    npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
    if not npm:raise SystemExit('Install Node.js 20.19+ (or Node 22 LTS) including npm, then run setup again.')
    env=ROOT/'.venv'
    python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.exists():print('Creating .venv...',flush=True);venv.EnvBuilder(with_pip=True).create(env)
    if not args.skip_deps:
        run([python,'-m','pip','install','--disable-pip-version-check','-r',ROOT/'requirements.txt'])
        run([npm,'ci' if (ROOT/'package-lock.json').exists() else 'install','--no-fund'])
    elif not (ROOT/'node_modules/vite').exists():raise SystemExit('Node dependencies missing; run setup without --skip-deps.')
    if not (ROOT/'.env').exists():
        template=(ROOT/'.env.example').read_text(encoding='utf-8')
        (ROOT/'.env').write_text(template.replace('DJANGO_SECRET_KEY=\n','DJANGO_SECRET_KEY='+secrets.token_urlsafe(48)+'\n'),encoding='utf-8')
    run([python,'manage.py','migrate','--noinput'],ROOT/'backend')
    candidates=[args.dataset,ROOT/'data/torob-dataset.zip',ROOT/'torob-dataset.zip',ROOT.parent/'torob-dataset.zip']
    source=next((p.resolve() for p in candidates if p and p.exists()),None)
    if args.dataset and not args.dataset.exists():raise SystemExit('Dataset file does not exist: '+str(args.dataset))
    extra=['--force'] if args.force_import else []
    if args.skip_import:print('Offline catalog import skipped. Live Torob search is available; dataset search requires import later.',flush=True)
    elif (ROOT/'data/catalog.jsonl.xz').is_file() and not args.sample and args.dataset is None:
        with tempfile.TemporaryDirectory(prefix='torob-setup-') as directory:
            seed=Path(directory)/'catalog.sqlite3'
            run([python,ROOT/'scripts/build_seed.py','--output',seed])
            run([python,'manage.py','bootstrap_catalog','--seed',seed,*(['--refresh'] if args.force_import else [])],ROOT/'backend')
    elif source and not args.sample:run([python,'-u','manage.py','import_torob',source,*extra],ROOT/'backend')
    else:run([python,'-u','manage.py','import_torob','--sample',*extra],ROOT/'backend')
    print('\nReady. Start both servers with: python scripts/run.py\nBoxAPI URL and model are configured. Replace LLM_API_KEY=PASTE_YOUR_BOXAPI_KEY_HERE in .env with your private key, then restart Django.\n',flush=True)
if __name__=='__main__':
    try:main()
    except subprocess.CalledProcessError as e:raise SystemExit(f'Setup stopped (exit {e.returncode}). Fix the displayed error and run it again; imports are idempotent.')
    except KeyboardInterrupt:raise SystemExit('\nSetup interrupted. Run it again to resume committed import batches.')
