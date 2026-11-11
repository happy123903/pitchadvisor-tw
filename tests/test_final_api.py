import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as main

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def final_client(monkeypatch):
    monkeypatch.setattr(main,'BUNDLE',ROOT/'artifacts/week2')
    monkeypatch.setenv('MODEL_VERSION','week2-sequence-v1')
    monkeypatch.delenv('SUPABASE_URL',raising=False)
    monkeypatch.delenv('SUPABASE_SECRET_KEY',raising=False)
    with TestClient(main.app) as client:
        yield client


def test_final_report_belongs_to_exact_served_bundle(final_client):
    response=final_client.get('/evaluation')
    assert response.status_code==200
    report=response.json()
    health=final_client.get('/health').json()
    assert report['test_evaluated'] is True and health['test_evaluated'] is True
    assert report['frozen_bundle']['sha256']==health['bundle_sha256']
    assert report['frozen_bundle']['model_version']==health['model_version']
    assert report['sample_counts']['usable']==99729
    assert report['sample_counts']['catalog_serving']==69044
    # Preserve the observed final-test decline, rather than implying universal improvement.
    assert report['selected']['pitch']['log_loss']>report['baselines']['pitcher_count_shrunk']['pitch']['log_loss']
    assert report['selected']['pitch']['coverage']<.9


def test_mismatched_final_report_is_not_published(final_client,monkeypatch,tmp_path):
    report=json.loads((ROOT/'docs/week3/final_evaluation_public.json').read_bytes())
    report['frozen_bundle']['sha256']='0'*64
    target=tmp_path/'docs/week3/final_evaluation_public.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(report),encoding='utf-8')
    monkeypatch.setattr(main,'ROOT',tmp_path)
    response=final_client.get('/evaluation')
    assert response.status_code==503
    assert response.json()['detail']['code']=='final_evaluation_not_available'
    assert final_client.get('/health').json()['test_evaluated'] is False


def test_final_report_sanitizes_unlisted_fields(final_client,monkeypatch,tmp_path):
    report=copy.deepcopy(json.loads((ROOT/'docs/week3/final_evaluation_public.json').read_bytes()))
    report['weights']='PRIVATE_SENTINEL'
    report['selected']['pitch']['raw_predictions']='PRIVATE_SENTINEL'
    report['frozen_bundle']['local_path']='PRIVATE_SENTINEL'
    target=tmp_path/'docs/week3/final_evaluation_public.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(report),encoding='utf-8')
    monkeypatch.setattr(main,'ROOT',tmp_path)
    response=final_client.get('/evaluation')
    assert response.status_code==200
    assert 'PRIVATE_SENTINEL' not in response.text


def test_diagnostic_id_is_generated_for_success_and_invalid_requests(final_client):
    successful=final_client.get('/health',headers={'X-Request-ID':'untrusted-incoming-value'})
    invalid=final_client.post('/predict',json={'not':'a valid prediction'})
    assert invalid.status_code==422
    for response in (successful,invalid):
        request_id=response.headers['X-Request-ID']
        assert len(request_id)==32 and int(request_id,16)>0
        assert request_id!='untrusted-incoming-value'
    assert successful.headers['X-Request-ID']!=invalid.headers['X-Request-ID']
