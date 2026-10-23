"""Give the mounted disk to the app, then permanently drop root privileges."""

import os
from pathlib import Path


def is_mounted(path):
    path = str(Path(path).resolve())
    if os.path.ismount(path):
        return True
    try:
        for line in Path('/proc/self/mountinfo').read_text().splitlines():
            fields = line.split()
            if len(fields) > 4 and fields[4].replace('\\040', ' ') == path:
                return True
    except OSError:
        pass
    return False


def configure_environment(root):
    """Use this package's production profile even with old development panel values."""
    storage = Path(os.getenv('TOROB_STORAGE_DIR', str(root / 'storage'))).resolve()
    mode = os.getenv('TOROB_DATA_MODE', 'auto').lower()
    if mode not in {'auto', 'persistent', 'readonly'}:
        raise RuntimeError('TOROB_DATA_MODE must be auto, persistent, or readonly.')
    persistent = mode == 'persistent' or (mode == 'auto' and is_mounted(storage))
    state = storage if persistent else Path(os.getenv('TOROB_TEMP_DIR', '/tmp/torob-yar'))
    database = storage / 'db.sqlite3' if persistent else root / 'bootstrap/catalog.sqlite3'
    os.environ.update(TOROB_IN_DOCKER='true', DJANGO_DEBUG='false',
        PORT=os.getenv('TOROB_PORT', '8000'), DJANGO_DB_PATH=str(database),
        DJANGO_DB_READONLY='false' if persistent else 'true',
        DJANGO_SECRET_KEY_FILE=str(state / 'django-secret-key'))
    known_hosts = ['torob-yar-v2.liara.run', 'torob-yar.liara.run', 'localhost', '127.0.0.1', '[::1]']
    origins = ['https://torob-yar-v2.liara.run', 'https://torob-yar.liara.run']
    for name, defaults in [('DJANGO_ALLOWED_HOSTS', known_hosts), ('DJANGO_CORS_ORIGINS', origins),
                           ('DJANGO_CSRF_TRUSTED_ORIGINS', origins)]:
        supplied = [s.strip() for s in os.getenv(name, '').split(',') if s.strip() and s.strip() != '*']
        os.environ[name] = ','.join(dict.fromkeys([*defaults, *supplied]))
    return state


def prepare_storage(storage, uid=1001, gid=1001):
    storage = Path(storage).resolve()
    storage.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        # Only touch the storage directory and this application's state files.
        # Existing datasets/uploads are not recursively chowned.
        os.chown(storage, uid, gid, follow_symlinks=False)
        candidates = [
            os.getenv('DJANGO_SECRET_KEY_FILE', str(storage / 'django-secret-key')),
            os.getenv('DJANGO_DB_PATH', str(storage / 'db.sqlite3')),
            str(storage / '.bootstrap.lock'),
        ]
        for filename in candidates:
            if not filename:
                continue
            path = Path(filename).resolve()
            if not path.is_relative_to(storage):
                continue
            for candidate in [path, Path(str(path) + '-wal'), Path(str(path) + '-shm'), Path(str(path) + '-journal')]:
                if candidate.exists():
                    os.chown(candidate, uid, gid, follow_symlinks=False)


def drop_privileges(uid=1001, gid=1001):
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)


def main():
    root = Path(os.getenv('APP_ROOT', '/app'))
    prepare_storage(configure_environment(root))
    drop_privileges()
    os.execv('/bin/sh', ['sh', str(root / 'scripts' / 'docker-entrypoint.sh')])


if __name__ == '__main__':
    main()
