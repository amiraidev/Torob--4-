"""Prepare the full catalog during image build, without reading private credentials."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import shutil
import tempfile
from catalog_bundle import inspect_catalog


def main():
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=root / 'bootstrap/catalog.sqlite3')
    parser.add_argument('--sample', action='store_true', help='Only for fast development verification.')
    parser.add_argument('--dataset', type=Path, help='Import a new original CSV/ZIP instead of the packaged snapshot.')
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='torob-seed-') as directory:
        build(root, Path(directory) / 'catalog.sqlite3', output, args.sample, args.dataset)


def build(root, database, output, sample=False, dataset=None):
    # DEBUG=False keeps hundreds of thousands of SQL strings out of Django's query log.
    env = {**os.environ, 'TOROB_IN_DOCKER': 'true', 'TOROB_BUILDING_IMAGE': 'true', 'DJANGO_DEBUG': 'false',
           'DJANGO_DB_PATH': str(database), 'DJANGO_SECRET_KEY': 'disposable-build-only-key',
           'DJANGO_DB_READONLY': 'false', 'LLM_ENABLED': 'false'}
    python = sys.executable
    manage = str(root / 'backend/manage.py')
    bundle = root / 'data/catalog.jsonl.xz'
    bundled = not sample and dataset is None and bundle.is_file()
    subprocess.run([python, manage, 'migrate', '--noinput'], cwd=root, env=env, check=True)
    if bundled:
        print('Loading the compact full catalog (no CSV parsing required) ...', flush=True)
        subprocess.run([python, '-u', manage, 'import_catalog_bundle', str(bundle)], cwd=root, env=env, check=True)
    else:
        command = [python, '-u', manage, 'import_torob']
        command += ['--sample'] if sample else [str(dataset or root / 'data/torob-dataset.zip')]
        subprocess.run(command, cwd=root, env=env, check=True)
    with sqlite3.connect(database) as connection:
        # Reclaim import/index free pages and give the query planner real statistics.
        connection.execute('VACUUM')
        connection.execute('ANALYZE')
    connection.close()
    manifest = inspect_catalog(database)
    manifest['catalog_kind'] = 'sample' if sample else 'full'
    # Publish only a closed, fully validated database, never a partial SQLite file.
    fd, temporary = tempfile.mkstemp(prefix='.seed-', dir=output.parent)
    try:
        with os.fdopen(fd, 'wb') as target, database.open('rb') as source:
            shutil.copyfileobj(source, target, length=1024*1024)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    output.with_suffix('.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    print('Packaged catalog ready: '+json.dumps(manifest['counts']), flush=True)


if __name__ == '__main__':
    main()

