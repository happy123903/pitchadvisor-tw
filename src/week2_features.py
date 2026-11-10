"""Train-only encoders and strictly previous-pitch features for week two."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.domain import zone13
from src.sequence import SequenceValidationError, validate_sequence

MAX_HISTORY = 16
HISTORY_RESULTS = ['ball', 'called_strike', 'swinging_strike', 'foul', 'in_play']


def finite(value):
    return None if pd.isna(value) else float(value)


def fit_encoder(train, labels=None):
    """Only the fixed training partition can define IDs, counts or normalization."""
    if not train.split.eq('train').all() or train.year.gt(2024).any():
        raise ValueError('Encoder fitting requires the pre-2025 training split only')
    velocity = train.loc[train.velocity.notna()]
    league_mean = float(velocity.velocity.mean())
    league_std = max(3., float(velocity.velocity.std()))
    def stats(group):
        return {'n': len(group), 'mean': float(group.velocity.mean()), 'std': max(3., float(group.velocity.std()))}
    velocity_stats = {'league': {'n': len(velocity), 'mean': league_mean, 'std': league_std},
                      'pitch_type': {str(t): stats(g) for t, g in velocity.groupby('pitch_type') if len(g) >= 20},
                      'pitcher_pitch_type': {str(pid) + '|' + str(t): stats(g)
                          for (pid, t), g in velocity.groupby(['pitcher_id', 'pitch_type']) if len(g) >= 20},
                      'minimum_group_n': 20, 'std_floor': 3.}
    return {
        'pitch_labels': list(labels or sorted(train.pitch_type.dropna().unique())),
        'pitcher_ids': sorted(train.pitcher_id.dropna().unique()),
        'batter_ids': sorted(train.batter_id.dropna().unique()),
        'pitcher_counts': train.pitcher_id.value_counts().astype(int).to_dict(),
        'batter_counts': train.batter_id.value_counts().astype(int).to_dict(),
        'pitcher_hands': train.groupby('pitcher_id').pitcher_hand.agg(lambda x: x.mode().iloc[0] if len(x.mode()) else '').to_dict(),
        'batter_hands': train.groupby('batter_id').batter_hand.agg(lambda x: x.mode().iloc[0] if len(x.mode()) else '').to_dict(),
        'velocity_center': float(train.velocity.median()), 'velocity_scale': 15.0,
        'velocity_stats': velocity_stats,
        'shrinkage_strength': 100.0, 'max_history': MAX_HISTORY,
        'history_results': HISTORY_RESULTS, 'result_labels': HISTORY_RESULTS,
    }


def tokens_for_history(sequence, encoder, pitcher_id=None):
    labels = encoder['pitch_labels']
    width = len(labels) + 13 + len(HISTORY_RESULTS) + 2
    tokens = np.zeros((MAX_HISTORY, width), dtype=np.float32)
    for i, pitch in enumerate(sequence):
        if pitch['pitch_type'] in labels:
            tokens[i, labels.index(pitch['pitch_type'])] = 1
        zone = pitch.get('zone')
        if zone is not None:
            tokens[i, len(labels) + int(zone)] = 1
        tokens[i, len(labels) + 13 + HISTORY_RESULTS.index(pitch['result'])] = 1
        velocity = pitch.get('velocity')
        statistics = encoder.get('velocity_stats')
        if statistics:
            chosen = statistics['pitcher_pitch_type'].get(str(pitcher_id) + '|' + pitch['pitch_type'],
                     statistics['pitch_type'].get(pitch['pitch_type'], statistics['league']))
            center, scale = chosen['mean'], chosen['std']
        else:
            center, scale = encoder['velocity_center'], encoder['velocity_scale']
        tokens[i, -2] = 0 if velocity is None else (velocity - center) / scale
        tokens[i, -1] = velocity is None
    return tokens


def context_row(pid, bid, balls, strikes, outs, bases, encoder):
    def hand(role, identity):
        return {'L': -1, 'R': 1}.get(encoder[role + '_hands'].get(identity), 0)
    def gate(role, identity):
        count = encoder[role + '_counts'].get(identity, 0)
        return count / (count + encoder['shrinkage_strength'])
    return [balls / 3, strikes / 2, outs / 2,
            float(bool(bases & 1)), float(bool(bases & 2)), float(bool(bases & 4)),
            hand('pitcher', pid), hand('batter', bid), gate('pitcher', pid), gate('batter', bid)]


@dataclass
class FeatureBatch:
    ids: np.ndarray
    context: np.ndarray
    tokens: np.ndarray
    lengths: np.ndarray
    pitch: np.ndarray
    zone: np.ndarray
    result: np.ndarray
    frame: pd.DataFrame

    def subset(self, indices):
        indices = np.asarray(indices)
        return FeatureBatch(*(getattr(self, key)[indices] for key in ['ids', 'context', 'tokens', 'lengths', 'pitch', 'zone', 'result']),
                            self.frame.iloc[indices].reset_index(drop=True))

    def lgb_features(self, sequence=True):
        context = np.column_stack([self.ids, self.context]).astype(np.float32)
        if not sequence:
            return context
        denominator = np.maximum(self.lengths, 1)[:, None]
        mean = self.tokens.sum(axis=1) / denominator
        last = self.tokens[np.arange(len(self.ids)), np.maximum(self.lengths - 1, 0)].copy()
        last[self.lengths == 0] = 0
        return np.column_stack([context, self.lengths / MAX_HISTORY, self.lengths == 0, mean, last]).astype(np.float32)


def build_batch(frame, encoder, *, jitter=0.0, seed=42):
    """Rows may contain train/validation/calibration, never the 2025 test split.

    Histories are constructed before current-row filtering, sorted within the same
    game and PA. Invalid or terminal histories are missing, never silently repaired.
    Jitter is a train-only experiment on recorded location coordinates; it does not
    perturb validation/calibration or the current state.
    """
    if frame.year.gt(2024).any() or frame.split.eq('test').any():
        raise ValueError('The 2025 holdout must not enter week-two feature construction')
    if jitter and not frame.split.eq('train').all():
        raise ValueError('Coordinate augmentation is training-only')
    work = frame.sort_values(['date', 'game_id', 'side', 'pa_index', 'event_index'], kind='stable').copy()
    if jitter:
        rng = np.random.default_rng(seed)
        x = work.coord_x.to_numpy(dtype=float) + rng.normal(0, jitter, len(work))
        y = work.coord_y.to_numpy(dtype=float) + rng.normal(0, jitter * 1.2, len(work))
        work['zone'] = [zone13(a, b) for a, b in zip(x, y)]
    pmap = {value: i + 1 for i, value in enumerate(encoder['pitcher_ids'])}
    bmap = {value: i + 1 for i, value in enumerate(encoder['batter_ids'])}
    labels = encoder['pitch_labels']
    ids, contexts, token_rows, lengths, targets, rows = [], [], [], [], [], []
    previous_key, history, history_pitchers = None, [], []
    for row in work.itertuples(index=False):
        group_key = (row.game_id, row.side, row.pa_index)
        if group_key != previous_key:
            history = []
            history_pitchers = []
            previous_key = group_key
        valid = bool(row.state_valid) and bool(row.identity_valid) and row.pitch_type in labels and row.result in HISTORY_RESULTS
        if valid:
            try:
                validate_sequence(history, int(row.balls), int(row.strikes), known_pitch_types=set(encoder['pitch_labels']))
                # Request histories do not encode past pitcher IDs. Mask training
                # PAs with a pitcher change rather than normalize another pitcher
                # using the current pitcher's parameters.
                valid_history = history if all(pid == row.pitcher_id for pid in history_pitchers) else []
            except (SequenceValidationError, TypeError):
                valid_history = []
            ids.append([pmap.get(row.pitcher_id, 0), bmap.get(row.batter_id, 0)])
            contexts.append(context_row(row.pitcher_id, row.batter_id, row.balls, row.strikes, row.outs, int(row.bases), encoder))
            token_rows.append(tokens_for_history(valid_history, encoder, row.pitcher_id))
            lengths.append(len(valid_history))
            targets.append([labels.index(row.pitch_type), -1 if pd.isna(row.zone) else int(row.zone), HISTORY_RESULTS.index(row.result)])
            rows.append(row._asdict())
        history.append({'pitch_type': row.pitch_type, 'zone': None if pd.isna(row.zone) else int(row.zone),
                        'velocity': finite(row.velocity), 'result': row.result})
        history_pitchers.append(row.pitcher_id)
    if not rows:
        raise ValueError('No usable pre-2025 rows')
    targets = np.asarray(targets, dtype=np.int64)
    return FeatureBatch(np.asarray(ids, dtype=np.int64), np.asarray(contexts, dtype=np.float32),
                        np.asarray(token_rows, dtype=np.float32), np.asarray(lengths, dtype=np.int64),
                        targets[:, 0], targets[:, 1], targets[:, 2], pd.DataFrame(rows))


def request_batch(pid, bid, balls, strikes, outs, bases, sequence, encoder):
    summary = validate_sequence(sequence, balls, strikes, known_pitch_types=set(encoder['pitch_labels']))
    pmap = {value: i + 1 for i, value in enumerate(encoder['pitcher_ids'])}
    bmap = {value: i + 1 for i, value in enumerate(encoder['batter_ids'])}
    return FeatureBatch(np.asarray([[pmap.get(pid, 0), bmap.get(bid, 0)]], dtype=np.int64),
                        np.asarray([context_row(pid, bid, balls, strikes, outs, bases, encoder)], dtype=np.float32),
                        tokens_for_history(sequence, encoder, pid)[None], np.asarray([len(sequence)]),
                        np.asarray([-1]), np.asarray([-1]), np.asarray([-1]), pd.DataFrame()), summary
