import json
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
for path in sorted(Path('data/raw').glob('*.zip')):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith('.json')]
        singles = [n for n in names if __import__('re').search(r'(?:^|/)G\d+\.json$', n)]
        print(path.name, 'members', len(names), 'single_games', len(singles), 'uncompressed', sum(x.file_size for x in z.infolist()), 'names', names[:3])
        obj = json.loads(z.read(singles[0] if singles else names[0]))
        if isinstance(obj, list):
            obj = obj[0]
        print('game', {k:v for k,v in obj.items() if not isinstance(v,(list,dict))})
        print('box', obj.get('awayPitcherBox', [])[:1], obj.get('homeBatterBox', [])[:1])
        pa = obj['awayPAList'][0]
        print('PA', {k:v for k,v in pa.items() if k != 'events'})
        print('events', json.dumps(pa['events'][:6], ensure_ascii=False))
