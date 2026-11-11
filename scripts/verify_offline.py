"""Verify the real hidden offline server, arbitrary inference and owned-process cleanup."""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import time
import zipfile

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SHA = 'aa3e984758796843bce68aa71fb06a4c84739a7d8048be475cc1bfe6855671ec'


def powershell(arguments, timeout=45):
    # Background venv children can inherit PIPE handles from Windows PowerShell;
    # a regular log file lets this control process return without waiting on EOF.
    log = ROOT / '.cache/offline-verifier-control.log'
    log.parent.mkdir(exist_ok=True)
    with log.open('w', encoding='utf-8') as stream:
        subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', *arguments],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)
    return log.read_text(encoding='utf-8', errors='replace').strip()


def owned_processes(record):
    env = os.environ.copy()
    env['PITCHADVISOR_OFFLINE_TOKEN'] = record['instance_id']
    env['PITCHADVISOR_OFFLINE_SCRIPT'] = str(Path(record['root']) / 'scripts/serve_offline.py')
    command = '''$items=@(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object {
    ([string]$_.CommandLine).IndexOf($env:PITCHADVISOR_OFFLINE_TOKEN,[System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
    ([string]$_.CommandLine).IndexOf($env:PITCHADVISOR_OFFLINE_SCRIPT,[System.StringComparison]::OrdinalIgnoreCase) -ge 0
} | ForEach-Object { @{pid=$_.ProcessId;parent_pid=$_.ParentProcessId;working_set_bytes=[long]$_.WorkingSetSize;creation_date=$_.CreationDate.ToUniversalTime().ToString('o');name=$_.Name} }); ConvertTo-Json -InputObject $items -Compress'''
    output = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command], cwd=ROOT, env=env,
                            text=True, encoding='utf-8', errors='replace', capture_output=True,
                            check=True, timeout=20).stdout.strip()
    return json.loads(output or '[]')


def package_checks():
    path = ROOT / 'deliverables/PitchAdvisor_Offline.zip'
    credentials = dotenv_values(ROOT / '.env') if (ROOT / '.env').exists() else {}
    private_values = [str(credentials[k]).encode('utf-8') for k in
                      ['SUPABASE_URL', 'SUPABASE_SECRET_KEY', 'SUPABASE_SERVICE_ROLE_KEY', 'SUPABASE_ANON_KEY']
                      if credentials.get(k) and len(str(credentials[k])) >= 12]
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read('PitchAdvisor_Offline/OFFLINE_MANIFEST.json'))
        for name, checksum in manifest['files_sha256'].items():
            raw = archive.read('PitchAdvisor_Offline/' + name)
            if hashlib.sha256(raw).hexdigest() != checksum:
                raise AssertionError('Offline archive file checksum mismatch')
            if any(value in raw for value in private_values):
                raise AssertionError('A private cloud value was copied into the archive')
        if any('/.env' in name or '/.venv/' in name or '/data/' in name or '/node_modules/' in name for name in names):
            raise AssertionError('An excluded development file was included in the archive')
        if manifest['bundle_sha256'] != EXPECTED_SHA:
            raise AssertionError('Packaged model differs from the frozen model')
    return {'files': len(names), 'bytes': path.stat().st_size,
            'archive_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'all_file_checksums_match': True, 'private_cloud_values_found': 0,
            'env_venv_raw_data_node_modules_included': False,
            'python_runtime_included': False, 'dependencies_included': False}


def verify_packaged_runtime():
    stage = ROOT / '.cache/offline-bundle/PitchAdvisor_Offline'
    package_record = stage / '.cache/offline-server.json'
    if package_record.exists():
        raise RuntimeError('A packaged offline instance is already owned; stop it first')
    record = None
    try:
        powershell(['-File', str(stage / 'scripts/Start-Offline.ps1'),
                    '-PythonExe', str(ROOT / '.venv/Scripts/python.exe'), '-Port', '8766'])
        record = json.loads(package_record.read_text(encoding='utf-8-sig'))
        with httpx.Client(base_url='http://127.0.0.1:8766', timeout=10) as client:
            assert client.get('/').status_code == 200
            health = client.get('/api/health').json()
            assert health['bundle_sha256'] == EXPECTED_SHA and health['data_source'] == 'local_snapshot'
            cases = client.get('/demo/cases.json').json()
            request = cases['cases'][0]['request']
            request['state']['outs'] = (request['state']['outs'] + 1) % 3
            response = client.post('/api/predict', json=request)
            response.raise_for_status()
            assert response.json()['source_mode'] == 'local_snapshot'
            assert client.get('/api/evaluation').json()['test_evaluated'] is True
    finally:
        if package_record.exists():
            powershell(['-File', str(stage / 'scripts/Stop-Offline.ps1')])
    assert record and not owned_processes(record) and not package_record.exists()
    return {'executed_from_packaged_directory': True, 'provided_existing_python_runtime': True,
            'html_health_arbitrary_inference_and_evaluation_passed': True,
            'owned_packaged_processes_cleaned': True, 'port': 8766}


