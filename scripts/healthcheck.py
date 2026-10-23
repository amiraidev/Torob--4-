"""Probe only the app and catalog; provider outages must not restart the container."""
import json
import os
from urllib.request import Request, urlopen

port = int(os.getenv('TOROB_PORT', '8000'))
request = Request('http://127.0.0.1:%s/api/health/' % port,
                  headers={'Host': 'localhost', 'X-Forwarded-Proto': 'https'})
with urlopen(request, timeout=4) as response:
    data = json.load(response)
if data.get('status') != 'ok' or data.get('backend') != 'django' or not data.get('catalog_ready'):
    raise SystemExit(1)

