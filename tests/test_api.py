import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as server


@pytest.fixture
def client(monkeypatch):
    # Unit/API checks must not contact a live account or depend on local secrets.
    monkeypatch.delenv('SUPABASE_URL',raising=False)
    monkeypatch.delenv('SUPABASE_SECRET_KEY',raising=False)
    monkeypatch.delenv('MODEL_VERSION',raising=False)
    monkeypatch.setattr(server,'BUNDLE',server.ROOT/'artifacts/baseline')
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
    assert server.origins and '*' not in server.origins
    origin=server.origins[0]
    allowed=client.get('/health',headers={'Origin':origin})
    assert allowed.headers['access-control-allow-origin']==origin
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


def test_public_metadata_has_only_summaries_and_explicit_sequence_contract(client):
    data=client.get('/metadata').json()
    assert data['sequence_schema']['max_length']==16
    assert data['sequence_schema']['complete_current_pa'] is True
    assert data['pitch_types']==server.app.state.baseline.model['labels']
    info=client.get('/model-info').json()
    assert 'model_version' in info and 'capabilities' in info
    assert 'pitch_player' not in info
    assert 'sha256' not in info


def test_model_summaries_do_not_publish_internal_payloads(client,monkeypatch):
    request=payload(client)
    hidden='not-a-real-secret-do-not-publish'
    model=server.app.state.baseline.model
    monkeypatch.setitem(model,'capabilities',dict(model['capabilities'],environment=hidden))
    monkeypatch.setitem(model,'model_info',{
        'selected_candidate':'gru','training_rows':12,'test_evaluated':False,
        'validation':{'gru':{'pitch':{'n':12,'log_loss':1.2,'weights':[hidden]},
                             'estimator':{'weights':[hidden]}}},
        'calibration_audit':{'pitch':{'n':3,'coverage':1.0,'internal':hidden}},
        'estimator':{'weights':[hidden]},'environment':hidden,
    })
    monkeypatch.setitem(model,'calibration',{
        'method':'temperature+split-conformal','target_coverage':0.9,
        'temperature':{'pitch':1.1,'zone':float('nan'),'secret':hidden},
        'thresholds':{'pitch':0.8},'audit':{'pitch':{'n':3,'coverage':1.0,'weights':[hidden]}},
        'split':{'audit':{'date_min':'2024-10-01','date_max':'2024-10-31','rows':3,'path':hidden}},
        'raw_predictions':[hidden],
    })
    for response in [client.get('/metadata'),client.get('/model-info'),client.post('/predict',json=request)]:
        assert response.status_code==200,response.text
        assert hidden not in response.text
        assert 'weights' not in response.text and 'raw_predictions' not in response.text
        data=response.json()
        assert data['model_info']['validation']['gru']['pitch']=={'n':12,'log_loss':1.2}
        assert data['calibration']['temperature']=={'pitch':1.1}
        assert data['calibration']['split']['audit']['rows']==3
    assert hidden not in client.get('/health').text


def test_week1_rejects_valid_history_with_explicit_capability_error(client):
    request=payload(client)
    label=client.get('/metadata').json()['pitch_types'][0]
    request['state'].update(balls=1,strikes=0)
    request['sequence']=[history_pitch(label)]
    response=client.post('/predict',json=request)
    assert response.status_code==422
    assert response.json()['detail']['code']=='history_not_supported'


def test_failed_startup_returns_safe_diagnostic_code(tmp_path,monkeypatch):
    (tmp_path/'model.json').write_text('{}',encoding='utf-8')
    (tmp_path/'manifest.json').write_text('{"sha256":"wrong"}',encoding='utf-8')
    monkeypatch.setattr(server,'BUNDLE',tmp_path)
    monkeypatch.delenv('SUPABASE_URL',raising=False)
    monkeypatch.delenv('SUPABASE_SECRET_KEY',raising=False)
    with TestClient(server.app) as client:
        response=client.get('/health')
        assert response.status_code==503
        assert response.json()['detail']['code']=='model_checksum_mismatch'
        assert str(tmp_path) not in response.text


def test_startup_download_exception_never_echoes_url_or_credentials(tmp_path,monkeypatch):
    hidden='not-a-real-secret-do-not-publish'
    def fail_download():
        raise server.httpx.InvalidURL('https://example.invalid/'+hidden)
    monkeypatch.setattr(server,'download_bundle_if_needed',fail_download)
    monkeypatch.setattr(server,'BUNDLE',tmp_path)
    monkeypatch.delenv('SUPABASE_URL',raising=False)
    monkeypatch.delenv('SUPABASE_SECRET_KEY',raising=False)
    with TestClient(server.app) as client:
        response=client.get('/health')
        assert response.status_code==503
        assert response.json()['detail']['code']=='model_bundle_load_failed'
        assert hidden not in response.text
        assert 'example.invalid' not in response.text


@pytest.fixture
def week2_client(monkeypatch):
    path=server.ROOT/'artifacts/week2'
    assert (path/'model.json').exists(),'Build the real week-two model before running its integration checks.'
    monkeypatch.setattr(server,'BUNDLE',path)
    monkeypatch.delenv('SUPABASE_URL',raising=False)
    monkeypatch.delenv('SUPABASE_SECRET_KEY',raising=False)
    monkeypatch.delenv('MODEL_VERSION',raising=False)
    with TestClient(server.app) as client:
        assert client.get('/health').status_code==200
        yield client


