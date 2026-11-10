"""Idempotent import. Defaults to an offline dry run; secrets never printed."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')
import httpx
from dotenv import load_dotenv


def bundle_path(value=None):
    path=Path(value or 'artifacts/baseline')
    return path if path.is_absolute() else ROOT/path


def rows_from_bundle(directory=None):
    directory=bundle_path(directory)
    raw=(directory/'model.json').read_bytes()
    model=json.loads(raw)
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256(raw).hexdigest()!=manifest['sha256']:
        raise ValueError('Model checksum mismatch; cloud import was not started.')
    if any(model[field]!=manifest[field] for field in ['model_version','data_version','data_cutoff']):
        raise ValueError('Model and manifest versions differ; cloud import was not started.')
    snapshot=model.get('baseline',model)
    version=model['data_version']
    if snapshot['data_version']!=version:
        raise ValueError('Snapshot and model data versions differ.')
    repertoire=[{'pitcher_id':pid,'data_version':version,'pitch_type':kind,'sample_count':n}
                for pid,stats in snapshot['pitch_player'].items() for kind,n in stats.items()]
    aggregates=[]
    for scope in ['pitch_count','pitch_player_count','zone_type','zone_player_type',
                  'matchup_counts','state_counts','re_table','action_values',
                  'action_count_values','action_state_values','pitcher_action_values']:
        aggregates.extend({'data_version':version,'scope':scope,'lookup_key':lookup,'stats':stats}
                          for lookup,stats in snapshot[scope].items())
    registration={'model_version':model['model_version'],'data_version':version,
        'data_cutoff':model['data_cutoff'],'model_name':model['model_name'],
        'storage_path':model['model_version']+'/model.json','sha256':manifest['sha256'],
        'metadata':{'training_pitches':model['training_pitches'],'capabilities':model['capabilities'],
                    'model_family':model.get('estimator',{}).get('family','frequency'),
                    'feature_version':model.get('feature_version',model.get('model_format','week1'))}}
    return model,{'players':model.get('players',snapshot['players']),'pitcher_repertoire':repertoire,
                  'aggregate_stats':aggregates,'model_versions':[registration]}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true',help='Upload to the explicitly configured new project')
    parser.add_argument('--bundle-dir',default=None,help='Versioned bundle directory, relative to the project root')
    args=parser.parse_args()
    load_dotenv(ROOT/'.env')
    directory=bundle_path(args.bundle_dir or os.getenv('MODEL_BUNDLE_DIR'))
    model,tables=rows_from_bundle(directory)
    print(json.dumps({'mode':'apply' if args.apply else 'dry_run','model_version':model['model_version'],'data_version':model['data_version'],
                      'tables':{name:len(rows) for name,rows in tables.items()}},ensure_ascii=False))
    if not args.apply:
        print('Offline validation complete. No cloud data changed.')
        return
    url=os.getenv('SUPABASE_URL','').rstrip('/')
    secret=os.getenv('SUPABASE_SECRET_KEY','')
    if not url.startswith('https://') or not secret:
        raise SystemExit('Configure SUPABASE_URL and SUPABASE_SECRET_KEY in the ignored root .env first.')
    origin=urlsplit(url)
    if origin.path or origin.query or origin.fragment or origin.username or origin.password:
        raise SystemExit('SUPABASE_URL must be the HTTPS project origin without /rest/v1/ or other paths.')
    headers={'apikey':secret,'Content-Type':'application/json','Prefer':'resolution=merge-duplicates'}
    if not secret.startswith('sb_secret_'):
        headers['Authorization']='Bearer '+secret
    with httpx.Client(timeout=60,headers=headers) as client:
        # Register the version last: partial imports must not appear as ready.
        for table in ['players','pitcher_repertoire','aggregate_stats']:
            for start in range(0,len(tables[table]),300):
                response=client.post(url+'/rest/v1/'+table,json=tables[table][start:start+300])
                if response.is_error:
                    raise SystemExit(f'Import failed for {table}: HTTP {response.status_code}. Check migration and permissions; credentials were not logged.')
            print('Imported',table,len(tables[table]))
        for name in ['model.json','manifest.json']:
            response=client.post(url+'/storage/v1/object/model-artifacts/'+model['model_version']+'/'+name,
                content=(directory/name).read_bytes(),headers={'x-upsert':'true'})
            if response.is_error:
                raise SystemExit(f'Model upload failed: HTTP {response.status_code}')
        response=client.post(url+'/rest/v1/model_versions',json=tables['model_versions'])
        response.raise_for_status()
    print('Cloud import complete; verify /health after deploying the pinned model.')


if __name__=='__main__':
    main()
