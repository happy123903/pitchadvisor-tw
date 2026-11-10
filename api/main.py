from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from src.baseline import Baseline

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
    sequence: list[dict]=Field(default_factory=list,max_length=64)


def load_bundle():
    manifest=json.loads((BUNDLE/'manifest.json').read_text(encoding='utf-8'))
    raw=(BUNDLE/'model.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=manifest['sha256']:
        raise ValueError('Model checksum mismatch')
    model=json.loads(raw)
    if any(model[k]!=manifest[k] for k in ['model_version','data_version','data_cutoff']):
        raise ValueError('Model and manifest versions differ')
    if os.getenv('MODEL_VERSION') and os.environ['MODEL_VERSION']!=model['model_version']:
        raise ValueError('Configured model version differs from local bundle')
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
    app.state.data_source='local_snapshot'
    try:
        download_bundle_if_needed()
        app.state.baseline=load_bundle()
    except (OSError,ValueError,RuntimeError,httpx.HTTPError) as exc:
        app.state.startup_error=type(exc).__name__
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
                    params={'model_version':'eq.'+version,'select':'model_version,data_version'})
                response.raise_for_status()
                rows=response.json()
                if len(rows)==1 and rows[0]['data_version']==app.state.baseline.model['data_version']:
                    players=await client.get(url+'/rest/v1/players',headers=headers,
                        params={'data_version':'eq.'+rows[0]['data_version'],'select':'id,role,name,hand,sample_count,data_version','limit':1000})
                    players.raise_for_status()
                    catalog=players.json()
                    if {(p['id'],p['role']) for p in catalog}=={(p['id'],p['role']) for p in app.state.baseline.model['players']}:
                        app.state.baseline.model['players']=catalog
                        app.state.data_source='supabase_verified_snapshot'
        except (httpx.HTTPError,ValueError,KeyError):
            app.state.data_source='local_snapshot_supabase_unavailable'
    yield


app=FastAPI(title='球路參謀 PitchAdvisor TW',version='0.1.0',lifespan=lifespan)
origins=[x.strip() for x in os.getenv('ALLOWED_ORIGINS','http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:4173,http://localhost:4173').split(',') if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=False,
                   allow_methods=['GET','POST'],allow_headers=['Content-Type'])


def ready():
    baseline=getattr(app.state,'baseline',None)
    if baseline is None:
        raise HTTPException(503,'模型尚未就緒。請先建立第一週模型包或確認雲端設定。')
    return baseline


@app.get('/health')
def health():
    baseline=ready()
    m=baseline.model
    return {'status':'ready','model_version':m['model_version'],'data_version':m['data_version'],
            'data_cutoff':m['data_cutoff'],'data_source':app.state.data_source,
            'capabilities':m['capabilities']}


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
            'data_cutoff':baseline.model['data_cutoff'],'model_version':baseline.model['model_version']}


@app.post('/predict')
def predict(request:PredictionRequest):
    baseline=ready()
    if request.pitcher_id not in baseline.pitchers or request.batter_id not in baseline.batters:
        raise HTTPException(404,'此球員不在訓練版本可辨識名單內，請重新選擇。')
    if request.sequence:
        raise HTTPException(422,'第一週基準尚未支援序列輸入；此功能排定於第二週，不能假裝已使用歷程。')
    before=time.perf_counter()
    s=request.state
    bases=sum(int(occupied)<<i for i,occupied in enumerate(s.bases))
    response=baseline.predict(request.pitcher_id,request.batter_id,s.balls,s.strikes,s.outs,bases)
    response['source_mode']=app.state.data_source
    response['elapsed_ms']=round((time.perf_counter()-before)*1000,2)
    response['warnings'].append('本次未使用已投球歷程；預測集合與校準於第二週完成後才會提供。')
    return response
