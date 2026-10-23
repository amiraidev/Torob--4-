"""Read-only public checks; defaults to the configured Liara application."""

import argparse
import json
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='https://torob-yar-v2.liara.run')
    args = parser.parse_args()
    base = args.url.rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        parser.error('--url must be an http(s) URL')
    checks = []
    for path, kind in [('/api/health/', 'health'), ('/', 'frontend')]:
        try:
            with urlopen(base + path, timeout=20) as response:
                content = response.read(2_000_000)
                if kind == 'health':
                    payload = json.loads(content)
                    ok = response.status == 200 and payload.get('service') == 'torob-yar' and payload.get('status') == 'ok'
                    checks.append({'check': kind, 'ok': ok, 'status': response.status,
                                   'llm_configured': payload.get('llm_configured')})
                else:
                    html = content.decode('utf-8')
                    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
                    ok = response.status == 200 and bool(assets)
                    for asset in assets:
                        with urlopen(base + asset, timeout=20) as static:
                            ok = ok and static.status == 200
                    checks.append({'check': kind, 'ok': ok, 'status': response.status, 'assets': len(assets)})
        except HTTPError as exc:
            checks.append({'check': kind, 'ok': False, 'status': exc.code})
        except (OSError, ValueError, URLError) as exc:
            checks.append({'check': kind, 'ok': False, 'error': str(exc)[:300]})
    print(json.dumps({'url': base, 'checks': checks}, ensure_ascii=False, indent=2))
    return 0 if all(check['ok'] for check in checks) else 1


if __name__ == '__main__':
    sys.exit(main())
