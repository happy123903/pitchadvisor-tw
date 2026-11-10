import hashlib
import json
from pathlib import Path

import pytest

from scripts.supabase_sync import ROOT, rows_from_bundle


def test_versioned_bundle_keeps_snapshot_statistics_and_registers_new_model(tmp_path):
    baseline=json.loads((ROOT/'artifacts/baseline/model.json').read_text(encoding='utf-8'))
    model={key:baseline[key] for key in ['data_version','data_cutoff','training_pitches','players']}
    model.update(model_version='week2-fixture-v1',model_name='fixture',baseline=baseline,
                 capabilities={'sequence':True},estimator={'family':'lightgbm'})
    raw=json.dumps(model,ensure_ascii=False).encode('utf-8')
    (tmp_path/'model.json').write_bytes(raw)
    manifest={key:model[key] for key in ['model_version','data_version','data_cutoff']}
    manifest['sha256']=hashlib.sha256(raw).hexdigest()
    (tmp_path/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    loaded,tables=rows_from_bundle(tmp_path)
    assert loaded['model_version']=='week2-fixture-v1'
    assert len(tables['players'])==len(baseline['players'])
    assert tables['model_versions'][0]['storage_path']=='week2-fixture-v1/model.json'
    assert tables['model_versions'][0]['metadata']['model_family']=='lightgbm'
    assert tables['model_versions'][0]['sha256']==manifest['sha256']
    assert len(tables['aggregate_stats'])>70000


def test_import_rejects_corrupted_bytes_before_creating_rows(tmp_path):
    (tmp_path/'model.json').write_bytes(b'{}')
    (tmp_path/'manifest.json').write_text(json.dumps({'sha256':'0'*64}),encoding='utf-8')
    with pytest.raises(ValueError,match='checksum mismatch'):
        rows_from_bundle(tmp_path)
