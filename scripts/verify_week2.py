"""Exercise a real week-two HTTP service; keep local and cloud timings distinct."""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import re
import signal
import socket
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def percentile(values, fraction=.95):
    return sorted(values)[math.ceil(len(values) * fraction) - 1]


def process_memory(pid):
    if os.name != 'nt':
        return None
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ['PeakWorkingSetSize', 'WorkingSetSize',
             'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
             'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage']]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
    if not handle:
        raise OSError('Unable to read owned verification process memory')
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            raise OSError('Unable to measure verification process memory')
        return {'rss_bytes': counters.WorkingSetSize, 'peak_rss_bytes': counters.PeakWorkingSetSize,
                'measurement': 'Windows process working set, independent uvicorn process'}
    finally:
        kernel.CloseHandle(handle)


def verify(base, expected_version, frontend=None, pid=None):
    base = base.rstrip('/')
    checks = {}
    with httpx.Client(timeout=55, follow_redirects=True) as client:
        health_response = client.get(base + '/health')
        health_response.raise_for_status()
        health = health_response.json()
        assert health['status'] == 'ready' and health['model_version'] == expected_version, health
        if not pid:
            assert health['data_source'] == 'supabase_verified_snapshot', health
        assert all(health['capabilities'][k] for k in ['sequence', 'conditional_result', 'conformal'])
        checks['health'] = True
        people_response = client.get(base + '/players')
        people_response.raise_for_status()
        people = people_response.json()['players']
        pitcher = next(p for p in people if p['role'] == 'pitcher')
        batters = [p for p in people if p['role'] == 'batter']
        info_response = client.get(base + '/model-info')
        info_response.raise_for_status()
        info = info_response.json()
        assert info['model_info']['test_evaluated'] is False
        assert not any(token in info_response.text for token in ['sb_secret_', 'Tree=', 'weight_ih_l0', 'SUPABASE_SECRET_KEY'])
        metadata = client.get(base + '/metadata')
        metadata.raise_for_status()
        labels = metadata.json()['pitch_types']
        payload = {'pitcher_id': pitcher['id'], 'batter_id': batters[0]['id'],
                   'state': {'balls': 1, 'strikes': 0, 'outs': 0, 'bases': [False] * 3}, 'sequence': []}
        empty_response = client.post(base + '/predict', json=payload)
        empty_response.raise_for_status()
        empty = empty_response.json()
        seq = [{'pitch_type': labels[0], 'zone': 0, 'velocity': 140., 'result': 'ball'}]
        with_history = dict(payload, sequence=seq)
        history_response = client.post(base + '/predict', json=with_history)
        history_response.raise_for_status()
        prediction = history_response.json()
        assert prediction['sequence_used'] is True and empty['sequence_used'] is False
        change = max(abs(a['probability'] - b['probability']) for a, b in
                     zip(empty['pitch_probabilities'], prediction['pitch_probabilities']))
        assert change > 1e-8, 'History did not change pitch probabilities'
        for task, key in [('pitch', 'pitch_probabilities'), ('zone', 'zone_probabilities'), ('result', 'result_probabilities')]:
            assert all(math.isfinite(p['probability']) and 0 <= p['probability'] <= 1 for p in prediction[key])
            assert abs(sum(p['probability'] for p in prediction[key]) - 1.) < 1e-5
            assert prediction['prediction_sets'][task]['target_coverage'] == .9
        assert len(prediction['recommendations']) > 0
        values = [candidate['expected_run_change'] for candidate in prediction['recommendations']]
        assert values == sorted(values) and all(math.isfinite(v) for v in values)
        for candidate in prediction['recommendations']:
            assert candidate['causal'] is False and candidate['pooled_sample_count'] >= 10
            assert abs(sum(p['probability'] for p in candidate['result_probabilities']) - 1.) < 1e-5
        other = client.post(base + '/predict', json=dict(with_history, batter_id=batters[-1]['id']))
        other.raise_for_status()
        batter_change = max(abs(a['probability'] - b['probability']) for a, b in
                            zip(prediction['pitch_probabilities'], other.json()['pitch_probabilities']))
        assert batter_change > 1e-8, 'Batter did not change pitch probabilities'
        invalid = dict(with_history, state=dict(payload['state'], balls=2))
        assert client.post(base + '/predict', json=invalid).status_code == 422
        terminal = dict(payload, sequence=[dict(seq[0], result='in_play')])
        assert client.post(base + '/predict', json=terminal).status_code == 422
        unknown = dict(payload, pitcher_id='not-a-player')
        assert client.post(base + '/predict', json=unknown).status_code == 404
        checks.update({'public_metadata': True, 'normalized_three_tasks': True, 'history_changes_prediction': True,
                       'batter_changes_prediction': True, 'conditional_recommendations': True,
                       'conformal_sets': True, 'invalid_history_422': True, 'terminal_history_422': True,
                       'unknown_player_404': True})
        durations, server = [], []
        for _ in range(25):
            before = time.perf_counter()
            response = client.post(base + '/predict', json=with_history)
            elapsed = (time.perf_counter() - before) * 1000
            response.raise_for_status()
            durations.append(elapsed)
            server.append(response.json()['elapsed_ms'])
        if frontend:
            page = client.get(frontend)
            page.raise_for_status()
            scripts = re.findall(r'<script[^>]+src="([^"]+)"', page.text)
            assert scripts, 'Frontend module missing'
            from urllib.parse import urljoin
            assets = [client.get(urljoin(frontend, path)) for path in scripts]
            assert all(r.status_code == 200 for r in assets)
            assert any(base in asset.text for asset in assets), 'Pages API URL does not match'
            assert any('本打席已投球歷程' in asset.text and '/model-info' in asset.text for asset in assets), 'Pages week-two UI has not been published'
            origin = frontend.split('/pitchadvisor-tw')[0].rstrip('/')
            cors = client.options(base + '/predict', headers={'Origin': origin,
                'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type'})
            assert cors.status_code == 200 and cors.headers.get('access-control-allow-origin') == origin
            cors_post = client.post(base + '/predict', json=with_history, headers={'Origin': origin})
            cors_post.raise_for_status()
            assert cors_post.headers.get('access-control-allow-origin') == origin
            checks.update({'frontend_html_and_assets': True, 'frontend_correct_api': True, 'cors': True})
    memory = process_memory(pid) if pid else None
    resource = {'samples': len(durations), 'http_median_ms': round(statistics.median(durations), 2),
                'http_p95_ms': round(percentile(durations), 2), 'server_p95_ms': round(percentile(server), 2),
                'measurement': 'Sequential warmed POST /predict, complete history and supported candidate scoring; no concurrent load.',
                'memory': memory}
    if pid:
        resource['gate_passed'] = percentile(durations) < 500 and memory['peak_rss_bytes'] < 400 * 1024**2
        assert resource['gate_passed'], resource
    return {'verified_at': datetime.now(timezone.utc).isoformat(), 'api_url': base,
            'frontend_url': frontend, 'health': health, 'checks': checks, 'resource': resource,
            'history_max_probability_change': change, 'batter_max_probability_change': batter_change,
            'model_info': info, 'browser_visual_qa': 'separate_browser_report_required'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url')
    parser.add_argument('--frontend-url')
    parser.add_argument('--bundle-dir', default='artifacts/week2')
    parser.add_argument('--expected-version', default='week2-sequence-v1')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    process = None
    serving_pid = None
    pid_file = None
    try:
        if args.api_url:
            report = verify(args.api_url, args.expected_version, args.frontend_url)
        else:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            env = dict(os.environ, MODEL_BUNDLE_DIR=str(ROOT / args.bundle_dir), MODEL_VERSION=args.expected_version,
                       SUPABASE_URL='', SUPABASE_SECRET_KEY='')
            (ROOT / '.cache').mkdir(exist_ok=True)
            pid_file = ROOT / f'.cache/week2-verification-{port}.pid'
            with (ROOT / '.cache/week2-verification.log').open('w', encoding='utf-8') as log:
                # Windows venv python.exe may be a tiny launcher. The real server
                # writes its own PID, so both measurement and cleanup target it.
                runner = ('import os,uvicorn; from pathlib import Path; '
                          f'Path({str(pid_file)!r}).write_text(str(os.getpid())); '
                          f"uvicorn.run('api.main:app',host='127.0.0.1',port={port},workers=1)")
                process = subprocess.Popen([sys.executable, '-c', runner], cwd=ROOT, env=env, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                base = f'http://127.0.0.1:{port}'
                for attempt in range(100):
                    if process.poll() is not None:
                        raise RuntimeError('Verification server exited; see .cache/week2-verification.log')
                    try:
                        if httpx.get(base + '/health', timeout=2).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.2)
                serving_pid = int(pid_file.read_text())
                report = verify(base, args.expected_version, pid=serving_pid)
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'report': args.output, 'checks': report['checks'], 'resource': report['resource']}, ensure_ascii=False))
    finally:
        if serving_pid is None and pid_file and pid_file.exists():
            serving_pid = int(pid_file.read_text())
        if serving_pid and process and serving_pid != process.pid:
            try:
                os.kill(serving_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        if pid_file and pid_file.exists():
            pid_file.unlink()


if __name__ == '__main__':
    main()
