"""Read per-game ZIP members once; reconstruct pre-pitch states conservatively."""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from src.domain import advance_count, number, result_label, zone13

ROOT = Path(__file__).resolve().parents[1]


def games_from_archives(raw: Path):
    seen = set()
    for archive in sorted(raw.glob('*.zip')):
        with zipfile.ZipFile(archive) as z:
            members = sorted(n for n in z.namelist() if re.search(r'-G\d+\.json$', n))
            if not members:
                raise ValueError(f'No individual game members: {archive.name}')
            for name in members:
                game = json.loads(z.read(name))
                key = (game['seasonId'], int(game['seq']))
                if key in seen:
                    raise ValueError(f'Duplicate game: {key}')
                seen.add(key)
                yield archive.name, name, game


def flatten(raw: Path):
    rows, game_rows, identity_rows = [], [], []
    audit = Counter()
    unknown_codes = Counter()
    event_types = Counter()
    pa_results = Counter()
    for archive, member, game in games_from_archives(raw):
        year = int(game['date'][:4])
        game_id = f'{game["seasonId"]}:{game["seq"]}'
        game_rows.append({'game_id': game_id, 'year': year, 'date': game['date'][:10],
                          'seq': int(game['seq']), 'stadium': game.get('stadium'),
                          'archive': archive, 'member': member})
        for side, defending in [('away', 'home'), ('home', 'away')]:
            batting_team = game[side + 'TeamId']
            defending_team = game[defending + 'TeamId']
            lookups = {}
            for role, box_side, team, box_type in [('batter', side, batting_team, 'BatterBox'),
                                                  ('pitcher', defending, defending_team, 'PitcherBox')]:
                mapping = defaultdict(set)
                for player in game.get(box_side + box_type, []):
                    if player.get('playerId') and player.get('playerName'):
                        mapping[player['playerName']].add(player['playerId'])
                        identity_rows.append({'id': player['playerId'], 'name': player['playerName'],
                                              'role': role, 'team_id': team, 'year': year,
                                              'date': game['date'][:10]})
                lookups[role] = mapping
            score = 0
            prior_inning, outs, bases, bases_known = None, 0, 0, True
            halves = defaultdict(list)
            end_states = {}
            for pa_index, pa in enumerate(game.get(side + 'PAList', [])):
                inning = int(pa['inning'])
                if inning != prior_inning:
                    outs, bases = 0, 0
                    bases_known = inning <= 9  # Do not assume extra-inning starting runners.
                    prior_inning = inning
                events = pa.get('events', [])
                pitch_indexes = [i for i, e in enumerate(events) if e.get('type') == 'PITCH']
                last_pitch = pitch_indexes[-1] if pitch_indexes else -1
                balls, strikes, count_known = 0, 0, True
                pa_row_indexes = []
                pa_result = pa.get('result', pa.get('results', 'UNKNOWN'))
                pa_results[str(pa_result)] += 1
                for event_index, event in enumerate(events):
                    event_type = event.get('type', 'UNKNOWN')
                    event_types[event_type] += 1
                    runners = event.get('runners') or []
                    scored = sum(bool(x.get('scored')) for x in runners)
                    out_count = sum(bool(x.get('isOut')) for x in runners)
                    if event_index == last_pitch:
                        # PA fields describe the instant BEFORE the final pitch, not PA start.
                        outs, bases = int(pa['outs']), int(pa['bases'])
                        bases_known = True
                        score = int(pa[side + 'Scores'])
                        if balls != int(pa['balls']) or strikes != int(pa['strikes']):
                            audit['pa_count_mismatch'] += 1
                            count_known = False
                            for idx in pa_row_indexes:
                                rows[idx]['count_valid'] = False
                    if event_type == 'PITCH':
                        code = event.get('pitchCode')
                        pitcher_name = event.get('pitcherName') or pa.get('pitcherName')
                        batter_name = event.get('batterName') or pa.get('batterName')
                        ids = {}
                        for role, name in [('pitcher', pitcher_name), ('batter', batter_name)]:
                            candidates = lookups[role].get(name, set())
                            ids[role] = next(iter(candidates)) if len(candidates) == 1 else None
                            if ids[role] is None:
                                audit[role + '_unresolved'] += 1
                        velocity = number(event.get('velocity'))
                        if velocity is not None and not 40 <= velocity <= 180:
                            audit['velocity_outlier'] += 1
                            velocity = None
                        x, y = number(event.get('coordX')), number(event.get('coordY'))
                        zone = zone13(x, y)
                        if x is not None and y is not None and zone is None:
                            audit['coordinate_outlier'] += 1
                        is_last = event_index == last_pitch
                        after_bases = int(pa['endBases']) if is_last else bases
                        after_outs = int(pa['endOuts']) if is_last else outs + out_count
                        after_known = is_last or (bases_known and not runners)
                        runs = int(pa['end' + side.title() + 'Scores']) - score if is_last else scored
                        try:
                            next_b, next_s, terminal = advance_count(balls, strikes, code)
                        except ValueError:
                            unknown_codes[str(code)] += 1
                            next_b, next_s, terminal = balls, strikes, False
                            count_known = False
                        if terminal and not is_last:
                            count_known = False
                        valid_count = count_known and 0 <= balls <= 3 and 0 <= strikes <= 2
                        row = {
                            'game_id': game_id, 'date': game['date'][:10], 'year': year,
                            'stadium': game.get('stadium'), 'side': side, 'inning': inning,
                            'pa_index': pa_index, 'event_index': event_index,
                            'pitcher_id': ids['pitcher'], 'batter_id': ids['batter'],
                            'pitcher_name': pitcher_name, 'batter_name': batter_name,
                            'pitcher_hand': pa.get('pitcherHand') if pitcher_name == pa.get('pitcherName') else None,
                            'batter_hand': pa.get('batterHand') if batter_name == pa.get('batterName') else None,
                            'balls': balls, 'strikes': strikes, 'outs': outs,
                            'bases': bases if bases_known else None,
                            'count_valid': valid_count, 'bases_known': bases_known,
                            'pitch_type': event.get('pitchType') or None, 'pitch_code': code,
                            'result': result_label(code, pa_result if is_last else None),
                            'velocity': velocity, 'coord_x': x, 'coord_y': y, 'zone': zone,
                            'before_score': score, 'runs': runs,
                            'next_balls': 0 if is_last else next_b,
                            'next_strikes': 0 if is_last else next_s,
                            'next_outs': after_outs, 'next_bases': after_bases if after_known else None,
                            'transition_known': after_known, 'pa_result': pa_result,
                            'is_final_pitch': is_last, 'history_length': len(pa_row_indexes),
                        }
                        rows.append(row)
                        idx = len(rows) - 1
                        pa_row_indexes.append(idx)
                        halves[inning].append(idx)
                        balls, strikes = next_b, next_s
                    score += scored
                    outs += out_count
                    # Runner records omit start/end bases. Never invent a base assignment.
                    if runners:
                        bases_known = False
                score = int(pa['end' + side.title() + 'Scores'])
                outs, bases = int(pa['endOuts']), int(pa['endBases'])
                bases_known = True
                end_states[inning] = (score, outs)
            for inning, indexes in halves.items():
                final_score, final_outs = end_states[inning]
                complete = final_outs == 3
                if not complete:
                    audit['incomplete_half_innings'] += 1
                for idx in indexes:
                    row = rows[idx]
                    remaining = final_score - row['before_score']
                    row['runs_to_end'] = remaining if complete and remaining >= 0 else None
                    row['complete_half'] = complete
    pitches = pd.DataFrame(rows)
    if pitches.empty:
        raise ValueError('No pitch records found')
    for col in ['balls', 'strikes', 'outs', 'bases', 'next_bases', 'zone']:
        pitches[col] = pd.array(pitches[col], dtype='Int64')
    pitches['state_valid'] = (pitches['count_valid'] & pitches['bases_known'] &
                              pitches['outs'].between(0, 2) & pitches['bases'].between(0, 7)).fillna(False)
    pitches['identity_valid'] = pitches['pitcher_id'].notna() & pitches['batter_id'].notna()
    duplicate = pitches.duplicated(['game_id', 'side', 'pa_index', 'event_index']).sum()
    if duplicate:
        raise ValueError(f'Duplicate pitch rows: {duplicate}')
    return pitches, pd.DataFrame(game_rows), pd.DataFrame(identity_rows).drop_duplicates(), {
        'counters': dict(audit), 'event_types': dict(event_types),
        'unknown_pitch_codes': dict(unknown_codes), 'pa_results': dict(pa_results),
    }


def split_games(games):
    """Chronological full-game splits, fixed without inspecting outcomes."""
    ordered = games.sort_values(['date', 'game_id']).copy()
    dates = sorted(ordered.loc[ordered.year == 2024, 'date'].unique())
    if len(dates) < 20:
        raise ValueError('Insufficient 2024 dates for train/validation/calibration split')
    validation_start, calibration_start = dates[int(len(dates) * .70)], dates[int(len(dates) * .85)]
    ordered['split'] = 'train'
    ordered.loc[(ordered.year == 2024) & (ordered.date >= validation_start), 'split'] = 'validation'
    ordered.loc[(ordered.year == 2024) & (ordered.date >= calibration_start), 'split'] = 'calibration'
    ordered.loc[ordered.year == 2025, 'split'] = 'test'
    if not set(ordered.year).issubset({2023, 2024, 2025}):
        raise ValueError('Unexpected year outside planned range')
    return ordered, {'validation_start': validation_start, 'calibration_start': calibration_start,
                     'test_start': '2025-01-01', 'strategy': '2024 unique dates 70%/85%; whole games, no label tuning'}
