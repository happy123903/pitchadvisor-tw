from __future__ import annotations

import hashlib
import json
import math
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from src.baseline import Baseline
from src.sequence import MAX_SEQUENCE_LENGTH, SEQUENCE_RESULTS, SequenceValidationError, validate_sequence

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
BUNDLE=Path(os.environ.get('MODEL_BUNDLE_DIR',str(ROOT/'artifacts/baseline')))


class State(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    balls: int=Field(ge=0,le=3)
    strikes: int=Field(ge=0,le=2)
    outs: int=Field(ge=0,le=2)
    bases: list[bool]=Field(min_length=3,max_length=3)


class PredictionRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    pitcher_id: str=Field(min_length=1,max_length=80)
    batter_id: str=Field(min_length=1,max_length=80)
    state: State
    sequence: list['HistoryPitch']=Field(default_factory=list,max_length=MAX_SEQUENCE_LENGTH)


class HistoryPitch(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    pitch_type: str=Field(min_length=1,max_length=16)
    zone: int|None=Field(default=None,ge=0,le=12)
    velocity: float|None=Field(default=None,ge=40,le=180,allow_inf_nan=False)
    result: Literal['ball','called_strike','swinging_strike','foul','in_play']


class BundleValidationError(ValueError):
    def __init__(self,code):
        super().__init__(code)
        self.code=code


def load_bundle():
    manifest=json.loads((BUNDLE/'manifest.json').read_text(encoding='utf-8'))
    raw=(BUNDLE/'model.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=manifest['sha256']:
        raise BundleValidationError('model_checksum_mismatch')
    model=json.loads(raw)
    if any(model[k]!=manifest[k] for k in ['model_version','data_version','data_cutoff']):
        raise BundleValidationError('model_manifest_version_mismatch')
    if os.getenv('MODEL_VERSION') and os.environ['MODEL_VERSION']!=model['model_version']:
        raise BundleValidationError('configured_model_version_mismatch')
    if model.get('model_format')=='week2-v1':
        from src.week2_model import Week2Model
        return Week2Model.fromdict(model)
    if model.get('model_format'):
        raise BundleValidationError('unsupported_model_format')
    return Baseline(model)


def download_bundle_if_needed():
    """Explicit version pin; download trusted JSON only, never execute model code."""
    if (BUNDLE/'manifest.json').exists() and (BUNDLE/'model.json').exists():
        return
    url=os.getenv('SUPABASE_URL','').rstrip('/')
    secret=os.getenv('SUPABASE_SECRET_KEY','')
    version=os.getenv('MODEL_VERSION','')
    if not all([url,secret,version]):
        raise RuntimeError('Local model bundle missing; build it or configure Supabase model download.')
    BUNDLE.mkdir(parents=True,exist_ok=True)
    headers={'apikey':secret}
    if not secret.startswith('sb_secret_'):
        headers['Authorization']='Bearer '+secret
    with httpx.Client(timeout=45) as client:
        for name in ['model.json','manifest.json']:
            response=client.get(f'{url}/storage/v1/object/authenticated/model-artifacts/{version}/{name}',headers=headers)
            response.raise_for_status()
            temporary=BUNDLE/(name+'.part')
            temporary.write_bytes(response.content)
            temporary.replace(BUNDLE/name)


@asynccontextmanager
async def lifespan(app):
    app.state.baseline=None
    app.state.startup_error=None
    app.state.data_source_error=None
    app.state.manifest=None
    app.state.data_source='local_snapshot'
    try:
        download_bundle_if_needed()
        app.state.baseline=load_bundle()
        app.state.manifest=json.loads((BUNDLE/'manifest.json').read_text(encoding='utf-8'))
    except BundleValidationError as exc:
        app.state.startup_error=exc.code
    except (OSError,ValueError,KeyError,TypeError,RuntimeError,ImportError,httpx.HTTPError,httpx.InvalidURL):
        # Never return exception strings: HTTP errors can contain URLs or keys.
        app.state.startup_error='model_bundle_load_failed'
    # Keep the service inspectable if the external DB is temporarily unavailable.
    if app.state.baseline and os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_SECRET_KEY'):
        url=os.environ['SUPABASE_URL'].rstrip('/')
        secret=os.environ['SUPABASE_SECRET_KEY']
        headers={'apikey':secret}
        if not secret.startswith('sb_secret_'):
            headers['Authorization']='Bearer '+secret
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                version=app.state.baseline.model['model_version']
                response=await client.get(url+'/rest/v1/model_versions',headers=headers,
                    params={'model_version':'eq.'+version,'select':'model_version,data_version,data_cutoff,sha256'})
                response.raise_for_status()
                rows=response.json()
                m=app.state.baseline.model
                matches=(len(rows)==1 and rows[0]['model_version']==version
                         and rows[0]['data_version']==m['data_version']
                         and rows[0]['data_cutoff']==m['data_cutoff']
                         and rows[0]['sha256']==app.state.manifest['sha256'])
                if matches:
                    players=await client.get(url+'/rest/v1/players',headers=headers,
                        params={'data_version':'eq.'+rows[0]['data_version'],'select':'id,role,name,hand,sample_count,data_version','limit':1000})
                    players.raise_for_status()
                    catalog=players.json()
                    catalog_fields=('id','role','name','hand','sample_count','data_version')
                    if (len(catalog)==len(m['players']) and
                        {tuple(p[field] for field in catalog_fields) for p in catalog}
                        =={tuple(p[field] for field in catalog_fields) for p in m['players']}):
                        app.state.baseline.model['players']=catalog
                        app.state.data_source='supabase_verified_snapshot'
                    else:
                        app.state.data_source='local_snapshot_supabase_mismatch'
                        app.state.data_source_error='supabase_catalog_mismatch'
                else:
                    app.state.data_source='local_snapshot_supabase_mismatch'
                    app.state.data_source_error='supabase_model_mismatch'
        except (httpx.HTTPError,httpx.InvalidURL,ValueError,KeyError,TypeError):
            app.state.data_source='local_snapshot_supabase_unavailable'
            app.state.data_source_error='supabase_verification_unavailable'
    yield


app=FastAPI(title='球路參謀 PitchAdvisor TW',version='0.2.0',lifespan=lifespan)
origins=[x.strip() for x in os.getenv('ALLOWED_ORIGINS','http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:4173,http://localhost:4173').split(',') if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=False,
                   allow_methods=['GET','POST'],allow_headers=['Content-Type'])


def ready():
    baseline=getattr(app.state,'baseline',None)
    if baseline is None:
        raise HTTPException(503,{'code':getattr(app.state,'startup_error',None) or 'model_not_ready',
                                 'message':'模型尚未就緒，請檢查模型版本與伺服器設定。'})
    return baseline


@app.get('/health')
def health():
    baseline=ready()
    m=baseline.model
    return {'status':'ready','model_version':m['model_version'],'data_version':m['data_version'],
            'data_cutoff':m['data_cutoff'],'data_source':app.state.data_source,
            'data_source_error':app.state.data_source_error,'capabilities':public_capabilities(m)}


TASKS=('pitch','zone','result')
METRIC_FIELDS=('n','log_loss','top1_accuracy','top2_accuracy','ece')
AUDIT_FIELDS=('n','coverage','mean_set_size','ece_before','ece_after','log_loss_before','log_loss_after')


def public_capabilities(model):
    return {key:value for key,value in model['capabilities'].items()
            if key in ('sequence','batter_conditioned_model','conformal','conditional_result')
            and type(value) is bool}


def scalar_summary(value,fields):
    """Only named finite scalar summaries can leave the model bundle."""
    if not isinstance(value,dict):
        return {}
    return {key:item for key in fields if key in value
            and (item:=value[key]) is not None
            and isinstance(item,(str,int,float,bool))
            and (not isinstance(item,float) or math.isfinite(item))}


def task_summaries(value,fields):
    if not isinstance(value,dict):
        return {}
    return {task:scalar_summary(value[task],fields) for task in TASKS if task in value}


def public_evaluation(model):
    info=model.get('model_info')
    if not isinstance(info,dict):
        return None
    result=scalar_summary(info,('selected_candidate','selection_rule','selection_reason','training_rows','test_evaluated'))
    validation=info.get('validation',{})
    if isinstance(validation,dict):
        result['validation']={name:task_summaries(values,METRIC_FIELDS) for name,values in validation.items()}
    result['calibration_audit']=task_summaries(info.get('calibration_audit'),AUDIT_FIELDS)
    return result


def public_calibration(model):
    calibration=model.get('calibration')
    if not isinstance(calibration,dict):
        return None
    result=scalar_summary(calibration,('method','target_coverage','limitations'))
    result['temperature']=scalar_summary(calibration.get('temperature'),TASKS+('conditional_result',))
    result['thresholds']=scalar_summary(calibration.get('thresholds'),TASKS)
    result['audit']=task_summaries(calibration.get('audit'),AUDIT_FIELDS)
    split=calibration.get('split',{})
    if isinstance(split,dict):
        result['split']={name:scalar_summary(split[name],('date_min','date_max','rows'))
                         for name in ('temperature','conformal','audit') if name in split}
    return result


def public_model_info(model):
    """Publish evaluation summaries, never the model trees/weights or environment."""
    return {'model_version':model['model_version'],'model_name':model['model_name'],
            'data_version':model['data_version'],'data_cutoff':model['data_cutoff'],
            'capabilities':public_capabilities(model),'model_info':public_evaluation(model),
            'calibration':public_calibration(model)}


@app.get('/model-info')
def model_info():
    return public_model_info(ready().model)


@app.get('/players')
def players(role: Annotated[str|None,Query(pattern='^(pitcher|batter)$')]=None,
            q: Annotated[str,Query(max_length=80)]=''):
    baseline=ready()
    return {'players':sorted([p for p in baseline.model['players']
               if (role is None or p['role']==role) and q.casefold() in p['name'].casefold()],
               key=lambda p:-p['sample_count']),
            'data_version':baseline.model['data_version'],'data_cutoff':baseline.model['data_cutoff']}


@app.get('/metadata')
def metadata():
    baseline=ready()
    path=ROOT/'docs/week1/data_audit.json'
    audit=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return {'games':audit.get('games'),'pitches':audit.get('pitches'),'by_year':audit.get('by_year',[]),
            'training_pitches':baseline.model['training_pitches'],
            **public_model_info(baseline.model),
            'pitch_types':baseline.model['labels'],
            'sequence_schema':{'max_length':MAX_SEQUENCE_LENGTH,'complete_current_pa':True,
                               'results':list(SEQUENCE_RESULTS),'zone_min':0,'zone_max':12,
                               'velocity_min':40,'velocity_max':180}}


@app.post('/predict')
def predict(request:PredictionRequest):
    baseline=ready()
    if request.pitcher_id not in baseline.pitchers or request.batter_id not in baseline.batters:
        raise HTTPException(404,'此球員不在訓練版本可辨識名單內，請重新選擇。')
    if request.sequence and not baseline.model['capabilities'].get('sequence'):
        raise HTTPException(422,{'code':'history_not_supported',
                                 'message':'目前模型版本尚未支援序列輸入，請清空歷程或切換支援序列的模型。'})
    before=time.perf_counter()
    s=request.state
    sequence=[pitch.model_dump() for pitch in request.sequence]
    try:
        history=validate_sequence(sequence,s.balls,s.strikes,baseline.model['labels'])
    except SequenceValidationError as exc:
        raise HTTPException(422,{'code':exc.code,'message':str(exc),'index':exc.index}) from None
    bases=sum(int(occupied)<<i for i,occupied in enumerate(s.bases))
    args=(request.pitcher_id,request.batter_id,s.balls,s.strikes,s.outs,bases)
    response=baseline.predict(*args,sequence=sequence) if baseline.model.get('model_format')=='week2-v1' else baseline.predict(*args)
    response['source_mode']=app.state.data_source
    response['elapsed_ms']=round((time.perf_counter()-before)*1000,2)
    response['sequence_used']=bool(sequence and baseline.model['capabilities'].get('sequence'))
    response['history_summary']=dict(history,sequence_used=response['sequence_used'])
    response['model_info']=public_evaluation(baseline.model)
    response['calibration']=public_calibration(baseline.model)
    response['capabilities']=public_capabilities(baseline.model)
    response.setdefault('prediction_sets',None)
    if not sequence and not baseline.model.get('model_format'):
        response['warnings'].append('本次未提供已投球歷程，使用缺少歷程的情境分析。')
    if app.state.data_source_error:
        response['warnings'].append('雲端資料版本尚未核對成功，本次使用已驗證的本機模型快照。')
    return response
