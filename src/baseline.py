"""Transparent, train-only smoothed frequency baseline and run-value ranking."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.domain import PITCH_NAMES, RESULTS, ZONE_NAMES, state_key


def key(*values):
    return '|'.join(str(int(v)) if isinstance(v, (int, np.integer)) else str(v) for v in values)


def counts(frame, dimensions, target):
    table = {}
    for row in frame.groupby(dimensions + [target], observed=True, dropna=True).size().reset_index(name='n').itertuples(index=False, name=None):
        table.setdefault(key(*row[:-2]), {})[str(row[-2])] = int(row[-1])
    return table


def moments(frame, dimensions):
    grouped = frame.groupby(dimensions, observed=True).delta_re.agg(['count', 'mean'])
    return {key(*(idx if isinstance(idx, tuple) else (idx,))): [int(row['count']), float(row['mean'])]
            for idx, row in grouped.iterrows()}


def distribution(table, labels, prior=None, alpha=30):
    prior = np.ones(len(labels)) / len(labels) if prior is None else np.asarray(prior)
    values = np.array([table.get(str(label), 0) for label in labels], dtype=float)
    return (values + alpha * prior) / (values.sum() + alpha)


def fit(train, identities, model_version, data_version):
    clean = train.loc[train.state_valid & train.identity_valid & train.pitch_type.isin(PITCH_NAMES)].copy()
    if clean.empty:
        raise ValueError('No valid training pitches')
    labels = sorted(clean.pitch_type.unique())
    usable_re = clean.loc[clean.runs_to_end.notna()]
    global_re = float(usable_re.runs_to_end.mean())
    parent = usable_re.groupby(['outs', 'bases'], observed=True).runs_to_end.mean().to_dict()
    re_table = {}
    for idx, group in usable_re.groupby(['balls', 'strikes', 'outs', 'bases'], observed=True):
        prior = parent.get((idx[2], idx[3]), global_re)
        re_table[key(*idx)] = float((group.runs_to_end.sum() + 30 * prior) / (len(group) + 30))
    def value(b, s, o, base):
        return 0.0 if o >= 3 else re_table.get(state_key(b, s, o, base), parent.get((o, base), global_re))
    valid_transition = clean.transition_known & clean.next_bases.notna() & clean.runs.ge(0) & clean.next_outs.between(0, 3)
    transitions = clean.loc[valid_transition].copy()
    transitions['delta_re'] = [float(r.runs + value(r.next_balls, r.next_strikes, r.next_outs, r.next_bases)
                                     - value(r.balls, r.strikes, r.outs, r.bases))
                               for r in transitions.itertuples()]
    zone_data = clean.loc[clean.zone.notna()].copy()
    zone_data['zone'] = zone_data.zone.astype(int).astype(str)
    zone_transitions = transitions.loc[transitions.zone.notna()].copy()
    zone_transitions['zone'] = zone_transitions.zone.astype(int)
    players = []
    for role, col in [('pitcher', 'pitcher_id'), ('batter', 'batter_id')]:
        for player_id, group in clean.groupby(col):
            matches = identities.loc[(identities.id == player_id) & (identities.role == role)].sort_values('date')
            hand = group[role + '_hand'].dropna().mode()
            players.append({'id': player_id, 'role': role, 'name': str(matches.iloc[-1]['name']),
                            'hand': str(hand.iloc[0]) if len(hand) else None,
                            'sample_count': len(group), 'data_version': data_version})
    model = {
        'model_version': model_version, 'data_version': data_version,
        'model_name': 'hierarchical-frequency-v1', 'data_cutoff': clean.date.max(),
        'labels': labels, 'zone_names': ZONE_NAMES, 'result_labels': RESULTS,
        'training_pitches': len(clean), 'players': players,
        'pitch_global': clean.pitch_type.value_counts().astype(int).to_dict(),
        'pitch_count': counts(clean, ['balls', 'strikes'], 'pitch_type'),
        'pitch_player': counts(clean, ['pitcher_id'], 'pitch_type'),
        'pitch_player_count': counts(clean, ['pitcher_id', 'balls', 'strikes'], 'pitch_type'),
        'zone_global': zone_data.zone.value_counts().astype(int).to_dict(),
        'zone_type': counts(zone_data, ['pitch_type'], 'zone'),
        'zone_player_type': counts(zone_data, ['pitcher_id', 'pitch_type'], 'zone'),
        'result_global': clean.result.value_counts().astype(int).to_dict(),
        'result_count': counts(clean, ['balls', 'strikes'], 'result'),
        'result_action': counts(zone_data, ['balls', 'strikes', 'pitch_type', 'zone'], 'result'),
        'matchup_counts': {k: sum(v.values()) for k,v in counts(clean, ['pitcher_id', 'batter_id'], 'pitch_type').items()},
        'batter_counts': clean.batter_id.value_counts().astype(int).to_dict(),
        'state_counts': {k:sum(v.values()) for k,v in counts(clean, ['balls', 'strikes', 'outs', 'bases'], 'pitch_type').items()},
        're_table': re_table, 're_parent': {key(*k): float(v) for k,v in parent.items()}, 'global_re': global_re,
        'action_values': moments(zone_transitions, ['pitch_type', 'zone']),
        'action_count_values': moments(zone_transitions, ['pitch_type', 'zone', 'balls', 'strikes']),
        'action_state_values': moments(zone_transitions, ['pitch_type', 'zone', 'balls', 'strikes', 'outs', 'bases']),
        'pitcher_action_values': moments(zone_transitions, ['pitcher_id', 'pitch_type', 'zone', 'balls', 'strikes']),
        'default_delta': float(transitions.delta_re.mean()),
        'smoothing': {'pitch_count': 30, 'pitcher': 80, 'pitcher_count': 40, 'zone': 40, 'run_value': 30},
        'capabilities': {'sequence': False, 'batter_conditioned_model': False, 'conformal': False},
    }
    return model


class Baseline:
    def __init__(self, model):
        self.model = model
        self.labels = model['labels']
        self.pitchers = {p['id']:p for p in model['players'] if p['role'] == 'pitcher'}
        self.batters = {p['id']:p for p in model['players'] if p['role'] == 'batter'}

    @classmethod
    def load(cls, path: Path):
        return cls(json.loads(path.read_text(encoding='utf-8')))

    def pitch_distribution(self, pitcher_id, balls, strikes, individual=True):
        m = self.model
        global_p = distribution(m['pitch_global'], self.labels, alpha=1)
        count_p = distribution(m['pitch_count'].get(key(balls, strikes), {}), self.labels, global_p, 30)
        if not individual:
            return count_p
        personal = m['pitch_player'].get(pitcher_id, {})
        if not personal:
            return count_p
        # Both priors contribute; unseen player-count combinations remain stable.
        player_p = distribution(personal, self.labels, global_p, 80)
        return distribution(m['pitch_player_count'].get(key(pitcher_id, balls, strikes), {}),
                            self.labels, .5 * player_p + .5 * count_p, 40)

    def zone_distribution(self, pitcher_id, pitch_type):
        m = self.model
        global_p = distribution(m['zone_global'], list(range(13)), alpha=1)
        type_p = distribution(m['zone_type'].get(pitch_type, {}), list(range(13)), global_p, 40)
        return distribution(m['zone_player_type'].get(key(pitcher_id, pitch_type), {}), list(range(13)), type_p, 40)

    def recommend(self, pitcher_id, balls, strikes, outs, bases):
        m = self.model
        candidates = []
        for pitch_type, pitch_n in m['pitch_player'].get(pitcher_id, {}).items():
            if pitch_n < 5:
                continue
            for zone in range(13):
                action = m['action_values'].get(key(pitch_type, zone))
                if not action or action[0] < 10:
                    continue
                estimate = action[1]
                support = 0
                for table, lookup in [
                    ('action_count_values', key(pitch_type, zone, balls, strikes)),
                    ('action_state_values', key(pitch_type, zone, balls, strikes, outs, bases)),
                    ('pitcher_action_values', key(pitcher_id, pitch_type, zone, balls, strikes)),
                ]:
                    n, mean = m[table].get(lookup, [0, estimate])
                    estimate = (n * mean + 30 * estimate) / (n + 30)
                    if table == 'pitcher_action_values':
                        support = n
                candidates.append({'pitch_type': pitch_type, 'zone': zone,
                                   'expected_run_change': round(float(estimate), 5),
                                   'direct_sample_count': support,
                                   'pooled_sample_count': action[0],
                                   'support': 'pooled' if support < 20 else 'historical'})
        return sorted(candidates, key=lambda a: a['expected_run_change'])[:5]

    def predict(self, pitcher_id, batter_id, balls, strikes, outs, bases):
        m = self.model
        pitch_p = self.pitch_distribution(pitcher_id, balls, strikes)
        zone_p = sum(p * self.zone_distribution(pitcher_id, t) for p,t in zip(pitch_p, self.labels))
        global_r = distribution(m['result_global'], RESULTS)
        result_p = distribution(m['result_count'].get(key(balls,strikes), {}), RESULTS, global_r)
        pitcher_n = sum(m['pitch_player'].get(pitcher_id, {}).values())
        batter_n = m['batter_counts'].get(batter_id, 0)
        matchup_n = m['matchup_counts'].get(key(pitcher_id, batter_id), 0)
        warnings = [
            '第一週版本：以歷史頻率及平滑估計配球傾向，尚未訓練序列模型。',
            '打者用於對戰樣本查核；目前基準尚未將打者能力作為預測特徵。',
            '落點為人工紀錄的實際位置，不是投手的瞄準點。',
            '推薦為觀測資料的估計失分變化，不能解釋為因果或實戰保證。',
        ]
        if matchup_n < 30:
            warnings.append('直接對戰樣本少，分析主要依賴投手及聯盟平滑統計。')
        if pitcher_n < 100:
            warnings.append('投手樣本偏少，已提高聯盟統計的影響。')
        return {
            'pitch_probabilities': [{'pitch_type': t, 'name': PITCH_NAMES[t], 'probability': float(p)} for t,p in zip(self.labels,pitch_p)],
            'zone_probabilities': [{'zone': z, 'name': ZONE_NAMES[z], 'probability': float(p)} for z,p in enumerate(zone_p)],
            'result_probabilities': [{'result': r, 'probability': float(p)} for r,p in zip(RESULTS,result_p)],
            'recommendations': self.recommend(pitcher_id, balls, strikes, outs, bases),
            'sample_counts': {'pitcher': pitcher_n, 'batter': batter_n, 'matchup': matchup_n,
                              'league_state': m['state_counts'].get(key(balls,strikes,outs,bases),0)},
            'prediction_set': None, 'warnings': warnings,
            'model_version': m['model_version'], 'data_version': m['data_version'],
            'data_cutoff': m['data_cutoff'], 'model_name': m['model_name'],
            'capabilities': m['capabilities'], 'source_mode': 'local_snapshot',
        }


def evaluate(model, frame):
    baseline = Baseline(model)
    valid = frame.loc[frame.state_valid & frame.pitch_type.isin(model['labels'])]
    output = {}
    for name, individual in [('league_count',False),('pitcher_count_shrunk',True)]:
        losses, top1, top2 = [], [], []
        for r in valid.itertuples():
            p = baseline.pitch_distribution(r.pitcher_id,r.balls,r.strikes,individual)
            target = model['labels'].index(r.pitch_type)
            losses.append(-np.log(max(p[target],1e-12)))
            ranking = np.argsort(p)[::-1]
            top1.append(ranking[0] == target)
            top2.append(target in ranking[:2])
        output[name] = {'n':len(losses), 'log_loss':float(np.mean(losses)),
                        'top1_accuracy':float(np.mean(top1)), 'top2_accuracy':float(np.mean(top2))}
    output['excluded_rows'] = len(frame) - len(valid)
    output['test_evaluated'] = False
    return output
