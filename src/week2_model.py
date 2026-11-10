"""Small deployable LightGBM/NumPy-GRU inference, without a PyTorch runtime."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.baseline import Baseline, distribution, key
from src.domain import PITCH_NAMES, RESULTS, ZONE_NAMES
from src.week2_features import request_batch


def softmax(logits):
    logits = np.asarray(logits, dtype=np.float32)
    shifted = logits - logits.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True)


def normalize(probabilities):
    values = np.maximum(np.asarray(probabilities, dtype=np.float64), 1e-10)
    return values / values.sum(axis=-1, keepdims=True)


def temperature_scale(probabilities, temperature):
    return softmax(np.log(np.clip(probabilities, 1e-10, 1)) / temperature).astype(float)


def numpy_gru_context(payload, batch):
    """Match PyTorch GRU's r,z,n gate order, including its reset-after equation."""
    w = {name: np.asarray(value, dtype=np.float32) for name, value in payload['weights'].items()}
    gates = batch.context[:, -2:].copy()
    if not payload['config']['shrinkage']:
        gates = (batch.ids > 0).astype(np.float32)
    ep = w['pitcher_embedding.weight'][batch.ids[:, 0]] * gates[:, :1]
    eb = w['batter_embedding.weight'][batch.ids[:, 1]] * gates[:, 1:]
    hidden = np.zeros((len(batch.ids), payload['config']['hidden_size']), dtype=np.float32)
    lengths = batch.lengths if payload['config']['sequence'] else np.zeros_like(batch.lengths)
    wi, wh = w['gru.weight_ih_l0'], w['gru.weight_hh_l0']
    bi, bh = w['gru.bias_ih_l0'], w['gru.bias_hh_l0']
    for step in range(int(lengths.max(initial=0))):
        ir, iz, inn = np.split(batch.tokens[:, step] @ wi.T + bi, 3, axis=1)
        hr, hz, hn = np.split(hidden @ wh.T + bh, 3, axis=1)
        reset = 1 / (1 + np.exp(-np.clip(ir + hr, -60, 60)))
        update = 1 / (1 + np.exp(-np.clip(iz + hz, -60, 60)))
        candidate = np.tanh(inn + reset * hn)
        next_hidden = (1 - update) * candidate + update * hidden
        hidden = np.where((step < lengths)[:, None], next_hidden, hidden)
    joined = np.column_stack([batch.context, ep, eb, hidden])
    return np.maximum(joined @ w['trunk.weight'].T + w['trunk.bias'], 0), w


def raw_distributions(payload, batch):
    if payload['family'] == 'lightgbm':
        import lightgbm as lgb
        models = payload.get('_boosters')
        if models is None:
            models = {task: lgb.Booster(model_str=content) for task, content in payload['models'].items()}
            payload['_boosters'] = models
        x = batch.lgb_features(payload['config']['sequence'])
        return {task: normalize(models[task].predict(x, num_threads=payload['config'].get('threads', 1)))
                for task in ['pitch', 'zone', 'result']}
    features, weights = numpy_gru_context(payload, batch)
    return {task: softmax(features @ weights[task + '_head.weight'].T + weights[task + '_head.bias'])
            for task in ['pitch', 'zone', 'result']}


def conditional_distributions(payload, batch, pitches, zones):
    """Candidate action enters only the result-given-action head."""
    pitch_count = payload['config']['pitch_classes']
    actions = np.column_stack([np.eye(pitch_count, dtype=np.float32)[pitches],
                               np.eye(13, dtype=np.float32)[zones]])
    if payload['family'] == 'lightgbm':
        import lightgbm as lgb
        booster = payload.get('_conditional_booster')
        if booster is None:
            booster = lgb.Booster(model_str=payload['models']['conditional_result'])
            payload['_conditional_booster'] = booster
        x = np.column_stack([batch.lgb_features(payload['config']['sequence']), actions])
        return normalize(booster.predict(x, num_threads=payload['config'].get('threads', 1)))
    features, weights = numpy_gru_context(payload, batch)
    joined = np.column_stack([features, actions])
    return softmax(joined @ weights['conditional_head.weight'].T + weights['conditional_head.bias'])


