"""Read back a registered private model and catalog, without printing credentials."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle-dir', default='artifacts/week2')
    parser.add_argument('--output', default='docs/week2/supabase_verification.json')
    args = parser.parse_args()
    directory = ROOT / args.bundle_dir
    local_raw = (directory / 'model.json').read_bytes()
    model = json.loads(local_raw)
    manifest = json.loads((directory / 'manifest.json').read_bytes())
    checksum = hashlib.sha256(local_raw).hexdigest()
    assert manifest['sha256'] == checksum
    load_dotenv(ROOT / '.env')
    url, secret = os.environ['SUPABASE_URL'].rstrip('/'), os.environ['SUPABASE_SECRET_KEY']
    headers = {'apikey': secret}
    if not secret.startswith('sb_secret_'):
        headers['Authorization'] = 'Bearer ' + secret
    counts = {}
    with httpx.Client(timeout=60, headers=headers) as client:
        for name in ['players', 'pitcher_repertoire', 'aggregate_stats', 'model_versions']:
            response = client.head(url + '/rest/v1/' + name, headers={'Prefer': 'count=exact'})
            response.raise_for_status()
            counts[name] = int(response.headers['content-range'].split('/')[-1])
        registered = client.get(url + '/rest/v1/model_versions', params={'model_version': 'eq.' + model['model_version'],
            'select': 'model_version,data_version,data_cutoff,sha256,storage_path,metadata'})
        registered.raise_for_status()
        rows = registered.json()
        assert len(rows) == 1
        registration = rows[0]
        assert registration['sha256'] == checksum
        assert all(registration[k] == model[k] for k in ['model_version', 'data_version', 'data_cutoff'])
        assert registration['metadata']['feature_version'] == model['model_format']
        catalog = client.get(url + '/rest/v1/players', params={'data_version': 'eq.' + model['data_version'],
            'select': 'id,role,name,hand,sample_count,data_version', 'limit': 1000})
        catalog.raise_for_status()
        fields = ('id', 'role', 'name', 'hand', 'sample_count', 'data_version')
        assert len(catalog.json()) == len(model['players'])
        assert {tuple(row[k] for k in fields) for row in catalog.json()} == {
            tuple(row[k] for k in fields) for row in model['players']}
        for name in ['model.json', 'manifest.json']:
            response = client.get(url + '/storage/v1/object/authenticated/model-artifacts/' + model['model_version'] + '/' + name)
            response.raise_for_status()
            assert response.content == (directory / name).read_bytes(), name + ' readback mismatch'
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'model_version': model['model_version'],
              'sha256': checksum, 'model_bytes': len(local_raw), 'tables': counts,
              'checks': {'registration_matches_manifest': True, 'full_catalog_matches': True,
                         'private_model_bytes_match': True, 'private_manifest_bytes_match': True},
              'registration': registration}
    (ROOT / args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['model_version', 'sha256', 'model_bytes', 'tables', 'checks']}))


if __name__ == '__main__':
    main()
