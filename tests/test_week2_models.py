"""Leakage, time split and deployment export regression checks."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import hashlib
import json
from pathlib import Path

from src.week2_features import build_batch, fit_encoder, request_batch, tokens_for_history
from src.week2_model import Week2Model, conditional_distributions, raw_distributions
from src.week2_training import calibrate, classification_metrics, make_torch_model, torch_probabilities


def sample_frame():
    rows = []
    for side in ['away', 'home']:
        for event, result, balls, strikes in [(0, 'ball', 0, 0), (1, 'called_strike', 1, 0), (2, 'foul', 1, 1)]:
            rows.append({'game_id': 'game1', 'side': side, 'pa_index': 0, 'event_index': event,
                         'date': '2024-01-01', 'year': 2024, 'split': 'train', 'pitcher_id': 'P1', 'batter_id': 'B1',
                         'pitcher_hand': 'R', 'batter_hand': 'L', 'state_valid': True, 'identity_valid': True,
                         'pitch_type': 'FF', 'result': result, 'balls': balls, 'strikes': strikes,
                         'outs': 0, 'bases': 0, 'zone': 4., 'velocity': 140. + event,
                         'coord_x': 0., 'coord_y': 0.})
    return pd.DataFrame(rows)


def test_histories_do_not_join_same_pa_index_on_opposite_sides():
    frame = sample_frame()
    encoder = fit_encoder(frame)
    batch = build_batch(frame.sample(frac=1, random_state=3), encoder)
    assert batch.lengths.tolist() == [0, 1, 2, 0, 1, 2]
    assert batch.frame.side.tolist() == ['away'] * 3 + ['home'] * 3
    # Only a previous ball exists before the second row, never current strike.
    result_start = len(encoder['pitch_labels']) + 13
    assert batch.tokens[1, 0, result_start] == 1
    assert batch.tokens[1, 0, result_start + 1] == 0


def test_special_results_excluded_and_2025_refused():
    frame = sample_frame()
    encoder = fit_encoder(frame)
    frame.loc[0, 'result'] = 'hit_by_pitch'
    batch = build_batch(frame, encoder)
    assert len(batch.ids) == 5
    assert batch.lengths[0] == 0
    frame.loc[:, 'year'] = 2025
    with pytest.raises(ValueError, match='2025'):
        build_batch(frame, encoder)
    with pytest.raises(ValueError, match='2025'):
        fit_encoder(frame)


def test_pitcher_change_masks_unrepresentable_history():
    frame = sample_frame()
    frame.loc[1, 'pitcher_id'] = 'P2'
    encoder = fit_encoder(frame)
    batch = build_batch(frame, encoder)
    assert batch.lengths[:3].tolist() == [0, 0, 0]


def test_velocity_uses_train_only_group_mean_std_and_fallbacks():
    frame = pd.concat([sample_frame()] * 5, ignore_index=True)
    encoder = fit_encoder(frame)
    stats = encoder['velocity_stats']
    assert stats['pitcher_pitch_type']['P1|FF']['n'] == 30
    history = [{'pitch_type': 'FF', 'zone': None, 'velocity': 144., 'result': 'ball'}]
    token = tokens_for_history(history, encoder, 'P1')
    assert token[0, -2] == pytest.approx(1.)  # train mean141, stdfloor3
    unseen = tokens_for_history(history, encoder, 'NEW')
    np.testing.assert_array_equal(token, unseen)  # pitch-type fallback
    history[0]['velocity'] = None
    missing = tokens_for_history(history, encoder, 'P1')
    assert missing[0, -2:].tolist() == [0., 1.]


def test_request_and_training_history_encoding_match():
    frame = sample_frame()
    encoder = fit_encoder(frame)
    train = build_batch(frame, encoder)
    history = [{'pitch_type': 'FF', 'zone': 4, 'velocity': 140., 'result': 'ball'}]
    request, _ = request_batch('P1', 'B1', 1, 0, 0, 0, history, encoder)
    np.testing.assert_array_equal(train.tokens[1], request.tokens[0])
    np.testing.assert_array_equal(train.context[1], request.context[0])


def test_numpy_gru_export_matches_torch_all_heads_and_empty_history():
    torch = pytest.importorskip('torch')
    frame = sample_frame()
    encoder = fit_encoder(frame)
    batch = build_batch(frame, encoder)
    torch.manual_seed(42)
    network = make_torch_model(encoder)
    payload = {'family': 'gru', 'config': {'sequence': True, 'shrinkage': True, 'hidden_size': 32,
                                          'pitch_classes': 1},
               'weights': {name: value.detach().numpy().tolist() for name, value in network.state_dict().items()}}
    reference = torch_probabilities(network, batch)
    deployed = raw_distributions(payload, batch)
    deployed['conditional_result'] = conditional_distributions(payload, batch, batch.pitch, batch.zone)
    for task in deployed:
        np.testing.assert_allclose(deployed[task], reference[task], rtol=1e-5, atol=2e-6)
        np.testing.assert_allclose(deployed[task].sum(axis=1), 1, atol=1e-6)


def test_metrics_mask_missing_zone_and_ece():
    metrics = classification_metrics(np.asarray([[.9, .1], [.1, .9], [.4, .6]]), np.asarray([0, 1, -1]))
    assert metrics['n'] == 2
    assert metrics['log_loss'] == pytest.approx(-np.log(.9))
    assert metrics['ece'] == pytest.approx(.1)


def test_calibration_dates_are_disjoint_and_small_sample_quantile_is_conservative(monkeypatch):
    from src.week2_features import FeatureBatch
    frame = pd.DataFrame({'date': np.repeat(pd.date_range('2024-09-12', periods=10).strftime('%Y-%m-%d'), 2),
                          'game_id': np.repeat(np.arange(10).astype(str), 2)})
    n = len(frame)
    batch = FeatureBatch(np.zeros((n, 2), dtype=np.int64), np.zeros((n, 10), dtype=np.float32),
                         np.zeros((n, 16, 21), dtype=np.float32), np.zeros(n, dtype=np.int64),
                         np.zeros(n, dtype=np.int64), np.zeros(n, dtype=np.int64), np.zeros(n, dtype=np.int64), frame)
    def uniform(_payload, part):
        return {'pitch': np.full((len(part.ids), 2), .5), 'zone': np.full((len(part.ids), 13), 1 / 13),
                'result': np.full((len(part.ids), 5), .2)}
    monkeypatch.setattr('src.week2_training.raw_distributions', uniform)
    monkeypatch.setattr('src.week2_training.conditional_distributions',
                        lambda _payload, part, _pitch, _zone: np.full((len(part.ids), 5), .2))
    result = calibrate({}, batch)
    dates = [set(result['split'][part]['dates']) for part in ['temperature', 'conformal', 'audit']]
    assert not dates[0] & dates[1] and not dates[0] & dates[2] and not dates[1] & dates[2]
    assert result['audit']['pitch']['conformal_n'] == 6
    assert result['audit']['pitch']['finite_sample_rank'] == 7
    assert result['thresholds']['pitch'] == 1.
    assert result['audit']['pitch']['coverage'] == 1.
    assert result['audit']['pitch']['mean_set_size'] == 2.


def test_real_export_checksum_calibration_and_sequence_effect():
    path = Path(__file__).resolve().parents[1] / 'artifacts/week2/model.json'
    if not path.exists():
        pytest.skip('Full training artifact is not present')
    manifest = json.loads(path.with_name('manifest.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest['sha256']
    assert manifest['test_evaluated'] is False
    model = Week2Model.load(path)
    assert model.model['model_format'] == 'week2-v1'
    assert model.model['estimator']['config'].get('threads', 1) == 1
    assert model.model['model_info']['test_evaluated'] is False
    pid = max(model.baseline.model['pitch_player'], key=lambda p: sum(model.baseline.model['pitch_player'][p].values()))
    bid = max(model.baseline.model['batter_counts'], key=model.baseline.model['batter_counts'].get)
    ball = {'pitch_type': model.labels[0], 'zone': 4, 'velocity': None, 'result': 'ball'}
    strike = dict(ball, result='called_strike')
    first = model.predict(pid, bid, 1, 1, 0, 0, [ball, strike])
    second = model.predict(pid, bid, 1, 1, 0, 0, [strike, ball])
    for name in ['pitch_probabilities', 'zone_probabilities', 'result_probabilities']:
        assert sum(item['probability'] for item in first[name]) == pytest.approx(1., abs=1e-6)
    if model.model['capabilities']['sequence']:
        assert first['history_summary']['sequence_used'] is True
        assert max(abs(a['probability'] - b['probability']) for a, b in
                   zip(first['pitch_probabilities'], second['pitch_probabilities'])) > 1e-7
    values = [item['expected_run_change'] for item in first['recommendations']]
    assert values == sorted(values)
    for item in first['recommendations']:
        assert item['causal'] is False
        assert item['pitch_type'] in model.baseline.model['pitch_player'][pid]
        assert item['pooled_sample_count'] >= 10
    for task in ['pitch', 'zone', 'result']:
        assert first['prediction_sets'][task]['target_coverage'] == .9
        assert first['prediction_sets'][task]['threshold'] == model.model['calibration']['thresholds'][task]
