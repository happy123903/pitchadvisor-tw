"""Idempotent import. Defaults to an offline dry run; secrets never printed."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')
import httpx
from dotenv import load_dotenv


def rows_from_bundle():
    model=json.loads((ROOT/'artifacts/baseline/model.json').read_text(encoding='utf-8'))
    manifest=json.loads((ROOT/'artifacts/baseline/manifest.json').read_text(encoding='utf-8'))
    version=model['data_version']
    repertoire=[{'pitcher_id':pid,'data_version':version,'pitch_type':kind,'sample_count':n}
                for pid,stats in model['pitch_player'].items() for kind,n in stats.items()]
    aggregates=[]
    for scope in ['pitch_count','pitch_player_count','zone_type','zone_player_type',
                  'matchup_counts','state_counts','re_table','action_values',
                  'action_count_values','action_state_values','pitcher_action_values']:
        aggregates.extend({'data_version':version,'scope':scope,'lookup_key':lookup,'stats':stats}
                          for lookup,stats in model[scope].items())
    registration={'model_version':model['model_version'],'data_version':version,
        'data_cutoff':model['data_cutoff'],'model_name':model['model_name'],
        'storage_path':model['model_version']+'/model.json','sha256':manifest['sha256'],
        'metadata':{'training_pitches':model['training_pitches'],'capabilities':model['capabilities']}}
    return model,{'players':model['players'],'pitcher_repertoire':repertoire,
                  'aggregate_stats':aggregates,'model_versions':[registration]}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true',help='Upload to the explicitly configured new project')
    args=parser.parse_args()
    load_dotenv(ROOT/'.env')
    model,tables=rows_from_bundle()
    print(json.dumps({'mode':'apply' if args.apply else 'dry_run','data_version':model['data_version'],
                      'tables':{name:len(rows) for name,rows in tables.items()}},ensure_ascii=False))
    if not args.apply:
        print('Offline validation complete. No cloud data changed.')
        return
    url=os.getenv('SUPABASE_URL','').rstrip('/')
    secret=os.getenv('SUPABASE_SECRET_KEY','')
    if not url.startswith('https://') or not secret:
        raise SystemExit('Configure SUPABASE_URL and SUPABASE_SECRET_KEY in the ignored root .env first.')
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
                content=(ROOT/'artifacts/baseline'/name).read_bytes(),headers={'x-upsert':'true'})
            if response.is_error:
                raise SystemExit(f'Model upload failed: HTTP {response.status_code}')
        response=client.post(url+'/rest/v1/model_versions',json=tables['model_versions'])
        response.raise_for_status()
    print('Cloud import complete; verify /health after deploying the pinned model.')


if __name__=='__main__':
    main()
