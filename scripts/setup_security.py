"""Install a pinned, checksum-verified scanner and repository-local Git hooks."""
import argparse
import hashlib
import io
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '8.30.1'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-hooks', action='store_true')
    args = parser.parse_args()
    system = {'Windows': 'windows', 'Linux': 'linux', 'Darwin': 'darwin'}[platform.system()]
    machine = {'AMD64': 'x64', 'x86_64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}[platform.machine()]
    extension = 'zip' if system == 'windows' else 'tar.gz'
    name = f'gitleaks_{VERSION}_{system}_{machine}.{extension}'
    base = f'https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/'
    checksums = urllib.request.urlopen(base+f'gitleaks_{VERSION}_checksums.txt', timeout=60).read().decode()
    expected = next(line.split()[0] for line in checksums.splitlines() if line.endswith(name))
    raw = urllib.request.urlopen(base+name, timeout=60).read()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise SystemExit('Gitleaks checksum mismatch; installation stopped.')
    binary = 'gitleaks.exe' if system == 'windows' else 'gitleaks'
    if extension == 'zip':
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            content = archive.read(binary)
    else:
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
            content = archive.extractfile(binary).read()
    target = ROOT/'.tools/gitleaks'/binary
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    target.chmod(0o755)
    if not args.no_hooks:
        current = subprocess.run(['git', 'config', '--get', 'core.hooksPath'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if current and current != '.githooks':
            raise SystemExit('Existing hooksPath found; merge the security hooks manually before continuing.')
        subprocess.run(['git', 'config', '--local', 'core.hooksPath', '.githooks'], cwd=ROOT, check=True)
        for hook in ('pre-commit', 'pre-push'):
            (ROOT/'.githooks'/hook).chmod(0o755)
    print(f'Installed Gitleaks {VERSION}; checksums verified; hooks={not args.no_hooks}.')


if __name__ == '__main__':
    main()
