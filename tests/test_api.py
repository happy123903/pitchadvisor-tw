import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as server


@pytest.fixture
def client():
    with TestClient(server.app) as client:
        yield client


def payload(client):
    people=client.get('/players').json()['players']
    return {'pitcher_id':next(x['id'] for x in people if x['role']=='pitcher'),
            'batter_id':next(x['id'] for x in people if x['role']=='batter'),
            'state':{'balls':1,'strikes':2,'outs':1,'bases':[True,False,False]},'sequence':[]}


def test_real_model_probabilities_recommendations_and_versions(client):
    request=payload(client)
    response=client.post('/predict',json=request)
    assert response.status_code==200,response.text
    data=response.json()
    for name in ['pitch_probabilities','zone_probabilities','result_probabilities']:
        probabilities=[x['probability'] for x in data[name]]
        assert sum(probabilities)==pytest.approx(1,abs=1e-8)
        assert all(0<=p<=1 for p in probabilities)
    assert len(data['zone_probabilities'])==13
    values=[x['expected_run_change'] for x in data['recommendations']]
    assert values==sorted(values)
    repertoire=server.app.state.baseline.model['pitch_player'][request['pitcher_id']]
    assert all(x['pitch_type'] in repertoire for x in data['recommendations'])
    assert data['data_cutoff']<'2025-01-01'
    assert data['capabilities']['sequence'] is False
    assert data['prediction_set'] is None


def test_invalid_state_unknown_player_sequence_and_unready(client,monkeypatch):
    request=payload(client)
    request['state']['strikes']=3
    assert client.post('/predict',json=request).status_code==422
    request['state']['strikes']=2
    request['state']['bases']=[1,0,0]
    assert client.post('/predict',json=request).status_code==422
    request=payload(client)
    request['sequence']=[{'pitch_code':'S'}]
    assert client.post('/predict',json=request).status_code==422
    request=payload(client);request['pitcher_id']='nonexistent'
    assert client.post('/predict',json=request).status_code==404
    monkeypatch.setattr(server.app.state,'baseline',None)
    assert client.get('/health').status_code==503
    assert client.post('/predict',json=payload_saved(client)).status_code==503


def payload_saved(client):
    return {'pitcher_id':'p','batter_id':'b','state':{'balls':0,'strikes':0,'outs':0,'bases':[False,False,False]},'sequence':[]}


def test_cors_is_explicit(client):
    allowed=client.get('/health',headers={'Origin':'http://127.0.0.1:5173'})
    assert allowed.headers['access-control-allow-origin']=='http://127.0.0.1:5173'
    denied=client.get('/health',headers={'Origin':'https://untrusted.example'})
    assert 'access-control-allow-origin' not in denied.headers


def test_bundle_integrity_rejects_changed_file(tmp_path,monkeypatch):
    (tmp_path/'manifest.json').write_text(json.dumps({'sha256':'0'*64}),encoding='utf-8')
    (tmp_path/'model.json').write_text('{}',encoding='utf-8')
    monkeypatch.setattr(server,'BUNDLE',tmp_path)
    with pytest.raises(ValueError,match='checksum'):
        server.load_bundle()


def test_changing_ball_count_recomputes_prediction(client):
    request=payload(client)
    first=client.post('/predict',json=request).json()
    request['state']['balls']=3
    second=client.post('/predict',json=request).json()
    assert first['pitch_probabilities']!=second['pitch_probabilities']
