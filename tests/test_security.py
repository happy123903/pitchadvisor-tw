import asyncio
import hashlib
import io
import subprocess
import zipfile

import pytest

from scripts import security_check as security
from src.http_security import RequestSizeLimit


def test_secret_in_nested_zip_and_private_filename_are_blocked():
    token = 'sb_' + 'secret_' + 'synthetic-not-a-real-key-1234567890'
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, 'w') as archive:
        archive.writestr('.env.local', 'KEY='+token)
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, 'w') as archive:
        archive.writestr('nested.zip', inner.getvalue())
    findings = security.inspect('release.zip', outer.getvalue())
    assert {'private-file', 'api-token'} <= {rule for _, _, rule in findings}
    assert token not in str(findings)


def test_known_secret_without_provider_prefix_is_blocked():
    value = 'synthetic' + '-opaque-value-1234567890'
    assert security.inspect('config.txt', value.encode(), secrets={value}) == [('config.txt', 0, 'local-secret-value')]


def test_home_path_email_and_document_author_are_blocked():
    private = 'C:' + '/' + 'Users' + '/someone/project'
    mail = 'person' + '@' + 'mail-provider.com'
    findings = security.inspect('report.txt', (private+'\n'+mail).encode())
    assert {rule for _, _, rule in findings} == {'personal-home-path', 'personal-email'}
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w') as archive:
        archive.writestr('docProps/core.xml', '<root><creator>Local Author</creator></root>')
    assert 'personal-document-author' in {rule for _, _, rule in security.inspect('deck.pptx', raw.getvalue())}


def test_binary_change_requires_review_and_oversized_archive_fails(monkeypatch):
    original = b'\x89PNG\0reviewed'
    approved = {hashlib.sha256(original).hexdigest()}
    assert not security.inspect('screen.png', original, approved)
    assert security.inspect('screen.png', original+b'new private text', approved)
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('large.txt', b'a'*10000)
    monkeypatch.setattr(security, 'MAX_BYTES', 1000)
    assert security.inspect('release.zip', raw.getvalue())[0][2] == 'archive-size-limit'


@pytest.fixture
def repository(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, stderr=subprocess.PIPE)
    git('init')
    git('config', 'user.name', 'Security Test')
    git('config', 'user.email', 'security-test@users.noreply.github.com')
    monkeypatch.setattr(security, 'ROOT', tmp_path)
    return tmp_path, git


def test_scan_reads_staged_bytes_even_when_worktree_is_clean(repository):
    root, git = repository
    path = root/'config.txt'
    token = 'sb_'+'secret_'+'synthetic-not-a-real-key-1234567890'
    path.write_text(token)
    git('add', 'config.txt')
    path.write_text('clean working copy')
    assert any(security.inspect(name, raw) for name, raw in security.entries('staged', []))


def test_history_scans_deleted_secrets_and_commit_metadata(repository):
    root, git = repository
    path = root/'config.txt'
    path.write_text('sb_'+'secret_'+'synthetic-not-a-real-key-1234567890')
    git('add', 'config.txt')
    git('commit', '-m', 'first')
    git('rm', 'config.txt')
    git('commit', '-m', 'remove fixture')
    entries = list(security.entries('history', []))
    assert any(name.startswith('git-metadata/') for name, _ in entries)
    assert any(security.inspect(name, raw) for name, raw in entries)


def test_chunked_request_stops_before_json_parser():
    async def run(chunks):
        called, messages = [], []
        async def app(scope, receive, send):
            called.append((await receive())['body'])
        async def receive():
            return chunks.pop(0)
        async def send(message):
            messages.append(message)
        await RequestSizeLimit(app, max_bytes=8)({'type': 'http', 'headers': []}, receive, send)
        return called, messages
    called, messages = asyncio.run(run([
        {'type': 'http.request', 'body': b'12345', 'more_body': True},
        {'type': 'http.request', 'body': b'6789', 'more_body': False}]))
    assert not called and messages[0]['status'] == 413
    called, _ = asyncio.run(run([{'type': 'http.request', 'body': b'12345678', 'more_body': False}]))
    assert called == [b'12345678']
