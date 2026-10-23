"""Initialize the writable database once; keep existing data and sessions on restart."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


@contextmanager
def storage_lock(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.bootstrap.lock').open('a+b') as stream:
        if os.name != 'nt':
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name != 'nt':
                fcntl.flock(stream, fcntl.LOCK_UN)


def install_seed(seed, destination):
    seed, destination = Path(seed), Path(destination)
    if not seed.is_file():
        raise RuntimeError('Packaged catalog is missing. Build this project with its Dockerfile.')
    with seed.open('rb') as stream:
        if stream.read(16) != b'SQLite format 3\x00':
            raise RuntimeError('Packaged catalog is not a SQLite database.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return False
    fd, temporary = tempfile.mkstemp(prefix='.catalog-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as target, seed.open('rb') as source:
            shutil.copyfileobj(source, target, length=1024*1024)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def main():
    started = time.monotonic()
    root = Path(os.getenv('APP_ROOT', '/app'))
    seed = Path(os.getenv('TOROB_SEED_PATH', str(root / 'bootstrap/catalog.sqlite3')))
    if os.getenv('DJANGO_DB_READONLY', 'false').lower() == 'true':
        if not seed.is_file() or not seed.with_suffix('.json').is_file():
            raise RuntimeError('Packaged catalog is missing. Rebuild this Docker image.')
        print('Using the packaged read-only catalog; no disk or runtime import is required.', flush=True)
        return
    database = Path(os.getenv('DJANGO_DB_PATH', str(root / 'storage/db.sqlite3')))
    env = {**os.environ, 'DJANGO_DB_PATH': str(database)}
    manage = str(root / 'backend/manage.py')
    with storage_lock(database.parent):
        copied = install_seed(seed, database)
        print('Installed packaged catalog.' if copied else 'Keeping existing database.', flush=True)
        for command in [['migrate', '--noinput'],
                        ['bootstrap_catalog', '--seed', str(seed)]]:
            subprocess.run([sys.executable, manage, *command], cwd=root, env=env, check=True)
    print('Initialization complete in %.1fs; starting Gunicorn.' % (time.monotonic()-started), flush=True)


if __name__ == '__main__':
    main()

