"""Verify final-release HTTP contracts and a bounded four-client demonstration load."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import time
from urllib.parse import urljoin, urlsplit

import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verify_week2 import verify, percentile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url',default='https://pitchadvisor-api.onrender.com')
    parser.add_argument('--frontend-url',default='https://happy123903.github.io/pitchadvisor-tw/')
    parser.add_argument('--output',default='docs/week3/deployment_verification.json')
    args=parser.parse_args()
    report=verify(args.api_url,'week2-sequence-v1',args.frontend_url)
    manifest=json.loads((ROOT/'artifacts/week2/manifest.json').read_bytes())
    base=args.api_url.rstrip('/')
    with httpx.Client(timeout=30,limits=httpx.Limits(max_connections=4,max_keepalive_connections=4)) as client:
        health=client.get(base+'/health').json()
        assert health['bundle_sha256']==manifest['sha256'] and health['test_evaluated'] is True
        response=client.get(base+'/evaluation')
        response.raise_for_status()
        evaluation=response.json()
        assert evaluation['frozen_bundle']['sha256']==manifest['sha256']
        assert evaluation['sample_counts']['usable']==99729 and evaluation['sample_counts']['catalog_serving']==69044
        assert evaluation['selected']['pitch']['coverage']<.9
        assert evaluation['selected']['pitch']['log_loss']>evaluation['baselines']['pitcher_count_shrunk']['pitch']['log_loss']
        demo_response=client.get(urljoin(args.frontend_url,'demo/cases.json'))
        demo_response.raise_for_status()
        demo=demo_response.json()
        assert demo['bundle_sha256']==manifest['sha256'] and len(demo['cases'])==3
        assert demo['evaluation']['sample_counts']['usable']==99729
        assert demo['model_info']['model_info']['test_evaluated'] is True
        request=demo['cases'][1]['request']
        origin=urlsplit(args.frontend_url).scheme+'://'+urlsplit(args.frontend_url).netloc
        denied=client.options(base+'/predict',headers={'Origin':'https://untrusted.example',
            'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'})
        assert denied.status_code==400 and 'access-control-allow-origin' not in denied.headers
        invalid=dict(request,sequence=request['sequence']*9)
        assert client.post(base+'/predict',json=invalid).status_code==422
        def predict(index):
            before=time.perf_counter()
            item=client.post(base+'/predict',json=request,headers={'Origin':origin})
            ms=(time.perf_counter()-before)*1000
            assert item.status_code==200, item.status_code
            body=item.json()
            assert body['model_version']==health['model_version'] and body['source_mode']=='supabase_verified_snapshot'
            assert body['sequence_used'] and body['model_info']['test_evaluated']
            assert item.headers.get('access-control-allow-origin')==origin
            assert all(math.isfinite(p['probability']) for p in body['pitch_probabilities'])
            return {'index':index,'http_ms':round(ms,2),'server_ms':body['elapsed_ms'],'status':item.status_code}
        # Establish each connection before measuring the bounded concurrent batch.
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(predict,range(4)))
            started=time.perf_counter()
            samples=list(pool.map(predict,range(20)))
        load={'concurrent_clients':4,'requests':20,'successes':len(samples),
              'duration_seconds':round(time.perf_counter()-started,3),
              'http_p95_ms':round(percentile([s['http_ms'] for s in samples]),2),
              'server_p95_ms':round(percentile([s['server_ms'] for s in samples]),2),
              'samples':samples,'measurement':'Small demonstration load only; not a production capacity or abuse test.'}
        assert load['http_p95_ms']<3000,load
    report.update(verified_at=datetime.now(timezone.utc).isoformat(),final_evaluation=evaluation,
        concurrent_demo_load=load,checks=dict(report['checks'],frozen_sha_matches=True,final_test_report=True,
            fixed_case_assets=True,untrusted_cors_denied=True,oversized_history_422=True,four_client_demo_load=True))
    target=ROOT/args.output
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'report':args.output,'checks':report['checks'],'warm':report['resource'],'concurrent':load},ensure_ascii=False))


if __name__=='__main__':
    main()
