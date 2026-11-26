"""Fail closed on secrets/private files; print locations and rules, never values."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 100 * 1024 * 1024
RULES = {
    'personal-home-path': re.compile(r'(?:[A-Za-z]:[\\/]+Users[\\/]+|/Users/|/home/)[\w.-]+[\\/]'),
    'private-resource-id': re.compile(r'\b(?:tea|srv|dep|exs)-[a-z0-9-]{10,}\b|\b[a-z]{20}\.supabase\.co\b'),
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'api-token': re.compile(r'(?:sb_secret_|sbp_|gh[pousr]_|github_pat_|sk-(?:proj-|ant-)?)[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{30,}'),
    'jwt': re.compile(r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'),
    'credential-url': re.compile(r'[a-z]+://[^\s/:\x22\x27]+:[^\s/@\x22\x27]+@[^\s\x22\x27]+'),
    'personal-phone': re.compile(r'(?<![\w.])(?:09\d{2}[- ]?\d{3}[- ]?\d{3}|\+886[- ]?9\d{2}[- ]?\d{3}[- ]?\d{3})(?![\w.])'),
}
EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
PRIVATE_DIRS = {'.git', '.ssh', '.aws', '.venv', '.cache', '.tools', 'node_modules',
                'graphify-out', 'private', 'secrets', 'output', '.playwright-cli'}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, stderr=subprocess.PIPE)


def private_path(name):
    path = PurePosixPath(name.rsplit('!', 1)[-1].replace('\\', '/'))
    return (any(part in PRIVATE_DIRS for part in path.parts)
            or (path.name.startswith('.env') and path.name != '.env.example')
            or path.name in {'.npmrc', '.pypirc', '.netrc', 'id_rsa', 'id_ed25519'}
            or path.suffix.lower() in {'.key', '.pem', '.p12', '.pfx', '.jks', '.db', '.sqlite', '.dump', '.bak'}
            or any('/'+part+'/' in '/'+path.as_posix() for part in ('data/raw', 'data/processed'))
            or path.name in {'球路參謀_初審提案簡報_v4.pptx', '野革盃黑客松_專案計畫書_v2.md'})


def local_secrets():
    values = set()
    for p in (ROOT/'.env', ROOT/'web/.env', ROOT/'web/.env.local'):
        if not p.is_file():
            continue
        for line in p.read_text(encoding='utf-8-sig').splitlines():
            key, separator, value = line.partition('=')
            value = value.strip().strip('\"\'')
            if separator and not key.lstrip().startswith('#') and re.search('KEY|TOKEN|SECRET|PASSWORD', key, re.I) and len(value) >= 12:
                values.add(value)
    return values


def inspect(name, raw, approved=(), secrets=(), depth=0):
    issues = []
    if private_path(name):
        issues.append((name, 0, 'private-file'))
    if len(raw) > MAX_BYTES:
        return issues + [(name, 0, 'file-too-large-to-review')]
    if raw.startswith(b'PK\x03\x04'):
        if depth >= 3:
            return issues + [(name, 0, 'archive-depth-limit')]
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if sum(i.file_size for i in archive.infolist()) > MAX_BYTES:
                    return issues + [(name, 0, 'archive-size-limit')]
                for item in archive.infolist():
                    if item.is_dir():
                        continue
                    if '..' in PurePosixPath(item.filename).parts or item.filename.startswith('/'):
                        issues.append((name, 0, 'unsafe-archive-path'))
                    data = archive.read(item)
                    member = name+'!'+item.filename
                    issues.extend(inspect(member, data, approved, secrets, depth+1))
                    if item.filename == 'docProps/core.xml':
                        for node in ET.fromstring(data):
                            if node.tag.split('}')[-1] in ('creator', 'lastModifiedBy') and (node.text or '').strip() not in ('', 'PitchAdvisor TW'):
                                issues.append((member, 0, 'personal-document-author'))
        except (zipfile.BadZipFile, RuntimeError, ET.ParseError):
            issues.append((name, 0, 'unreadable-archive'))
        return issues
    # PDF, images and video need human review; a changed digest invalidates it.
    opaque = PurePosixPath(name).suffix.lower() in {'.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.webm'}
    if opaque or (b'\0' in raw[:8192] and not raw.startswith((b'\xff\xfe', b'\xfe\xff'))):
        if hashlib.sha256(raw).hexdigest() not in approved:
            issues.append((name, 0, 'unreviewed-binary'))
        return issues
    text = raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig', errors='replace')
    for rule, pattern in RULES.items():
        for match in pattern.finditer(text):
            issues.append((name, text.count('\n', 0, match.start())+1, rule))
    for match in EMAIL.finditer(text):
        domain = match.group().split('@')[-1].lower()
        # Upstream public attribution is retained; this does not exempt secrets.
        if name == 'docs/sources/REBas-README.md' or domain.endswith('.noreply.github.com') or domain in ('example.com', 'example.org', 'example.net') or domain.endswith(('.invalid', '.example', '.test')):
            continue
        issues.append((name, text.count('\n', 0, match.start())+1, 'personal-email'))
    for secret in secrets:
        if secret in text:
            issues.append((name, 0, 'local-secret-value'))
    return issues


def entries(mode, refs):
    if mode == 'history':
        revisions = refs or ['--all']
        for line in git('rev-list', '--objects', *revisions).decode('utf-8').splitlines():
            oid, _, name = line.partition(' ')
            kind = git('cat-file', '-t', oid).strip()
            if kind == b'blob':
                yield name, git('cat-file', 'blob', oid)
            elif kind in (b'commit', b'tag'):
                yield 'git-metadata/'+oid, git('cat-file', kind.decode(), oid)
    elif mode == 'staged':
        for item in git('ls-files', '--stage', '-z').decode('utf-8').split('\0'):
            if not item:
                continue
            info, name = item.split('\t', 1)
            filemode, oid, stage = info.split()
            if stage != '0' or filemode in ('120000', '160000'):
                raise ValueError('Unmerged entries, symlinks and submodules require manual review')
            yield name, git('cat-file', 'blob', oid)
    else:
        for name in sorted(set(git('ls-files', '--cached', '--others', '--exclude-standard', '-z').decode('utf-8').split('\0')) - {''}):
            path = ROOT/name
            if path.is_symlink():
                raise ValueError('Symlinks require manual review')
            if path.is_file():
                yield name, path.read_bytes()


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['worktree', 'staged', 'history'], default='worktree')
    parser.add_argument('--ref', action='append', default=[])
    args = parser.parse_args()
    for ref in args.ref:
        if not re.fullmatch(r'[a-fA-F0-9]{40,64}', ref):
            parser.error('History refs must be full commit hashes')
    executable = ROOT/'.tools/gitleaks'/('gitleaks.exe' if os.name == 'nt' else 'gitleaks')
    if not executable.is_file():
        raise SystemExit('Security check blocked: run python scripts/setup_security.py first.')
    approved = set(json.loads((ROOT/'.security-reviewed-media.json').read_text(encoding='utf-8'))['sha256'].values())
    issues, count = [], 0
    secrets = local_secrets()
    with tempfile.TemporaryDirectory(prefix='pitchadvisor-security-') as temp:
        stage = Path(temp)/'files'
        stage.mkdir()
        lookup = {}
        for name, raw in entries(args.mode, args.ref):
            count += 1
            issues.extend(inspect(name, raw, approved, secrets))
            target = stage/(str(count)+PurePosixPath(name).suffix)
            target.write_bytes(raw)
            lookup[target.name] = name
        report = Path(temp)/'gitleaks.json'
        empty_ignore = Path(temp)/'.gitleaksignore'
        empty_ignore.write_text('', encoding='utf-8')
        result = subprocess.run([str(executable), 'dir', str(stage), '--redact=100', '--no-banner', '--no-color',
            '--config', str(ROOT/'.gitleaks.toml'), '--ignore-gitleaks-allow', '--gitleaks-ignore-path', str(empty_ignore),
            '--max-archive-depth=3', '--report-format=json', '--report-path', str(report)], capture_output=True)
        if result.returncode not in (0, 1):
            raise SystemExit('Security check blocked: Gitleaks could not complete (details suppressed).')
        if report.is_file():
            for finding in json.loads(report.read_text(encoding='utf-8')):
                source = Path(finding['File']).name
                issues.append((lookup.get(source, 'archive-member'), finding['StartLine'], 'gitleaks:'+finding['RuleID']))
        if result.returncode == 1 and not issues:
            raise SystemExit('Security check blocked: secret scanner reported findings without a usable report.')
    for name, line, rule in sorted(set(issues)):
        print(f'BLOCKED {name}:{line} [{rule}]')
    print(f'Security check: {count} entries; {len(set(issues))} findings; mode={args.mode}. Values are never printed.')
    return 1 if issues else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError):
        raise SystemExit('Security check could not finish; commit/push blocked. No sensitive details printed.')
