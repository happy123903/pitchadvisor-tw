"""Serve compiled UI and real frozen-model inference on loopback, without cloud I/O."""
from __future__ import annotations

import argparse
import hashlib
import os
from contextlib import asynccontextmanager
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FROZEN_SHA256 = 'aa3e984758796843bce68aa71fb06a4c84739a7d8048be475cc1bfe6855671ec'


def create_offline_app(web_dir=None, instance_id=None):
    # Set before importing api.main: its dotenv loader must not import a user's
    # cloud configuration. Empty values also take precedence over dotenv values.
    os.environ.update(PYTHON_DOTENV_DISABLED='1', SUPABASE_URL='', SUPABASE_SECRET_KEY='',
                      MODEL_BUNDLE_DIR=str(ROOT / 'artifacts/week2'), MODEL_VERSION='week2-sequence-v1')
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from api import main as api_module

    web = Path(web_dir) if web_dir else (ROOT / 'frontend' if (ROOT / 'frontend/index.html').exists() else ROOT / '.cache/offline-web')
    if not (web / 'index.html').is_file():
        raise ValueError('Compiled offline UI missing. Run scripts/build_offline_bundle.py first.')
    bundle = ROOT / 'artifacts/week2'
    if hashlib.sha256((bundle / 'model.json').read_bytes()).hexdigest() != FROZEN_SHA256:
        raise ValueError('Offline mode requires the fixed week-two model checksum')
    identity = instance_id or str(uuid.uuid4())

    @asynccontextmanager
    async def lifespan(_parent):
        previous_bundle = api_module.BUNDLE
        api_module.BUNDLE = bundle
        try:
            # A mounted FastAPI child's lifespan is not entered automatically.
            async with api_module.app.router.lifespan_context(api_module.app):
                if api_module.app.state.baseline is None:
                    raise RuntimeError('The frozen offline model did not become ready')
                if api_module.app.state.data_source != 'local_snapshot':
                    raise RuntimeError('Offline startup attempted a cloud data source')
                yield
        finally:
            api_module.BUNDLE = previous_bundle

    application = FastAPI(title='PitchAdvisor offline local', lifespan=lifespan,
                          docs_url=None, redoc_url=None, openapi_url=None)

    @application.get('/offline-info')
    def offline_info():
        return {'mode': 'offline_local', 'instance_id': identity, 'server_pid': os.getpid(),
                'model_version': 'week2-sequence-v1', 'bundle_sha256': FROZEN_SHA256,
                'cloud_connections_enabled': False}

    application.mount('/api', api_module.app)
    application.mount('/', StaticFiles(directory=web, html=True), name='frontend')
    return application


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--web-dir', type=Path)
    parser.add_argument('--instance-id')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    import uvicorn
    uvicorn.run(create_offline_app(args.web_dir, args.instance_id), host='127.0.0.1', port=args.port,
                access_log=False)


if __name__ == '__main__':
    main()
