"""Final-test access, frozen preprocessing/calibration and fair-mask contracts."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.final_evaluation import (FROZEN_SHA256, digest, frozen_baseline_probabilities,
                                  load_frozen_bundle, predict_final_frame, run, score)
from src.baseline import Baseline
from src.week2_features import build_batch, fit_encoder
from src.week2_training import baseline_probabilities


@pytest.fixture
def frozen():
    path = Path(__file__).resolve().parents[1] / 'artifacts/week2/model.json'
    if not path.exists():
        pytest.skip('Frozen full artifact not available')
    return load_frozen_bundle(path)[0]


def fixture_frame(model, year=2025):
    pid, bid = model['encoder']['pitcher_ids'][0], model['encoder']['batter_ids'][0]
    rows = []
    for side in ['away', 'home']:
        for event, result, balls, strikes in [(0, 'ball', 0, 0), (1, 'called_strike', 1, 0), (2, 'foul', 1, 1)]:
            rows.append({'game_id': 'fixture', 'side': side, 'pa_index': 0, 'event_index': event,
                         'date': f'{year}-04-01', 'year': year, 'split': 'test' if year == 2025 else 'train',
                         'pitcher_id': pid, 'batter_id': bid, 'pitcher_hand': 'R', 'batter_hand': 'L',
                         'state_valid': True, 'identity_valid': True, 'pitch_type': model['labels'][0],
                         'result': result, 'balls': balls, 'strikes': strikes, 'outs': 0, 'bases': 0,
                         'zone': 4., 'velocity': 140., 'coord_x': 0., 'coord_y': 0.})
    return pd.DataFrame(rows)


def test_final_access_is_explicit_and_preserves_identical_history_encoding(frozen):
    future = fixture_frame(frozen)
    previous = fixture_frame(frozen, 2024)
    with pytest.raises(ValueError, match='2025'):
        build_batch(future, frozen['encoder'])
    with pytest.raises(ValueError, match='pre-2025'):
        fit_encoder(future)
    with pytest.raises(ValueError, match='2025 test'):
        build_batch(previous, frozen['encoder'], final_test=True)
    mixed = pd.concat([future, previous], ignore_index=True)
    with pytest.raises(ValueError, match='2025 test'):
        build_batch(mixed, frozen['encoder'], final_test=True)
    with pytest.raises(ValueError, match='augment'):
        build_batch(future, frozen['encoder'], final_test=True, jitter=.1)
    test = build_batch(future, frozen['encoder'], final_test=True)
    train = build_batch(previous, frozen['encoder'])
    np.testing.assert_array_equal(test.tokens, train.tokens)
    np.testing.assert_array_equal(test.context, train.context)
    assert test.lengths.tolist() == [0, 1, 2, 0, 1, 2]


def test_bad_checksum_fails_before_final_dataset_is_read(tmp_path, monkeypatch):
    path = tmp_path / 'artifacts/week2/model.json'
    path.parent.mkdir(parents=True)
    path.write_text('{}', encoding='utf-8')
    def forbidden(*args, **kwargs):
        raise AssertionError('Test data must not be read before the freeze check')
    monkeypatch.setattr(pd, 'read_parquet', forbidden)
    with pytest.raises(ValueError, match='frozen week-two SHA'):
        run(tmp_path, tmp_path / 'report')


def test_final_predictions_never_fit_or_mutate_fixed_calibrators(frozen, monkeypatch):
    import src.week2_training as training
    def forbidden(*args, **kwargs):
        raise AssertionError('Final evaluation must not fit any model or calibration')
    for name in ['calibrate', 'fit_encoder', 'fit_result_values', 'train_lightgbm', 'train_gru']:
        monkeypatch.setattr(training, name, forbidden)
    before = digest(frozen['calibration']), digest(frozen['encoder'])
    frame = fixture_frame(frozen)
    frame.loc[1, 'zone'] = np.nan
    predictions, targets, metadata, lengths = predict_final_frame(frozen, frame, games_per_chunk=1)
    assert (digest(frozen['calibration']), digest(frozen['encoder'])) == before
    assert len(metadata) == 6 and lengths.tolist() == [0, 1, 2, 0, 1, 2]
    assert (targets['zone'] >= 0).sum() == 5
    assert (targets['conditional_result'] >= 0).sum() == 5
    assert (targets['result'] >= 0).sum() == 6
    for tasks in predictions.values():
        for values in tasks.values():
            np.testing.assert_allclose(values.sum(axis=1), 1, atol=2e-6)
    path = Path(__file__).resolve().parents[1] / 'artifacts/week2/model.json'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == FROZEN_SHA256


def test_frequency_comparators_match_the_frozen_week_two_formulas(frozen):
    batch = build_batch(fixture_frame(frozen), frozen['encoder'], final_test=True)
    for individual in [False, True]:
        expected = baseline_probabilities(Baseline(frozen['baseline']), batch, individual)
        actual = frozen_baseline_probabilities(Baseline(frozen['baseline']), batch, individual)
        for task in ['pitch', 'zone', 'result']:
            np.testing.assert_array_equal(actual[task], expected[task])


def test_conformal_uses_fixed_threshold_and_common_missing_target_mask():
    values = np.asarray([[.8, .2], [.3, .7], [.1, .9]])
    target = np.asarray([0, 0, -1])
    measured = score(values, target, threshold=.5)
    assert measured['n'] == 2
    assert measured['coverage'] == .5
    assert measured['mean_set_size'] == 1.
    assert measured['log_loss'] == pytest.approx(-np.log([.8, .3]).mean())
