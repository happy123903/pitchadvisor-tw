"""Build a credential-free offline application package; Python runtime is separate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FROZEN_SHA256 = 'aa3e984758796843bce68aa71fb06a4c84739a7d8048be475cc1bfe6855671ec'
RUNTIME_FILES = [
    'api/__init__.py', 'api/main.py',
    'src/__init__.py', 'src/baseline.py', 'src/domain.py', 'src/sequence.py',
    'src/week2_features.py', 'src/week2_model.py',
    'scripts/serve_offline.py', 'scripts/Start-Offline.ps1', 'scripts/Stop-Offline.ps1',
    'artifacts/week2/model.json', 'artifacts/week2/manifest.json', 'requirements-lock.txt',
    'docs/week1/data_audit.json', 'docs/week3/final_evaluation_public.json',
    'docs/week3/FINAL_RESULTS.md', 'docs/week3/final_test_summary.png',
    'docs/week3/final_evaluation.json', 'docs/week3/freeze_before_final_test.json',
    'docs/week3/OFFLINE_GUIDE.md', 'docs/sources/REBas-LICENSE',
]


def checked_remove(path, expected):
    resolved = Path(path).resolve()
    if resolved != Path(expected).resolve() or not resolved.is_relative_to((ROOT / '.cache').resolve()):
        raise ValueError('Refusing to clear an unexpected staging directory')
    if resolved.exists():
        shutil.rmtree(resolved)


def build_frontend():
    env = os.environ.copy()
    env.update(VITE_API_BASE_URL='/api', PAGES_BASE_PATH='./')
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if not npm:
        raise RuntimeError('npm is required to compile the offline frontend')
    subprocess.run([npm, '--prefix', str(ROOT / 'web'), 'run', 'build'], cwd=ROOT, env=env, check=True)
    target = ROOT / '.cache/offline-web'
    checked_remove(target, ROOT / '.cache/offline-web')
    shutil.copytree(ROOT / 'web/dist', target)
    return target


def assemble(web_dir):
    web_dir = Path(web_dir)
    if not (web_dir / 'index.html').is_file() or not (web_dir / 'demo/cases.json').is_file():
        raise ValueError('Offline frontend and genuine fixed demo cases must be compiled first')
    model = ROOT / 'artifacts/week2/model.json'
    if hashlib.sha256(model.read_bytes()).hexdigest() != FROZEN_SHA256:
        raise ValueError('Offline package requires the frozen model SHA-256')
    # Catch an accidental production build before packaging it as an offline UI.
    js_files = list((web_dir / 'assets').glob('*.js'))
    if not js_files or any('https://pitchadvisor-api.onrender.com' in p.read_text(encoding='utf-8') for p in js_files):
        raise ValueError('Frontend still targets the cloud API; rebuild with VITE_API_BASE_URL=/api')
    cases = json.loads((web_dir / 'demo/cases.json').read_text(encoding='utf-8'))
    if cases['bundle_sha256'] != FROZEN_SHA256:
        raise ValueError('Fixed demo cases and packaged model disagree')
    stage = ROOT / '.cache/offline-bundle/PitchAdvisor_Offline'
    checked_remove(stage, ROOT / '.cache/offline-bundle/PitchAdvisor_Offline')
    stage.mkdir(parents=True)
    for name in RUNTIME_FILES:
        source = ROOT / name
        destination = stage / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    shutil.copytree(web_dir, stage / 'frontend')
    readme = '''# PitchAdvisor TW 本機斷網展示包

這個資料夾包含已編譯的網頁、真實模型推論程式、凍結模型、固定示範案例及評估報告。
**不包含 Python、第三方套件或虛擬環境。** 必須先在有網路時準備 Python 3.12 與 requirements-lock.txt 的 runtime 套件；既有專案的 .venv 可直接使用。
不需要 Node、Supabase、Render 或任何 .env 憑證來執行本包。

在 PowerShell 中進入解壓縮後的 PitchAdvisor_Offline 資料夾：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/Start-Offline.ps1 -PythonExe "C:\\完整路徑\\Python環境\\Scripts\\python.exe"
```

開啟 http://127.0.0.1:8765/。任意合法情境由本機模型即時計算；若切換固定案例頁，則是明確標示的已計算案例。

停止：`powershell -ExecutionPolicy Bypass -File scripts/Stop-Offline.ps1`。
前景執行也可用：`<Python路徑> scripts/serve_offline.py --port 8765`，按 Ctrl+C 結束。

完整準備、版本查核與斷網演練：[OFFLINE_GUIDE.md](docs/week3/OFFLINE_GUIDE.md)。
資料來源：Rebas 野球革命 Open Data（ODC-By），授權副本位於 docs/sources/REBas-LICENSE。
模型與最終測試限制請閱讀 docs/week3/FINAL_RESULTS.md。
'''
    (stage / 'README.md').write_bytes(readme.encode('utf-8'))
    files = {}
    forbidden = re.compile(rb'(?:sb_secret_[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,})')
    for path in sorted(stage.rglob('*')):
        if not path.is_file():
            continue
        if path.name.startswith('.env') or '__pycache__' in path.parts or 'node_modules' in path.parts:
            raise ValueError('Unexpected private or development file in the offline stage')
        raw = path.read_bytes()
        if forbidden.search(raw):
            raise ValueError('Credential-like value found in offline package; packaging stopped')
        files[path.relative_to(stage).as_posix()] = hashlib.sha256(raw).hexdigest()
    manifest = {'format': 'pitchadvisor-offline-v1', 'model_version': 'week2-sequence-v1',
                'bundle_sha256': FROZEN_SHA256, 'python_runtime_included': False,
                'dependencies_included': False, 'credentials_included': False,
                'api_base_url': '/api', 'host': '127.0.0.1', 'default_port': 8765,
                'files_sha256': files}
    (stage / 'OFFLINE_MANIFEST.json').write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    output = ROOT / 'deliverables/PitchAdvisor_Offline.zip'
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                archive.write(path, arcname='PitchAdvisor_Offline/' + path.relative_to(stage).as_posix())
    result = {'archive': str(output.relative_to(ROOT)), 'bytes': output.stat().st_size,
              'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
              'staging_directory': str(stage.relative_to(ROOT)), 'files': len(files) + 1,
              'bundle_sha256': FROZEN_SHA256, 'python_runtime_included': False,
              'dependencies_included': False, 'credentials_included': False}
    (ROOT / 'docs/week3/offline_package.json').write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-build', action='store_true', help='Package the previously prepared .cache/offline-web')
    args = parser.parse_args()
    assemble(ROOT / '.cache/offline-web' if args.skip_build else build_frontend())