class Week2Model:
    def __init__(self, model):
        self.model = model
        self.labels = model['labels']
        self.encoder = model['encoder']
        self.result_labels = model['result_labels']
        self.payload = model['estimator']
        self.baseline = Baseline(model['baseline'])
        self.pitchers = self.baseline.pitchers
        self.batters = self.baseline.batters
        if self.payload['family'] == 'lightgbm':
            import lightgbm as lgb
            self.payload['_boosters'] = {task: lgb.Booster(model_str=self.payload['models'][task])
                                         for task in ['pitch', 'zone', 'result']}
            self.payload['_conditional_booster'] = lgb.Booster(model_str=self.payload['models']['conditional_result'])

    @classmethod
    def fromdict(cls, model):
        return cls(model)

    @classmethod
    def load(cls, path: Path):
        return cls(json.loads(Path(path).read_text(encoding='utf-8')))

    def distribution_batch(self, batch, calibrated=True):
        probabilities = raw_distributions(self.payload, batch)
        if calibrated:
            temperatures = self.model.get('calibration', {}).get('temperature', {})
            probabilities = {task: temperature_scale(p, temperatures.get(task, 1.0)) for task, p in probabilities.items()}
        return probabilities

    def recommend(self, batch, pitcher_id, balls, strikes, outs, bases):
        baseline = self.baseline.model
        candidates = [(pitch, zone, action) for pitch, count in baseline['pitch_player'].get(pitcher_id, {}).items()
                      if count >= 5 and pitch in self.labels for zone in range(13)
                      if (action := baseline['action_values'].get(key(pitch, zone))) and action[0] >= 10]
        if not candidates:
            return []
        repeated = batch.subset(np.zeros(len(candidates), dtype=int)) if len(batch.frame) else None
        # Request batches have no dataframe rows; repeat the arrays directly.
        if repeated is None:
            from src.week2_features import FeatureBatch
            repeated = FeatureBatch(*(np.repeat(getattr(batch, name), len(candidates), axis=0)
                                      for name in ['ids', 'context', 'tokens', 'lengths', 'pitch', 'zone', 'result']),
                                    batch.frame)
        result_p = conditional_distributions(self.payload, repeated,
                                            np.asarray([self.labels.index(item[0]) for item in candidates]),
                                            np.asarray([item[1] for item in candidates]))
        result_p = temperature_scale(result_p, self.model.get('calibration', {}).get('temperature', {}).get('conditional_result', 1.))
        value_info = self.model['result_values']
        values = np.asarray(value_info['by_state'].get(key(balls, strikes, outs, bases), value_info['global']))
        predictions = []
        for (pitch, zone, action), probability in zip(candidates, result_p):
            support = baseline['pitcher_action_values'].get(key(pitcher_id, pitch, zone, balls, strikes), [0, 0])[0]
            predictions.append({'pitch_type': pitch, 'zone': zone,
                                'expected_run_change': round(float(probability @ values), 5),
                                'direct_sample_count': support, 'pooled_sample_count': action[0],
                                'support': 'pooled' if support < 20 else 'historical',
                                'result_probabilities': [{'result': label, 'probability': float(p)} for label, p in zip(self.result_labels, probability)],
                                'method': 'conditional_result_times_train_only_delta_re', 'causal': False})
        return sorted(predictions, key=lambda item: item['expected_run_change'])[:5]

    def predict(self, pitcher_id, batter_id, balls, strikes, outs, bases, sequence=None):
        batch, history = request_batch(pitcher_id, batter_id, balls, strikes, outs, bases, sequence or [], self.encoder)
        probabilities = {name: values[0] for name, values in self.distribution_batch(batch).items()}
        m, baseline = self.model, self.baseline.model
        counts = {'pitcher': sum(baseline['pitch_player'].get(pitcher_id, {}).values()),
                  'batter': baseline['batter_counts'].get(batter_id, 0),
                  'matchup': baseline['matchup_counts'].get(key(pitcher_id, batter_id), 0),
                  'league_state': baseline['state_counts'].get(key(balls, strikes, outs, bases), 0)}
        calibration = m.get('calibration', {})
        prediction_sets = {}
        for task, labels in [('pitch', self.labels), ('zone', list(range(13))), ('result', self.result_labels)]:
            threshold = calibration.get('thresholds', {}).get(task)
            included = [] if threshold is None else [label for label, p in zip(labels, probabilities[task]) if 1 - p <= threshold]
            prediction_sets[task] = {'labels': included, 'target_coverage': 0.9, 'threshold': threshold}
        warnings = ['推薦依歷史觀察關聯與訓練期得分期望，不代表因果或保證最優配球。',
                    '90%預測集合僅在保留校準稽核資料量測；時間漂移可能使實際覆蓋率改變。',
                    '候選配球的條件結果頭另作溫度校準；主結果頭的90%集合不代表候選配球的成功率。',
                    '歷程假設來自同一位當前投手；打席中換投時請清空歷程，僅使用目前情境。']
        if not history['provided']:
            warnings.append('未提供本打席先前投球；使用情境、投打身分與空歷史特徵。')
        if counts['matchup'] < 30:
            warnings.append('直接對戰樣本少於30球，請參考投打整體樣本及校準集合。')
        return {'pitch_probabilities': [{'pitch_type': t, 'name': PITCH_NAMES[t], 'probability': float(p)} for t, p in zip(self.labels, probabilities['pitch'])],
                'zone_probabilities': [{'zone': z, 'name': ZONE_NAMES[z], 'probability': float(p)} for z, p in enumerate(probabilities['zone'])],
                'result_probabilities': [{'result': r, 'probability': float(p)} for r, p in zip(self.result_labels, probabilities['result'])],
                'recommendations': self.recommend(batch, pitcher_id, balls, strikes, outs, bases),
                'sample_counts': counts, 'warnings': warnings, 'prediction_sets': prediction_sets,
                'prediction_set': prediction_sets['pitch']['labels'], 'calibration': calibration,
                'history_summary': dict(history, sequence_used=bool(history['provided'] and m['capabilities']['sequence'])),
                'model_info': m['model_info'], 'model_version': m['model_version'], 'data_version': m['data_version'],
                'data_cutoff': m['data_cutoff'], 'model_name': m['model_name'], 'capabilities': m['capabilities'],
                'source_mode': 'local_snapshot'}
