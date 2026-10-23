"""Runtime secrets for containers; generated keys live outside the image."""

import os
import secrets
import tempfile
from pathlib import Path


def secret_key(debug=False):
    value = os.getenv('DJANGO_SECRET_KEY', '').strip()
    if value:
        return value
    filename = os.getenv('DJANGO_SECRET_KEY_FILE', '').strip()
    if filename:
        try:
            value = Path(filename).read_text(encoding='utf-8').strip()
        except FileNotFoundError:
            value = ''
        except OSError as exc:
            raise RuntimeError('Cannot read DJANGO_SECRET_KEY_FILE; check disk permissions.') from exc
        if value:
            return value
    if debug:
        return 'dev-only-' + secrets.token_hex(32)
    raise RuntimeError(
        'Set DJANGO_SECRET_KEY or initialize DJANGO_SECRET_KEY_FILE with the Docker entrypoint.'
    )


def prepare_secret():
    """Create a strong key once, atomically, without logging its value."""
    if os.getenv('DJANGO_SECRET_KEY', '').strip():
        return 'Using DJANGO_SECRET_KEY from the environment.'
    filename = os.getenv('DJANGO_SECRET_KEY_FILE', '').strip()
    if not filename:
        raise RuntimeError('Set DJANGO_SECRET_KEY or DJANGO_SECRET_KEY_FILE.')
    path = Path(filename)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            # Publish a complete file, so another worker cannot read a half-written key.
            fd, temporary = tempfile.mkstemp(prefix='.django-secret-', dir=path.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    stream.write(secrets.token_urlsafe(64) + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    pass
            finally:
                Path(temporary).unlink(missing_ok=True)
        if not path.read_text(encoding='utf-8').strip():
            raise RuntimeError('DJANGO_SECRET_KEY_FILE is empty; restore its key or set DJANGO_SECRET_KEY.')
    except OSError as exc:
        raise RuntimeError(
            'Cannot initialize the secret file. Mount /app/storage on a writable disk '
            'for container UID 1001, or set DJANGO_SECRET_KEY in Liara variables.'
        ) from exc
    return 'Using the saved Django secret key.'


def main():
    port = os.getenv('PORT', '8000')
    if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise RuntimeError('PORT must be an integer between 1 and 65535.')
    database = os.getenv('DJANGO_DB_PATH', '').strip()
    if database:
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    print(prepare_secret(), flush=True)
    print(f'Preparing Django for 0.0.0.0:{port}.', flush=True)


if __name__ == '__main__':
    main()
