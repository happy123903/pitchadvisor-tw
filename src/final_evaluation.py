"""One-way final test of the frozen week-two artifact, without fitting anything."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.baseline import Baseline, distribution, key
from src.week2_features import HISTORY_RESULTS, build_batch
from src.week2_model import Week2Model, conditional_distributions, temperature_scale
from src.week2_training import classification_metrics

FROZEN_SHA256 = 'aa3e984758796843bce68aa71fb06a4c84739a7d8048be475cc1bfe6855671ec'
TASKS = ('pitch', 'zone', 'result', 'conditional_result')
MODELS = ('selected_calibrated', 'selected_raw', 'league_count', 'pitcher_count_shrunk')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))


def load_frozen_bundle(path):
    """This check must precede any read of final-test rows."""
    raw = Path(path).read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    if checksum != FROZEN_SHA256:
        raise ValueError('Final evaluation requires the frozen week-two SHA-256')
    model = json.loads(raw)
    manifest = json.loads(Path(path).with_name('manifest.json').read_text(encoding='utf-8'))
    if manifest['sha256'] != checksum or manifest['model_version'] != model['model_version']:
        raise ValueError('Frozen model and manifest disagree')
    if model['model_version'] != 'week2-sequence-v1' or model['data_cutoff'] != '2024-08-14':
        raise ValueError('Final evaluation requires the fixed model version and training cutoff')
    return model, {'model_version': model['model_version'], 'sha256': checksum,
                   'data_cutoff': model['data_cutoff'], 'data_version': model['data_version'],
                   'calibration_sha256': digest(model['calibration']),
                   'encoder_sha256': digest(model['encoder']),
                   'baseline_sha256': digest(model['baseline']),
                   'frozen_before_test_read': datetime.now(timezone.utc).isoformat()}


def frozen_baseline_probabilities(baseline, batch, individual):
    """Exact week-two comparison formulas, with caches for repeated states.

    The legacy model has seven result classes. Comparisons condition its frozen
    counts on the same five supported outcomes as the selected model. The legacy
    conditional head uses its frozen count/pitch/zone result table, with count
    prior. No batter or 2025 statistics are added.
    """
    model, labels = baseline.model, baseline.labels
    global_result = distribution(model['result_global'], HISTORY_RESULTS)
    result_prior, pitches, zones, actions = {}, {}, {}, {}
    output = {task: [] for task in TASKS}
    for row in batch.frame.itertuples(index=False):
        state = (row.balls, row.strikes)
        person_state = (row.pitcher_id, *state)
        if state not in result_prior:
            result_prior[state] = distribution(model['result_count'].get(key(*state), {}), HISTORY_RESULTS, global_result)
        if person_state not in pitches:
            pitches[person_state] = baseline.pitch_distribution(row.pitcher_id, *state, individual=individual)
        if person_state not in zones:
            zones[person_state] = sum(probability * baseline.zone_distribution(row.pitcher_id, label)
                                      for probability, label in zip(pitches[person_state], labels))
        action = (*state, row.pitch_type, 0 if pd.isna(row.zone) else int(row.zone))
        if action not in actions:
            actions[action] = distribution(model['result_action'].get(key(*action), {}), HISTORY_RESULTS,
                                            result_prior[state])
        output['pitch'].append(pitches[person_state])
        output['zone'].append(zones[person_state])
        output['result'].append(result_prior[state])
        output['conditional_result'].append(actions[action])
    return {task: np.asarray(values) for task, values in output.items()}


def score(probabilities, target, threshold=None):
    p, y = np.asarray(probabilities), np.asarray(target)
    if not np.isfinite(p).all() or (p < 0).any() or not np.allclose(p.sum(axis=1), 1, atol=2e-6):
        raise ValueError('Non-finite or invalid final-test probability distribution')
    result = classification_metrics(p, y)
    good = y >= 0
    if threshold is not None and good.any():
        included = 1 - p[good] <= threshold
        result.update(coverage=float(included[np.arange(good.sum()), y[good]].mean()),
                      mean_set_size=float(included.sum(axis=1).mean()))
    else:
        result.update(coverage=None, mean_set_size=None)
    return result


def evaluate_predictions(model, scores, targets, mask):
    thresholds = model['calibration']['thresholds']
    return {name: {task: score(scores[name][task][mask], targets[task][mask],
                              thresholds.get(task) if name == 'selected_calibrated' else None)
                   for task in TASKS} for name in MODELS}


def training_groups(frame, lengths, model):
    encoder, baseline = model['encoder'], model['baseline']
    pc = frame.pitcher_id.map(encoder['pitcher_counts']).fillna(0).to_numpy()
    bc = frame.batter_id.map(encoder['batter_counts']).fillna(0).to_numpy()
    mc = np.asarray([baseline['matchup_counts'].get(key(pid, bid), 0)
                     for pid, bid in zip(frame.pitcher_id, frame.batter_id)])
    return {'pitcher_unseen': pc == 0, 'pitcher_1_99': (pc > 0) & (pc < 100),
            'pitcher_100_499': (pc >= 100) & (pc < 500), 'pitcher_500_plus': pc >= 500,
            'batter_unseen': bc == 0, 'batter_1_99': (bc > 0) & (bc < 100),
            'batter_100_499': (bc >= 100) & (bc < 500), 'batter_500_plus': bc >= 500,
            'matchup_unseen': mc == 0, 'matchup_1_29': (mc > 0) & (mc < 30),
            'matchup_30_99': (mc >= 30) & (mc < 100), 'matchup_100_plus': mc >= 100,
            'history_empty': lengths == 0, 'history_available': lengths > 0}


def predict_final_frame(model, frame, *, games_per_chunk=12):
    if frame.empty or not frame.year.eq(2025).all() or not frame.split.eq('test').all():
        raise ValueError('Final evaluation accepts only the 2025 test partition')
    estimator, baseline = Week2Model.fromdict(model), Baseline(model['baseline'])
    all_scores = {name: {task: [] for task in TASKS} for name in MODELS}
    all_targets, all_frames, all_lengths = {task: [] for task in TASKS}, [], []
    games = sorted(frame.game_id.unique())
    for start in range(0, len(games), games_per_chunk):
        part = frame.loc[frame.game_id.isin(games[start:start + games_per_chunk])]
        try:
            batch = build_batch(part, model['encoder'], final_test=True)
        except ValueError as error:
            if str(error) != 'No usable evaluation rows':
                raise
            continue
        raw = estimator.distribution_batch(batch, calibrated=False)
        raw['conditional_result'] = conditional_distributions(estimator.payload, batch, batch.pitch, np.maximum(batch.zone, 0))
        calibrated = {task: temperature_scale(values, model['calibration']['temperature'][task])
                      for task, values in raw.items()}
        predictions = {'selected_raw': raw, 'selected_calibrated': calibrated,
                       'league_count': frozen_baseline_probabilities(baseline, batch, False),
                       'pitcher_count_shrunk': frozen_baseline_probabilities(baseline, batch, True)}
        for name in MODELS:
            for task in TASKS:
                all_scores[name][task].append(predictions[name][task])
        for task in TASKS:
            target = batch.result.copy() if task == 'conditional_result' else getattr(batch, task)
            if task == 'conditional_result':
                target[batch.zone < 0] = -1
            all_targets[task].append(target)
        all_frames.append(batch.frame[['date', 'game_id', 'pitcher_id', 'batter_id', 'zone']])
        all_lengths.append(batch.lengths)
        print(f'Final evaluation: {min(start + games_per_chunk, len(games))}/{len(games)} complete games', flush=True)
    if not all_frames:
        raise ValueError('No supported final-test rows')
    return ({name: {task: np.concatenate(values) for task, values in tasks.items()}
             for name, tasks in all_scores.items()},
            {task: np.concatenate(values) for task, values in all_targets.items()},
            pd.concat(all_frames, ignore_index=True), np.concatenate(all_lengths))


def exclusion_counts(frame, labels):
    conditions = [('invalid_state', frame.state_valid.fillna(False).astype(bool)),
                  ('invalid_identity', frame.identity_valid.fillna(False).astype(bool)),
                  ('unsupported_pitch_type', frame.pitch_type.isin(labels)),
                  ('unsupported_result', frame.result.isin(HISTORY_RESULTS))]
    remaining = np.ones(len(frame), dtype=bool)
    priority, overlapping = {}, {}
    for name, condition in conditions:
        good = condition.to_numpy()
        priority[name] = int((remaining & ~good).sum())
        overlapping[name] = int((~good).sum())
        remaining &= good
    return {'priority_disjoint': priority, 'overlapping_flags': overlapping,
            'unsupported_result_values': frame.loc[~frame.result.isin(HISTORY_RESULTS), 'result'].fillna('<missing>').value_counts().astype(int).to_dict(),
            'unsupported_pitch_values': frame.loc[~frame.pitch_type.isin(labels), 'pitch_type'].fillna('<missing>').value_counts().astype(int).to_dict()}


def run(root, report_dir):
    root, report_dir = Path(root), Path(report_dir)
    started = time.perf_counter()
    model_path = root / 'artifacts/week2/model.json'
    model, frozen = load_frozen_bundle(model_path)
    # Persist the freeze evidence before the first read of the test partition.
    write_json(report_dir / 'freeze_before_final_test.json', frozen)
    frame = pd.read_parquet(root / 'data/processed/pitches.parquet', filters=[('year', '==', 2025)])
    predictions, targets, metadata, lengths = predict_final_frame(model, frame)
    all_rows = np.ones(len(metadata), dtype=bool)
    pitchers = {p['id'] for p in model['players'] if p['role'] == 'pitcher'}
    batters = {p['id'] for p in model['players'] if p['role'] == 'batter'}
    servable = (metadata.pitcher_id.isin(pitchers) & metadata.batter_id.isin(batters)).to_numpy()
    groups = training_groups(metadata, lengths, model)
    months = sorted(metadata.date.str[:7].unique())
    selected_all = evaluate_predictions(model, predictions, targets, all_rows)
    cohort = {'raw_rows': len(frame), 'usable_rows': len(metadata),
              'excluded_rows': len(frame) - len(metadata),
              'catalog_serving_rows': int(servable.sum()), 'outside_catalog_rows': int((~servable).sum()),
              'games': int(frame.game_id.nunique()), 'usable_games': int(metadata.game_id.nunique()),
              'missing_zone_targets': int((targets['zone'] < 0).sum()),
              'history_empty': int((lengths == 0).sum()), 'history_available': int((lengths > 0).sum()),
              'exclusions': exclusion_counts(frame, model['labels'])}
    if cohort['usable_rows'] != cohort['raw_rows'] - sum(cohort['exclusions']['priority_disjoint'].values()):
        raise AssertionError('Evaluation rows differ from the declared common sample mask')
    report = {'schema_version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(),
              'test_evaluated': True, 'frozen_bundle': frozen,
              'period': {'start': str(frame.date.min()), 'end': str(frame.date.max()), 'year': 2025},
              'protocol': {'model_selected_using': '2024 validation only; no 2025-based reselection',
                           'training_or_calibration_performed': False,
                           'calibration': 'fixed temperatures and thresholds from the frozen bundle',
                           'feature_history': 'shared build_batch; full game chunks; same PA/side/previous pitches; no augmentation',
                           'labels': {'pitch': model['labels'], 'zone': list(range(13)), 'result': model['result_labels']},
                           'common_row_mask': 'valid state and identity; known pitch type; one of five supported outcomes',
                           'zone_and_conditional_mask': 'common rows with a recorded zone',
                           'result_baseline_projection': 'frozen seven-class count tables conditioned on the same five result labels',
                           'baseline_zone': 'as in week two: both frequency baselines mix frozen pitcher/type zone estimates using their respective pitch probabilities',
                           'baseline_conditional_result': 'frozen count/pitch/zone result_action table, alpha30 and frozen count-result prior; same for both baselines',
                           'ece': '15 equal-width confidence bins, top-label absolute calibration error',
                           'conformal': '1-p <= frozen threshold; no threshold fitting or correction on final test'},
              'cohort': cohort,
              'all_supported_rows': selected_all,
              'catalog_serving_rows': evaluate_predictions(model, predictions, targets, servable),
              'outside_catalog_rows': evaluate_predictions(model, predictions, targets, ~servable),
              'training_count_groups': {name: evaluate_predictions(model, predictions, targets, mask)
                                        for name, mask in groups.items()},
              'monthly': {month: evaluate_predictions(model, predictions, targets, metadata.date.str.startswith(month).to_numpy())
                          for month in months},
              'frozen_calibration_audit': model['calibration']['audit'],
              'calibration_audit_to_test': {task: {
                  'audit_n': model['calibration']['audit'][task]['n'],
                  'test_n': selected_all['selected_calibrated'][task]['n'],
                  'log_loss_change': selected_all['selected_calibrated'][task]['log_loss'] - model['calibration']['audit'][task]['log_loss_after'],
                  'ece_change': selected_all['selected_calibrated'][task]['ece'] - model['calibration']['audit'][task]['ece_after'],
                  'coverage_change': None if task == 'conditional_result' else selected_all['selected_calibrated'][task]['coverage'] - model['calibration']['audit'][task]['coverage']}
                  for task in TASKS},
              'limitations': [
                  'Final test is a retrospective 2025 regular-season cohort, not a future-performance guarantee.',
                  'Temporal drift and correlated pitches can invalidate exchangeability assumptions; nominal 90% is not guaranteed.',
                  'All-supported metrics include unseen player IDs with frozen unknown-ID features; the public API accepts only the frozen catalog. Catalog-serving metrics are reported separately.',
                  'Hit-by-pitch and other outcomes outside the five-class task are excluded and counted. Missing zones mask only zone and conditional-result evaluation.',
                  'Recorded pitch location is an observed outcome, not the intended target. Conditional-result accuracy on observed actions does not establish causal recommendation benefit.',
                  'Calibration-audit versus final-test changes compare different time cohorts; they do not isolate the cause of drift.',
                  'Frozen model metadata retains test_evaluated=false as historical training provenance; this separate report records the later final evaluation.'],
              'duration_seconds': time.perf_counter() - started}
    # Runtime caches are harmless, but the fixed preprocessing/calibrators and
    # artifact bytes must be unchanged even after every final-test prediction.
    after = hashlib.sha256(model_path.read_bytes()).hexdigest()
    if after != frozen['sha256'] or digest(model['calibration']) != frozen['calibration_sha256'] or digest(model['encoder']) != frozen['encoder_sha256']:
        raise AssertionError('Frozen artifact, calibration or encoder changed during final evaluation')
    report['immutability_verified_after'] = {'bundle_sha256': after, 'calibration_sha256': digest(model['calibration']),
                                              'encoder_sha256': digest(model['encoder']), 'unchanged': True}
    write_json(report_dir / 'final_evaluation.json', report)
    public = {'schema_version': 1, 'test_evaluated': True,
              'frozen_bundle': {k: frozen[k] for k in ['model_version', 'sha256', 'data_cutoff']},
              'period': report['period'],
              'sample_counts': {'raw': cohort['raw_rows'], 'usable': cohort['usable_rows'],
                                'catalog_serving': cohort['catalog_serving_rows'],
                                'outside_catalog': cohort['outside_catalog_rows'], 'missing_zone': cohort['missing_zone_targets']},
              'selected': selected_all['selected_calibrated'],
              'baselines': {name: selected_all[name] for name in ['league_count', 'pitcher_count_shrunk']},
              'catalog_serving': {'selected': report['catalog_serving_rows']['selected_calibrated'],
                                  'baselines': {name: report['catalog_serving_rows'][name] for name in ['league_count', 'pitcher_count_shrunk']}},
              'limitations': report['limitations']}
    write_json(report_dir / 'final_evaluation_public.json', public)
    write_report(report, report_dir)
    print(json.dumps(public, ensure_ascii=False), flush=True)
    return report


def write_report(report, directory):
    directory = Path(directory)
    def number(value, percent=False):
        return '—' if value is None else (f'{value:.2%}' if percent else f'{value:.6f}')
    lines = ['# 2025 凍結模型最終測試', '', '執行日期：2026-11-11。此報告在第二週選模與校準完成後才開啟 2025 最終測試；未重訓、選模、重估溫度或 conformal 分位數。', '',
             f'凍結版本：`{report["frozen_bundle"]["model_version"]}`；訓練截止 `{report["frozen_bundle"]["data_cutoff"]}`。', '',
             f'SHA-256：`{report["frozen_bundle"]["sha256"]}`。第一次讀取測試資料前寫入 [凍結紀錄](freeze_before_final_test.json)，推論後再確認模型位元組、encoder 與校準器未變。', '',
             '## 樣本與遮罩', '',
             f'測試期間 `{report["period"]["start"]}` 至 `{report["period"]["end"]}`，{report["cohort"]["games"]:,} 場，原始 {report["cohort"]["raw_rows"]:,} 球，共同可用 {report["cohort"]["usable_rows"]:,} 球。', '',
             f'凍結 API 名單內投打組合 {report["cohort"]["catalog_serving_rows"]:,} 球；名單外 {report["cohort"]["outside_catalog_rows"]:,} 球亦以未知 ID 特徵評估，但線上 API 不開放未知 ID。缺少落點 {report["cohort"]["missing_zone_targets"]:,} 球只遮罩分區與條件結果任務。', '',
             '| 排除原因（依序、互斥） | 球數 |', '|---|---:|']
    for name, value in report['cohort']['exclusions']['priority_disjoint'].items():
        lines.append(f'| {name} | {value:,} |')
    lines += ['', '特殊結果原值：`' + json.dumps(report['cohort']['exclusions']['unsupported_result_values'], ensure_ascii=False) + '`。完整重疊旗標與未知球種計數見 JSON。', '',
              '所有模型在同一批列／目標遮罩上比較；基準的七類結果頻率投影至相同五類。ECE 使用 15 個等寬信心區間；log loss 為 nats，越低越好。條件結果 head 只評估已觀測球種與落點，不是推薦換球後的因果收益。', '',
              '## 全部共同可用樣本', '', '| 模型 | 任務 | n | log loss | top-1 | top-2 | ECE | 90% 集合覆蓋率 | 平均集合大小 |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for name, tasks in report['all_supported_rows'].items():
        for task, metric in tasks.items():
            lines.append(f'| {name} | {task} | {metric["n"]:,} | {number(metric["log_loss"])} | {number(metric["top1_accuracy"], True)} | {number(metric["top2_accuracy"], True)} | {number(metric["ece"])} | {number(metric["coverage"], True)} | {number(metric["mean_set_size"])} |')
    selected = report['all_supported_rows']['selected_calibrated']
    base = report['all_supported_rows']['pitcher_count_shrunk']
    gain = 1 - selected['pitch']['log_loss'] / base['pitch']['log_loss']
    catalog = report['catalog_serving_rows']
    catalog_gain = 1 - catalog['selected_calibrated']['pitch']['log_loss'] / catalog['pitcher_count_shrunk']['pitch']['log_loss']
    unseen = report['training_count_groups']['pitcher_unseen']['selected_calibrated']['pitch']
    lines += ['', f'球種 log loss 相對投手頻率基準變化為 **{-gain:+.2%}**（負值代表改善）；這是已凍結模型的最終測試結果，沒有依此改選模型。', '',
              f'**不能宣稱全面優於投手基準**：全部可用列的球種 log loss 較差，但名單內子集改善 {catalog_gain:.2%}；top-1 與機率品質反映不同面向。訓練未見投手 {unseen["n"]:,} 球的固定集合覆蓋率只有 {unseen["coverage"]:.2%}，顯示未知 ID 路徑的限制。名單內子集也不是新測試集，不能用來隱藏全部樣本的退步。', '',
              '![最終測試與月別覆蓋率](final_test_summary.png)', '', '## 線上名單內子集', '',
              '| 模型 | 球種 n | 球種 log loss | 球種 top-1 | 分區 log loss | 結果 log loss |', '|---|---:|---:|---:|---:|---:|']
    for name, tasks in report['catalog_serving_rows'].items():
        lines.append(f'| {name} | {tasks["pitch"]["n"]:,} | {number(tasks["pitch"]["log_loss"])} | {number(tasks["pitch"]["top1_accuracy"], True)} | {number(tasks["zone"]["log_loss"])} | {number(tasks["result"]["log_loss"])} |')
    lines += ['', '## 訓練期樣本數與 OOD 分組', '', '分組只由凍結 encoder 與 baseline 訓練期計數定義，沒有累加 2025 次數。直接對戰使用原基準訓練球數；特殊結果是否納入依凍結原表，不重算。空組保留 n=0。', '',
              '| 分組 | 球種 n | 球種 log loss | 球種 top-1 | 球種集合覆蓋 | 分區覆蓋 | 結果覆蓋 |', '|---|---:|---:|---:|---:|---:|---:|']
    for name, models in report['training_count_groups'].items():
        tasks = models['selected_calibrated']
        lines.append(f'| {name} | {tasks["pitch"]["n"]:,} | {number(tasks["pitch"]["log_loss"])} | {number(tasks["pitch"]["top1_accuracy"], True)} | {number(tasks["pitch"]["coverage"], True)} | {number(tasks["zone"]["coverage"], True)} | {number(tasks["result"]["coverage"], True)} |')
    lines += ['', '## 月別時間漂移', '', '| 月 | 球種 n | 球種 log loss | 球種 ECE | 球種覆蓋 | 分區覆蓋 | 結果覆蓋 |', '|---|---:|---:|---:|---:|---:|---:|']
    for month, models in report['monthly'].items():
        tasks = models['selected_calibrated']
        lines.append(f'| {month} | {tasks["pitch"]["n"]:,} | {number(tasks["pitch"]["log_loss"])} | {number(tasks["pitch"]["ece"])} | {number(tasks["pitch"]["coverage"], True)} | {number(tasks["zone"]["coverage"], True)} | {number(tasks["result"]["coverage"], True)} |')
    lines += ['', '2024 校準 audit 與 2025 測試的差異同時包含球員、月份與資料分布改變，不能歸因於單一原因。每月樣本相關，未以獨立逐球假設宣稱信賴區間。', '',
              '## 校準與限制', '', '| 任務 | 2024 audit log loss | 2025 log loss | 2024 audit 覆蓋 | 2025 覆蓋 |', '|---|---:|---:|---:|---:|']
    for task in TASKS:
        audit, tested = report['frozen_calibration_audit'][task], selected[task]
        lines.append(f'| {task} | {number(audit["log_loss_after"])} | {number(tested["log_loss"])} | {number(audit.get("coverage"), True)} | {number(tested["coverage"], True)} |')
    lines += ['', '名目 90% 集合沒有在測試集調整；若低於 90% 即如實保留。分區集合可能涵蓋多數區域，應同時看集合大小，而非只看覆蓋。', '',
              '推薦只用觀測資料的條件結果與訓練期 ΔRE；人工落點是實際位置，並非瞄準意圖，不能宣稱推薦改善實際失分。', '',
              '模型內 `test_evaluated=false` 是第二週匯出當下的歷史訓練紀錄，保留原位元組以維持 SHA；本第三週報告的 `test_evaluated=true` 表示後續已實施最終評估。', '',
              f'實際評估耗時 {report["duration_seconds"]:.1f} 秒，完整 [最終測試 JSON](final_evaluation.json)、[供產品顯示的摘要](final_evaluation_public.json)。重新執行 `rtk proxy .venv\\Scripts\\python.exe scripts/evaluate_final.py` 只重現同一凍結評估，不重訓。', '',
              '資料：[Rebas Open Data](https://github.com/rebas-tw/rebas.tw-open-data)，[ODC-By 授權](https://github.com/rebas-tw/rebas.tw-open-data/blob/main/LICENSE)。']
    (directory / 'FINAL_RESULTS.md').write_bytes(('\n'.join(lines) + '\n').encode('utf-8'))
    os.environ.setdefault('MPLCONFIGDIR', str(directory.resolve().parents[1] / '.cache/matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    names = ['league_count', 'pitcher_count_shrunk', 'selected_calibrated']
    tasks = ['pitch', 'zone', 'result']
    for i, name in enumerate(names):
        axes[0].bar(np.arange(3) + (i - 1) * .25,
                    [report['all_supported_rows'][name][task]['log_loss'] for task in tasks],
                    width=.25, label=name.replace('_', ' '))
    axes[0].set(xticks=np.arange(3), xticklabels=tasks, ylabel='log loss (nats)', title='Frozen-model 2025 final test')
    axes[0].legend(fontsize=8)
    for task in tasks:
        axes[1].plot(list(report['monthly']), [models['selected_calibrated'][task]['coverage'] for models in report['monthly'].values()],
                     marker='o', label=task)
    axes[1].axhline(.9, color='gray', linestyle='--', label='nominal 90%')
    axes[1].set(ylabel='empirical set coverage', title='2025 monthly coverage with frozen thresholds')
    axes[1].tick_params(axis='x', rotation=35)
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(directory / 'final_test_summary.png', dpi=160)
    plt.close(fig)
