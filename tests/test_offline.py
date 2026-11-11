"""Real mounted API inference remains usable when outbound HTTP is forbidden."""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from scripts.serve_offline import FROZEN_SHA256, create_offline_app


@pytest.fixture(autouse=True)
def isolate_offline_environment(monkeypatch):
    for name in ['SUPABASE_URL', 'SUPABASE_SECRET_KEY', 'PYTHON_DOTENV_DISABLED',
                 'MODEL_VERSION', 'MODEL_BUNDLE_DIR']:
        if name in os.environ:
            monkeypatch.setenv(name, os.environ[name])
        else:
            monkeypatch.delenv(name, raising=False)


def test_full_offline_application_with_outbound_http_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://must-not-be-contacted.invalid')
    monkeypatch.setenv('SUPABASE_SECRET_KEY', 'test-only-placeholder')
    monkeypatch.setenv('PYTHON_DOTENV_DISABLED', '0')
    monkeypatch.setenv('MODEL_VERSION', 'intentionally-wrong-before-offline-configuration')
    monkeypatch.setenv('MODEL_BUNDLE_DIR', 'intentionally-wrong-before-offline-configuration')
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'index.html').write_text('<!doctype html><script src="./assets/local.js"></script>', encoding='utf-8')
    (tmp_path / 'assets/local.js').write_text('window.localAssetLoaded=true;', encoding='utf-8')
    calls = []
    original_send = httpx.Client.send
    def only_in_process(client, request, *args, **kwargs):
        if request.url.host != 'testserver':
            calls.append(str(request.url))
            raise AssertionError('Offline mode attempted an outbound request')
        return original_send(client, request, *args, **kwargs)
    async def no_async_http(*args, **kwargs):
        calls.append('async outbound HTTP')
        raise AssertionError('Offline mode attempted an outbound request')
    monkeypatch.setattr(httpx.Client, 'send', only_in_process)
    monkeypatch.setattr(httpx.AsyncClient, 'send', no_async_http)
    app = create_offline_app(tmp_path, instance_id='offline-test-instance')
    with TestClient(app) as client:
        # Explicit lifespan entry is required: a mounted child otherwise stays unready.
        health = client.get('/api/health')
        assert health.status_code == 200
        assert health.json()['status'] == 'ready'
        assert health.json()['data_source'] == 'local_snapshot'
        assert health.json()['bundle_sha256'] == FROZEN_SHA256
        assert client.get('/offline-info').json()['cloud_connections_enabled'] is False
        for _reload in range(2):
            assert 'assets/local.js' in client.get('/').text
            assert client.get('/assets/local.js').text == 'window.localAssetLoaded=true;'
        people = client.get('/api/players').json()['players']
        pid = next(p['id'] for p in people if p['role'] == 'pitcher')
        bid = next(p['id'] for p in people if p['role'] == 'batter')
        request = {'pitcher_id': pid, 'batter_id': bid,
                   'state': {'balls': 0, 'strikes': 0, 'outs': 0, 'bases': [False] * 3}, 'sequence': []}
        first = client.post('/api/predict', json=request)
        assert first.status_code == 200
        assert first.json()['source_mode'] == 'local_snapshot'
        assert first.json()['model_version'] == 'week2-sequence-v1'
        labels = client.get('/api/metadata').json()['pitch_types']
        request['state']['balls'] = 1
        request['sequence'] = [{'pitch_type': labels[0], 'zone': None, 'velocity': None, 'result': 'ball'}]
        second = client.post('/api/predict', json=request)
        assert second.status_code == 200 and second.json()['sequence_used'] is True
        assert first.json()['pitch_probabilities'] != second.json()['pitch_probabilities']
        assert second.json()['recommendations']
        report = client.get('/api/evaluation')
        assert report.status_code == 200 and report.json()['test_evaluated'] is True
        assert report.json()['frozen_bundle']['sha256'] == FROZEN_SHA256
    assert calls == []


def test_offline_static_bundle_must_exist(tmp_path):
    with pytest.raises(ValueError, match='Compiled offline UI missing'):
        create_offline_app(tmp_path)


def test_delivered_package_manifest_excludes_runtime_and_credentials():
    import zipfile
    path = Path(__file__).resolve().parents[1] / 'deliverables/PitchAdvisor_Offline.zip'
    if not path.exists():
        pytest.skip('Offline release package has not been built')
    import hashlib
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert all('/.env' not in n and '/.venv/' not in n and '/data/raw/' not in n and 'node_modules' not in n for n in names)
        manifest = json.loads(archive.read('PitchAdvisor_Offline/OFFLINE_MANIFEST.json'))
        assert manifest['bundle_sha256'] == FROZEN_SHA256
        assert manifest['dependencies_included'] is False
        for name, expected in manifest['files_sha256'].items():
            assert hashlib.sha256(archive.read('PitchAdvisor_Offline/' + name)).hexdigest() == expected
        assert hashlib.sha256(archive.read('PitchAdvisor_Offline/artifacts/week2/model.json')).hexdigest() == FROZEN_SHA256
