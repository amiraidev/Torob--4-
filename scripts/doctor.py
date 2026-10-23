"""Read-only connection diagnostics. Does not read or print API keys."""
import argparse
import json
import urllib.request
import urllib.error
import sys

def check(url,origin,body=None):
    headers={'Origin':origin,'Accept':'application/json'}
    if body is not None:headers['Content-Type']='application/json'
    req=urllib.request.Request(url,data=json.dumps(body).encode() if body is not None else None,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=40) as response:
            status=response.status;raw=response.read(1_000_000)
            try:data=json.loads(raw)
            except (ValueError,UnicodeError):return status,{'issue':'not_json_api'}
            return status,data
    except urllib.error.HTTPError as error:
        try:data=json.loads(error.read(10000))
        except (ValueError,UnicodeError):data={'issue':'http_error'}
        return error.code,{'issue':data.get('code') or data.get('error') or data.get('detail') or 'request_rejected'}
    except (urllib.error.URLError,TimeoutError,OSError):return 0,{'issue':'connection_failed'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=4173);p.add_argument('--api-port',type=int,default=8000);p.add_argument('--live',action='store_true');args=p.parse_args()
    origin=f'http://localhost:{args.port}';proxy=origin+'/api/';direct=f'http://127.0.0.1:{args.api_port}/api/'
    passed=True
    for name,base in [('DJANGO',direct),('REACT_PROXY',proxy)]:
        status,data=check(base+'health/',origin)
        valid=status==200 and data.get('service')=='torob-yar' and data.get('backend')=='django' and data.get('api_version')==3
        passed=passed and valid
        print(name,'HTTP',status,'BACKEND_OK',valid,'SERVICE',data.get('service','unknown'),'ISSUE',data.get('issue','none'))
        if valid:
            code,result=check(base+'chat/',origin,{'message':''})
            print(name,'CHAT_POST_HTTP',code,'CHAT_VALID',isinstance(result.get('reply'),str),'ISSUE',result.get('issue','none'))
            passed=passed and code==200 and isinstance(result.get('reply'),str)
    if args.live:
        status,data=check(proxy+'live-search/?q=Samsung%20A55',origin)
        print('TOROB_VIA_DJANGO','HTTP',status,'PRODUCTS',len(data.get('products',[])),'ISSUE',data.get('issue','none'))
        passed=passed and status==200 and isinstance(data.get('products'),list)
    if passed:print('ALL REQUESTED CONNECTION CHECKS PASSED')
    else:
        print('Start the current package with: python scripts/run.py')
        print('Use --port and --api-port with the actual ports printed by the launcher.')
    return 0 if passed else 1
if __name__=='__main__':sys.exit(main())
