"""Bounded public cold-start observation; never redeploy to manufacture a pass."""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='https://pitchadvisor-api.onrender.com')
    parser.add_argument('--budget', type=float, default=180)
    parser.add_argument('--output', default='docs/week3/cold_start.json')
    args = parser.parse_args()
    started = time.perf_counter()
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'url': args.url,
              'budget_seconds': args.budget, 'attempts': [], 'ready': False,
              'measurement': 'First external request after observed overnight shutdown; bounded retries, no deployment/restart.'}
    with httpx.Client(timeout=25) as client:
        while time.perf_counter() - started < args.budget:
            before = time.perf_counter()
            attempt = {'offset_seconds': round(before - started, 3)}
            try:
                response = client.get(args.url.rstrip('/') + '/health', timeout=min(25, max(1, args.budget - (before - started))))
                attempt['status'] = response.status_code
                if response.status_code == 200:
                    health = response.json()
                    if health.get('status') == 'ready' and health.get('model_version') == 'week2-sequence-v1':
                        report['ready'] = True
                        report['health'] = health
            except httpx.TimeoutException:
                attempt['error'] = 'timeout'
            except (httpx.HTTPError, ValueError):
                attempt['error'] = 'network_or_response_error'
            attempt['duration_seconds'] = round(time.perf_counter() - before, 3)
            report['attempts'].append(attempt)
            print(json.dumps(attempt), flush=True)
            if report['ready']:
                break
            time.sleep(min(5, max(0, args.budget - (time.perf_counter() - started))))
    report['elapsed_seconds'] = round(time.perf_counter() - started, 3)
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    target = ROOT / args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'ready': report['ready'], 'elapsed_seconds': report['elapsed_seconds'], 'report': args.output}), flush=True)


if __name__ == '__main__':
    main()
