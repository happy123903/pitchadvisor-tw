"""Check actual HTTP API, Vite proxy and response timing without browser automation."""
import json
import math
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')


def main():
    with httpx.Client(timeout=15) as client:
        for attempt in range(20):
            try:
                health=client.get('http://127.0.0.1:8000/health')
                if health.status_code==200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.5)
        health.raise_for_status()
        people=client.get('http://127.0.0.1:8000/players').json()['players']
        payload={'pitcher_id':next(p['id'] for p in people if p['role']=='pitcher'),
                 'batter_id':next(p['id'] for p in people if p['role']=='batter'),
                 'state':{'balls':1,'strikes':2,'outs':0,'bases':[False,False,False]},'sequence':[]}
        durations=[]
        for _ in range(21):
            before=time.perf_counter()
            response=client.post('http://127.0.0.1:8000/predict',json=payload)
            durations.append((time.perf_counter()-before)*1000)
            response.raise_for_status()
        proxy=client.post('http://127.0.0.1:5173/api/predict',json=payload)
        proxy.raise_for_status()
        assert proxy.json()['model_version']==health.json()['model_version']
        page=client.get('http://127.0.0.1:5173/')
        page.raise_for_status()
        assert 'root' in page.text
        invalid={**payload,'state':{**payload['state'],'balls':4}}
        assert client.post('http://127.0.0.1:8000/predict',json=invalid).status_code==422
        durations=durations[1:]
        report={'api_health':health.json(),'frontend_http':page.status_code,'vite_proxy_http':proxy.status_code,
                'warm_requests':len(durations),'warm_median_ms':round(statistics.median(durations),2),
                'warm_p95_ms':round(sorted(durations)[math.ceil(.95*len(durations))-1],2),
                'measurement':'local Windows HTTP round-trip; single client; excludes cloud cold start',
                'browser_visual_qa':'not_run_browser_host_unavailable',
                'cloud_deployment':'pending_accounts_and_repository'}
        (ROOT/'docs/week1/system_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