def main():
    record_file = ROOT / '.cache/offline-server.json'
    if record_file.exists():
        raise RuntimeError('Stop the current owned offline server before running lifecycle verification')
    report = {'verification': 'real loopback HTTP and Windows process lifecycle',
              'generated_at': datetime.now(timezone.utc).isoformat(),
              'network_scope': 'HTTP server checks use loopback; outbound-HTTP blocking is separately tested in tests/test_offline.py',
              'model_sha256': EXPECTED_SHA, 'checks': {}}
    record = None
    try:
        powershell(['-File', str(ROOT / 'scripts/Start-Offline.ps1')])
        record = json.loads(record_file.read_text(encoding='utf-8-sig'))
        base = f'http://127.0.0.1:{record["port"]}'
        with httpx.Client(base_url=base, timeout=10) as client:
            health = client.get('/api/health')
            health.raise_for_status()
            request_id = health.headers.get('x-request-id', '')
            assert re.fullmatch('[0-9a-f]{32}', request_id)
            report['checks']['request_diagnostics'] = {'server_generated_request_id': True}
            health = health.json()
            assert health['status'] == 'ready' and health['data_source'] == 'local_snapshot'
            assert health['bundle_sha256'] == EXPECTED_SHA
            report['checks']['health'] = health
            info = client.get('/offline-info').json()
            assert info['instance_id'] == record['instance_id'] and info['server_pid'] == record['server_pid']
            assert info['cloud_connections_enabled'] is False
            report['actual_server_pid'] = info['server_pid']
            report['launcher_pid'] = record['launcher_pid']
            html = client.get('/')
            html.raise_for_status()
            assets = re.findall(r'(?:src|href)="(\./assets/[^\"]+)"', html.text)
            assert assets
            asset_checks = []
            for asset in assets:
                for reload_index in range(2):
                    response = client.get('/' + asset.removeprefix('./'))
                    response.raise_for_status()
                    assert response.content
                    if asset.endswith('.js'):
                        assert 'https://pitchadvisor-api.onrender.com' not in response.text
                    asset_checks.append({'asset': asset, 'reload': reload_index, 'status': response.status_code})
            report['checks']['compiled_static_reload'] = asset_checks
            cases = client.get('/demo/cases.json').json()
            assert cases['bundle_sha256'] == EXPECTED_SHA and len(cases['cases']) >= 3
            report['checks']['fixed_cases'] = {'n': len(cases['cases']), 'bundle_sha256': cases['bundle_sha256'], 'mode': cases['mode']}
            metadata = client.get('/api/metadata').json()
            people = client.get('/api/players').json()['players']
            model = json.loads((ROOT / 'artifacts/week2/model.json').read_text(encoding='utf-8'))
            assert metadata['calibration']['temperature'] == model['calibration']['temperature']
            assert metadata['calibration']['thresholds'] == model['calibration']['thresholds']
            report['checks']['metadata'] = {'players': len(people), 'model_version': metadata['model_version'],
                                             'calibration_matches_frozen_bundle': True}
            pitchers = [p for p in people if p['role'] == 'pitcher']
            batters = [p for p in people if p['role'] == 'batter']
            request = {'pitcher_id': pitchers[1]['id'], 'batter_id': batters[1]['id'],
                       'state': {'balls': 0, 'strikes': 0, 'outs': 1, 'bases': [True, False, False]}, 'sequence': []}
            assert request not in [case['request'] for case in cases['cases']]
            first = client.post('/api/predict', json=request)
            first.raise_for_status()
            request['state'].update(balls=1, strikes=1)
            request['sequence'] = [{'pitch_type': metadata['pitch_types'][0], 'zone': None, 'velocity': None, 'result': 'ball'},
                                   {'pitch_type': metadata['pitch_types'][1], 'zone': 4, 'velocity': 140., 'result': 'called_strike'}]
            second = client.post('/api/predict', json=request)
            second.raise_for_status()
            prediction = second.json()
            for field in ['pitch_probabilities', 'zone_probabilities', 'result_probabilities']:
                probabilities = [item['probability'] for item in prediction[field]]
                assert all(math.isfinite(value) for value in probabilities)
                assert abs(sum(probabilities) - 1) < 2e-6
            assert prediction['sequence_used'] and prediction['source_mode'] == 'local_snapshot'
            assert first.json()['pitch_probabilities'] != prediction['pitch_probabilities']
            report['checks']['arbitrary_real_inference'] = {'not_a_fixed_case': True, 'sequence_used': True,
                'changed_with_new_input': True, 'probability_sums_valid': True,
                'recommendations': len(prediction['recommendations']), 'source_mode': prediction['source_mode']}
            evaluation = client.get('/api/evaluation').json()
            assert evaluation['frozen_bundle']['sha256'] == EXPECTED_SHA and evaluation['test_evaluated'] is True
            report['checks']['final_evaluation'] = {'same_bundle': True, 'test_evaluated': True,
                'usable_rows': evaluation['sample_counts']['usable']}
        running = owned_processes(record)
        assert any(item['pid'] == record['server_pid'] for item in running)
        report['processes_before_stop'] = running
        report['actual_server_working_set_bytes'] = next(item['working_set_bytes'] for item in running if item['pid'] == record['server_pid'])
        report['package'] = package_checks()
    finally:
        if record_file.exists():
            powershell(['-File', str(ROOT / 'scripts/Stop-Offline.ps1')])
    time.sleep(.3)
    assert record and not owned_processes(record) and not record_file.exists()
    listening = powershell(['-Command', '(@(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)).Count'])
    if int(listening) != 0:
        raise AssertionError('Offline server is still listening after Stop-Offline.ps1')
    report['cleanup'] = {'all_owned_python_processes_stopped': True, 'loopback_port_closed': True, 'ownership_record_removed': True}
    report['package']['runtime_smoke'] = verify_packaged_runtime()
    report['passed'] = True
    output = ROOT / 'docs/week3/offline_verification.json'
    output.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps({'passed': True, 'report': str(output.relative_to(ROOT)),
                      'real_server_working_set_bytes': report['actual_server_working_set_bytes'],
                      'package_sha256': report['package']['archive_sha256']}))


if __name__ == '__main__':
    main()
