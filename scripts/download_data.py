"""Download the organizer's public article, schema and original season archives."""
from __future__ import annotations

import hashlib
import argparse
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
SOURCES = ROOT / 'docs' / 'sources'
ARTICLE = 'https://blog.rebas.tw/articles/4136'
REPO = 'https://api.github.com/repos/rebas-tw/rebas.tw-open-data'
ASSETS = {
    'CPBL-2023-G1-G150-OpenData.zip',
    'CPBL-2023-G151-G300-OpenData.zip',
    'CPBL-2024-OpenData.zip',
    'CPBL-2025-OpenData.zip',
}


def request(url: str):
    return urllib.request.urlopen(urllib.request.Request(url, headers={
        'User-Agent': 'PitchAdvisor-TW/0.1 (public research dataset download)',
        'Accept': 'application/octet-stream' if '/releases/assets/' in url else '*/*',
    }), timeout=45)


def save(url: str, target: Path) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        print(f'Downloading {target.name} ...', flush=True)
        temp = target.with_suffix(target.suffix + '.part')
        for attempt in range(3):
            try:
                fetch_url = url + '?download=1&research=' + str(int(time.time())) if '/releases/download/' in url else url
                with request(fetch_url) as response, temp.open('wb') as stream:
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
                temp.replace(target)
                break
            except (OSError, urllib.error.URLError):
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
    with target.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    print(f'Downloaded {target.name}: {target.stat().st_size:,} bytes', flush=True)
    return {'url': url, 'path': str(target.relative_to(ROOT)).replace('\\', '/'),
            'bytes': target.stat().st_size, 'sha256': digest}


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[dict] = []
        self.text: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        if tag == 'a':
            href = dict(attrs).get('href', '')
            if href.startswith('http'):
                self.links.append({'url': href})

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        if tag in ('p', 'h1', 'h2', 'h3', 'h4', 'li', 'tr'):
            self.text.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)


def main():
    arguments = argparse.ArgumentParser()
    arguments.add_argument('--schemas-only', action='store_true')
    options = arguments.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    SOURCES.mkdir(parents=True, exist_ok=True)
    manifest = {'retrieved_at': datetime.now(timezone.utc).isoformat(),
                'organizer_article': ARTICLE, 'files': [], 'article_links': []}
    try:
        with request(ARTICLE) as response:
            article = response.read().decode('utf-8')
        (RAW / 'organizer_article.html').write_text(article, encoding='utf-8')
        parser = ArticleParser()
        parser.feed(article)
        manifest['article_links'] = parser.links
        # Store only a compact factual source note in tracked docs, not the article.
        article_text = re.sub(r'\n\s*\n+', '\n', ''.join(parser.text))
        (RAW / 'organizer_article.txt').write_text(article_text, encoding='utf-8')
        print('Organizer article read; official open-data link confirmed:',
              any(x['url'] == 'https://github.com/rebas-tw/rebas.tw-open-data' for x in parser.links), flush=True)
    except urllib.error.HTTPError as exc:
        manifest['article_fetch_error'] = str(exc)
        print(f'Organizer article HTTP {exc.code}; public GitHub source remains available.', flush=True)

    with request(REPO + '/releases') as response:
        releases = json.load(response)
    (RAW / 'releases.json').write_text(json.dumps(releases, ensure_ascii=False, indent=2), encoding='utf-8')
    with request(REPO + '/contents/schema') as response:
        schema = json.load(response)
    for item in schema:
        if item['type'] == 'file' and item['name'].endswith(('.md','.png')):
            manifest['files'].append(save(item['download_url'], SOURCES / 'schema' / item['name']))
    for name in ['README.md', 'LICENSE']:
        manifest['files'].append(save(
            'https://raw.githubusercontent.com/rebas-tw/rebas.tw-open-data/main/' + name,
            SOURCES / ('REBas-' + name)))
    if options.schemas_only:
        return
    found = set()
    for release in sorted(releases, key=lambda r: r['published_at'], reverse=True):
        for asset in release['assets']:
            if asset['name'] in ASSETS and asset['name'] not in found:
                entry = save(asset['browser_download_url'], RAW / asset['name'])
                if entry['bytes'] != asset['size']:
                    raise ValueError(f'Asset size mismatch: {asset["name"]}')
                with zipfile.ZipFile(RAW / asset['name']) as archive:
                    bad = archive.testzip()
                    if bad:
                        raise ValueError(f'ZIP CRC failed: {bad}')
                    entry['zip_members'] = len(archive.infolist())
                    entry['uncompressed_bytes'] = sum(x.file_size for x in archive.infolist())
                entry['release'] = release['tag_name']
                manifest['files'].append(entry)
                found.add(asset['name'])
    if found != ASSETS:
        raise ValueError(f'Missing expected releases: {ASSETS - found}')

    (SOURCES / 'download_manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Download and ZIP validation complete.', flush=True)


if __name__ == '__main__':
    main()