def history_pitch(pitch_type,result='ball',zone=None,velocity=None):
    return {'pitch_type':pitch_type,'result':result,'zone':zone,'velocity':velocity}


def test_week2_real_model_uses_history_and_returns_calibration(week2_client):
    client=week2_client
    request=payload(client)
    request['state'].update(balls=1,strikes=1)
    labels=client.get('/metadata').json()['pitch_types']
    empty=client.post('/predict',json=request)
    assert empty.status_code==200,empty.text
    assert empty.json()['sequence_used'] is False
    predictions=[]
    for pitch_type in labels:
        request['sequence']=[history_pitch(pitch_type),history_pitch(pitch_type,'called_strike',4,145)]
        response=client.post('/predict',json=request)
        assert response.status_code==200,response.text
        data=response.json()
        assert data['sequence_used'] is True
        assert data['history_summary']['missing_zone_count']==1
        assert data['capabilities']['sequence'] is True
        assert data['capabilities']['conditional_result'] is True
        assert data['calibration']['method']=='temperature+split-conformal'
        assert set(data['prediction_sets'])=={'pitch','zone','result'}
        assert data['prediction_set']==data['prediction_sets']['pitch']['labels']
        assert data['model_info']['test_evaluated'] is True
        assert data['model_info']['selected_candidate']=='lightgbm_history'
        candidates=data['recommendations']
        assert candidates
        values=[item['expected_run_change'] for item in candidates]
        assert values==sorted(values)
        repertoire=server.app.state.baseline.baseline.model['pitch_player'][request['pitcher_id']]
        assert all(item['pitch_type'] in repertoire and item['causal'] is False for item in candidates)
        for name in ['pitch_probabilities','zone_probabilities','result_probabilities']:
            probabilities=[x['probability'] for x in data[name]]
            # The deployable heads use float32 softmax; its sum can drift by an ULP.
            assert sum(probabilities)==pytest.approx(1,abs=1e-6)
            assert all(0<=probability<=1 for probability in probabilities)
        predictions.append(data['pitch_probabilities'])
    assert any(prediction!=empty.json()['pitch_probabilities'] for prediction in predictions)
    assert any(prediction!=predictions[0] for prediction in predictions[1:])


def test_week2_history_count_terminal_vocabulary_and_strict_masks(week2_client):
    client=week2_client
    request=payload(client)
    label=client.get('/metadata').json()['pitch_types'][0]
    request['sequence']=[history_pitch(label)]
    mismatch=client.post('/predict',json=request)
    assert mismatch.status_code==422
    assert mismatch.json()['detail']['code']=='history_count_mismatch'
    request['state'].update(balls=0,strikes=0)
    for results in [['ball']*4,['called_strike']*3,['in_play']]:
        request['sequence']=[history_pitch(label,result) for result in results]
        response=client.post('/predict',json=request)
        assert response.status_code==422
        assert response.json()['detail']['code']=='history_pa_ended'
    request['state'].update(balls=1,strikes=0)
    request['sequence']=[history_pitch('UNKNOWN')]
    assert client.post('/predict',json=request).json()['detail']['code']=='history_unknown_pitch_type'
    for field,value in [('zone',True),('zone',13),('velocity',True),('velocity',181),('result','other')]:
        request['sequence']=[history_pitch(label)]
        request['sequence'][0][field]=value
        assert client.post('/predict',json=request).status_code==422
    request['sequence']=[history_pitch(label)]*17
    assert client.post('/predict',json=request).status_code==422


def test_cloud_verification_requires_exact_model_hash_and_catalog(client,monkeypatch):
    model=server.app.state.baseline.model
    manifest=server.app.state.manifest
    actual_client=server.httpx.AsyncClient
    row={key:model[key] for key in ['model_version','data_version','data_cutoff']}
    row['sha256']=manifest['sha256']
    catalog=model['players']
    def handler(request):
        return server.httpx.Response(200,json=[row] if request.url.path.endswith('model_versions') else catalog)
    monkeypatch.setattr(server.httpx,'AsyncClient',lambda **kwargs:actual_client(transport=server.httpx.MockTransport(handler),**kwargs))
    monkeypatch.setenv('SUPABASE_URL','https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SECRET_KEY','sb_secret_test_only')
    with TestClient(server.app) as verified:
        assert verified.get('/health').json()['data_source']=='supabase_verified_snapshot'
    row['sha256']='0'*64
    with TestClient(server.app) as mismatch:
        data=mismatch.get('/health').json()
        assert data['status']=='ready'
        assert data['data_source']=='local_snapshot_supabase_mismatch'
        assert data['data_source_error']=='supabase_model_mismatch'
    row['sha256']=manifest['sha256']
    catalog=[dict(player) for player in catalog]
    catalog[0]['id']='different-catalog-id'
    with TestClient(server.app) as mismatch:
        data=mismatch.get('/health').json()
        assert data['status']=='ready'
        assert data['data_source']=='local_snapshot_supabase_mismatch'
        assert data['data_source_error']=='supabase_catalog_mismatch'
    catalog=[dict(player) for player in model['players']]
    catalog[0]['sample_count']+=1
    with TestClient(server.app) as mismatch:
        data=mismatch.get('/health').json()
        assert data['data_source']=='local_snapshot_supabase_mismatch'
        assert data['data_source_error']=='supabase_catalog_mismatch'
