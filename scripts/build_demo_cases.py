"""Capture genuine frozen-model responses for explicitly labelled fixed examples."""
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.update(MODEL_BUNDLE_DIR=str(ROOT/'artifacts/week2'),MODEL_VERSION='week2-sequence-v1',
                  SUPABASE_URL='',SUPABASE_SECRET_KEY='')

from fastapi.testclient import TestClient
from api.main import app


def main():
    directory=ROOT/'artifacts/week2'
    original=(directory/'model.json').read_bytes()
    manifest=json.loads((directory/'manifest.json').read_bytes())
    assert hashlib.sha256(original).hexdigest()==manifest['sha256']
    with TestClient(app) as client:
        players=client.get('/players').json()['players']
        pitchers=[p for p in players if p['role']=='pitcher']
        batters=[p for p in players if p['role']=='batter']
        pitcher,batter=pitchers[0],batters[0]
        small=min(batters,key=lambda p:p['sample_count'])
        labels=client.get('/metadata').json()['pitch_types']
        common=app.state.baseline.baseline.model['pitch_player'][pitcher['id']]
        types=sorted((t for t in labels if t in common),key=lambda t:-common[t])
        state={'balls':0,'strikes':0,'outs':0,'bases':[False,False,False]}
        history=[{'pitch_type':types[0],'zone':None,'velocity':None,'result':'ball'},
                 {'pitch_type':types[min(1,len(types)-1)],'zone':4,'velocity':140.,'result':'called_strike'}]
        specifications=[
            ('count-only','一般情境：無已投球歷程',batter,state,[]),
            ('history-two','完整歷程：兩球後的下一球',batter,dict(state,balls=1,strikes=1),history),
            ('small-matchup','少量樣本：查看資料支持與集合',small,dict(state,balls=1,strikes=2,outs=1,bases=[True,False,False]),[])]
        cases=[]
        for identity,title,opponent,situation,sequence in specifications:
            request={'pitcher_id':pitcher['id'],'batter_id':opponent['id'],'state':situation,'sequence':sequence}
            response=client.post('/predict',json=request)
            response.raise_for_status()
            prediction=response.json()
            cases.append({'id':identity,'title':title,'description':'手動設定的示範輸入，並非特定歷史打席；輸出由凍結模型實際計算。',
                          'pitcher_name':pitcher['name'],'batter_name':opponent['name'],
                          'request':request,'response':prediction})
        evaluation=client.get('/evaluation')
        bundle={'schema_version':1,'mode':'fixed_demo_cases','model_version':manifest['model_version'],
                'data_version':manifest['data_version'],'data_cutoff':manifest['data_cutoff'],
                'bundle_sha256':manifest['sha256'],'recorded_from':'local_snapshot',
                'disclaimer':'固定示範案例，僅切換已計算的輸入與結果，不接受任意情境即時推論。',
                'players':players,'metadata':client.get('/metadata').json(),
                'model_info':client.get('/model-info').json(),
                'evaluation':evaluation.json() if evaluation.status_code==200 else None,'cases':cases}
    assert hashlib.sha256((directory/'model.json').read_bytes()).hexdigest()==manifest['sha256']
    target=ROOT/'web/public/demo/cases.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(bundle,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(target.relative_to(ROOT)),'case_ids':[c['id'] for c in cases],
                      'bundle_sha256':manifest['sha256'],'final_evaluation_available':bundle['evaluation'] is not None}))


if __name__=='__main__':
    main()
