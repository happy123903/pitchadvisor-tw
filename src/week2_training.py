"""Fixed-budget, train/validation/calibration-only week-two experiments.

PyTorch is a training dependency only. The deployed artifact contains native
LightGBM text or NumPy GRU parameters, with independent temperature/conformal
partitions. Candidate selection never uses calibration outcomes or the 2025 set.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from src.baseline import Baseline, distribution, key
from src.week2_features import HISTORY_RESULTS, FeatureBatch, build_batch, fit_encoder
from src.week2_model import conditional_distributions, raw_distributions, temperature_scale

TASKS = ('pitch', 'zone', 'result')
SEED = 20261110


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Bytes, not Windows text newline conversion: this is the checksum contract.
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))


def classification_metrics(probabilities, target):
    mask = target >= 0
    p, y = np.asarray(probabilities)[mask], target[mask]
    if not len(y):
        return {'n': 0, 'log_loss': None, 'top1_accuracy': None, 'top2_accuracy': None, 'ece': None}
    ranks = np.argsort(p, axis=1)[:, ::-1]
    confidence, correct = p.max(axis=1), ranks[:, 0] == y
    ece = 0.0
    for lo, hi in zip(np.linspace(0, 1, 16)[:-1], np.linspace(0, 1, 16)[1:]):
        group = (confidence >= lo) & (confidence < hi if hi < 1 else confidence <= hi)
        if group.any():
            ece += group.mean() * abs(confidence[group].mean() - correct[group].mean())
    return {'n': len(y), 'log_loss': float(-np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1)).mean()),
            'top1_accuracy': float(correct.mean()), 'top2_accuracy': float((ranks[:, :2] == y[:, None]).any(axis=1).mean()),
            'ece': float(ece)}


def evaluate_payload(payload, batch):
    probabilities = raw_distributions(payload, batch)
    return {task: classification_metrics(probabilities[task], getattr(batch, task)) for task in TASKS}


def baseline_probabilities(baseline, batch, individual):
    pitch, zones, results = [], [], []
    model = baseline.model
    labels = model['labels']
    result_prior = distribution(model['result_global'], HISTORY_RESULTS)
    for row in batch.frame.itertuples(index=False):
        pp = baseline.pitch_distribution(row.pitcher_id, row.balls, row.strikes, individual=individual)
        pitch.append(pp)
        # Both legacy baselines use the same train-only pitcher/zone estimates.
        zones.append(sum(p * baseline.zone_distribution(row.pitcher_id, label) for p, label in zip(pp, labels)))
        results.append(distribution(model['result_count'].get(key(row.balls, row.strikes), {}), HISTORY_RESULTS, result_prior))
    return {'pitch': np.asarray(pitch), 'zone': np.asarray(zones), 'result': np.asarray(results)}


def train_lightgbm(train, validation, *, sequence, rounds, threads, seed=SEED):
    import lightgbm as lgb
    x, vx = train.lgb_features(sequence), validation.lgb_features(sequence)
    class_counts = {'pitch': train.tokens.shape[-1] - 20, 'zone': 13, 'result': len(HISTORY_RESULTS)}
    models, iterations = {}, {}
    for task in (*TASKS, 'conditional_result'):
        target_task = 'result' if task == 'conditional_result' else task
        y, vy = getattr(train, target_task), getattr(validation, target_task)
        tx, tvx = x, vx
        mask, vmask = y >= 0, vy >= 0
        if task == 'conditional_result':
            mask &= train.zone >= 0
            vmask &= validation.zone >= 0
            action = np.column_stack([np.eye(class_counts['pitch'])[train.pitch], np.eye(13)[np.maximum(train.zone, 0)]])
            va = np.column_stack([np.eye(class_counts['pitch'])[validation.pitch], np.eye(13)[np.maximum(validation.zone, 0)]])
            tx, tvx = np.column_stack([x, action]), np.column_stack([vx, va])
        params = {'objective': 'multiclass', 'num_class': class_counts[target_task], 'metric': 'multi_logloss',
                  'learning_rate': .055, 'num_leaves': 23, 'min_data_in_leaf': 80, 'lambda_l2': 4.,
                  'feature_fraction': .9, 'verbosity': -1, 'deterministic': True, 'force_col_wise': True,
                  'num_threads': threads, 'seed': seed}
        train_set = lgb.Dataset(tx[mask], label=y[mask], categorical_feature=[0, 1])
        val_set = lgb.Dataset(tvx[vmask], label=vy[vmask], reference=train_set)
        booster = lgb.train(params, train_set, num_boost_round=rounds, valid_sets=[val_set],
                            callbacks=[lgb.early_stopping(18, verbose=False)])
        models[task] = booster.model_to_string(num_iteration=booster.best_iteration)
        iterations[task] = booster.best_iteration
        print(f'  LGB sequence={sequence} {task}: {booster.best_iteration} iterations', flush=True)
    return {'family': 'lightgbm', 'config': {'sequence': sequence, 'pitch_classes': class_counts['pitch'],
            'threads': 1, 'best_iterations': iterations}, 'models': models}


def make_torch_model(encoder, *, sequence=True, shrinkage=True, hidden_size=32, embedding_size=8):
    import torch
    from torch import nn

    class MultiTaskGRU(nn.Module):
        def __init__(self):
            super().__init__()
            self.pitcher_embedding = nn.Embedding(len(encoder['pitcher_ids']) + 1, embedding_size, padding_idx=0)
            self.batter_embedding = nn.Embedding(len(encoder['batter_ids']) + 1, embedding_size, padding_idx=0)
            self.gru = nn.GRU(len(encoder['pitch_labels']) + 13 + len(HISTORY_RESULTS) + 2, hidden_size, batch_first=True)
            self.trunk = nn.Linear(10 + 2 * embedding_size + hidden_size, 64)
            self.pitch_head = nn.Linear(64, len(encoder['pitch_labels']))
            self.zone_head = nn.Linear(64, 13)
            self.result_head = nn.Linear(64, len(HISTORY_RESULTS))
            self.conditional_head = nn.Linear(64 + len(encoder['pitch_labels']) + 13, len(HISTORY_RESULTS))

        def features(self, ids, context, tokens, lengths):
            gates = context[:, -2:] if shrinkage else (ids > 0).float()
            ep = self.pitcher_embedding(ids[:, 0]) * gates[:, :1]
            eb = self.batter_embedding(ids[:, 1]) * gates[:, 1:]
            output, _ = self.gru(tokens)
            lengths = lengths if sequence else torch.zeros_like(lengths)
            hidden = output[torch.arange(len(ids)), (lengths - 1).clamp(min=0)] * (lengths > 0)[:, None]
            return torch.relu(self.trunk(torch.cat([context, ep, eb, hidden], dim=1)))

        def forward(self, ids, context, tokens, lengths, pitch=None, zone=None):
            features = self.features(ids, context, tokens, lengths)
            outputs = {task: getattr(self, task + '_head')(features) for task in TASKS}
            if pitch is not None:
                actions = torch.cat([nn.functional.one_hot(pitch, len(encoder['pitch_labels'])),
                                     nn.functional.one_hot(zone.clamp(min=0), 13)], dim=1).float()
                outputs['conditional_result'] = self.conditional_head(torch.cat([features, actions], dim=1))
            return outputs

    return MultiTaskGRU()


def torch_tensors(batch):
    import torch
    return [torch.from_numpy(getattr(batch, name)) for name in ['ids', 'context', 'tokens', 'lengths', 'pitch', 'zone', 'result']]


def torch_probabilities(network, batch, chunk_size=2048):
    import torch
    output = {task: [] for task in (*TASKS, 'conditional_result')}
    tensors = torch_tensors(batch)
    network.eval()
    with torch.no_grad():
        for start in range(0, len(batch.ids), chunk_size):
            ids, context, tokens, lengths, pitch, zone, _ = [x[start:start + chunk_size] for x in tensors]
            for task, logits in network(ids, context, tokens, lengths, pitch, zone).items():
                output[task].append(torch.softmax(logits, dim=1).numpy())
    return {task: np.concatenate(values) for task, values in output.items()}


def train_gru(train, validation, encoder, *, epochs, threads, sequence=True, shrinkage=True, multitask=True):
    import torch
    from torch import nn
    torch.set_num_threads(threads)
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    network = make_torch_model(encoder, sequence=sequence, shrinkage=shrinkage)
    optimizer = torch.optim.AdamW(network.parameters(), lr=.002, weight_decay=.0001)
    criterion = nn.CrossEntropyLoss()
    tensors = torch_tensors(train)
    generator = torch.Generator().manual_seed(SEED)
    best_loss, best_state, best_epoch, history = float('inf'), None, 0, []
    for epoch in range(epochs):
        network.train()
        running, total = 0., 0
        for indices in torch.randperm(len(train.ids), generator=generator).split(1024):
            ids, context, tokens, lengths, pitch, zone, result = [x[indices] for x in tensors]
            optimizer.zero_grad(set_to_none=True)
            outputs = network(ids, context, tokens, lengths, pitch, zone)
            loss = criterion(outputs['pitch'], pitch)
            if multitask:
                mask = zone >= 0
                loss = loss + .35 * criterion(outputs['result'], result)
                if mask.any():
                    loss = loss + .35 * criterion(outputs['zone'][mask], zone[mask])
                    loss = loss + .35 * criterion(outputs['conditional_result'][mask], result[mask])
            loss.backward()
            nn.utils.clip_grad_norm_(network.parameters(), 2.)
            optimizer.step()
            running += float(loss.detach()) * len(indices)
            total += len(indices)
        probabilities = torch_probabilities(network, validation)
        loss = classification_metrics(probabilities['pitch'], validation.pitch)['log_loss']
        history.append({'epoch': epoch + 1, 'training_joint_loss': running / total, 'validation_pitch_log_loss': loss})
        print(f'  GRU seq={sequence} shrink={shrinkage} multi={multitask} epoch={epoch + 1} validation={loss:.6f}', flush=True)
        if loss < best_loss:
            best_loss, best_epoch = loss, epoch + 1
            best_state = {name: value.detach().clone() for name, value in network.state_dict().items()}
        if epoch + 1 - best_epoch >= 3:
            break
    network.load_state_dict(best_state)
    payload = {'family': 'gru', 'config': {'sequence': sequence, 'shrinkage': shrinkage,
                'multitask': multitask, 'hidden_size': 32, 'embedding_size': 8, 'pitch_classes': len(encoder['pitch_labels']),
                'best_epoch': best_epoch},
               'weights': {name: value.detach().numpy().tolist() for name, value in network.state_dict().items()}}
    check = validation.subset(np.arange(min(128, len(validation.ids))))
    reference = torch_probabilities(network, check)
    predicted = raw_distributions(payload, check)
    predicted['conditional_result'] = conditional_distributions(payload, check, check.pitch, np.maximum(check.zone, 0))
    parity = {task: float(np.abs(reference[task] - predicted[task]).max()) for task in reference}
    if max(parity.values()) > 2e-5:
        raise AssertionError(f'NumPy/PyTorch export mismatch: {parity}')
    return payload, {'epochs': history, 'numpy_export_max_abs_error': parity}


def fit_result_values(train, baseline):
    """Expected ΔRE by *observed* result, pooled by current state, train only."""
    m = baseline
    def value(b, s, o, bases):
        return 0. if o >= 3 else m['re_table'].get(key(b, s, o, bases), m['re_parent'].get(key(o, bases), m['global_re']))
    valid = train.state_valid & train.identity_valid & train.transition_known & train.next_bases.notna() & train.next_outs.between(0, 3) & train.runs.ge(0) & train.result.isin(HISTORY_RESULTS)
    work = train.loc[valid].copy()
    work['delta_re'] = [float(r.runs + value(r.next_balls, r.next_strikes, r.next_outs, r.next_bases)
                             - value(r.balls, r.strikes, r.outs, r.bases)) for r in work.itertuples()]
    global_values = [float(work.loc[work.result.eq(label), 'delta_re'].mean()) for label in HISTORY_RESULTS]
    by_state = {}
    for state, group in work.groupby(['balls', 'strikes', 'outs', 'bases']):
        by_state[key(*state)] = [float((group.loc[group.result.eq(label), 'delta_re'].sum() + 30 * parent)
                                      / (group.result.eq(label).sum() + 30)) for label, parent in zip(HISTORY_RESULTS, global_values)]
    return {'global': global_values, 'by_state': by_state, 'training_transitions': len(work), 'smoothing_strength': 30,
            'interpretation': 'observational result-conditional mean delta RE, not intervention value'}


def calibrate(payload, calibration):
    dates = sorted(calibration.frame.date.unique())
    cut1, cut2 = max(1, int(len(dates) * .4)), max(2, int(len(dates) * .7))
    parts = {}
    for name, selected in [('temperature', dates[:cut1]), ('conformal', dates[cut1:cut2]), ('audit', dates[cut2:])]:
        idx = np.flatnonzero(calibration.frame.date.isin(selected).to_numpy())
        if not len(idx):
            raise ValueError('Calibration requires at least three distinct complete dates')
        parts[name] = calibration.subset(idx)
    probabilities = {name: raw_distributions(payload, batch) for name, batch in parts.items()}
    temperatures, thresholds, audit = {}, {}, {}
    candidates = np.unique(np.r_[1., np.exp(np.linspace(np.log(.5), np.log(3.), 81))])
    for task in (*TASKS, 'conditional_result'):
        target_task = 'result' if task == 'conditional_result' else task
        if task == 'conditional_result':
            for name, batch in parts.items():
                probabilities[name][task] = conditional_distributions(payload, batch, batch.pitch, np.maximum(batch.zone, 0))
        def mask(batch):
            good = getattr(batch, target_task) >= 0
            return good & (batch.zone >= 0) if task == 'conditional_result' else good
        fitted = parts['temperature']
        good = mask(fitted)
        y = getattr(fitted, target_task)[good]
        raw = probabilities['temperature'][task][good]
        losses = [classification_metrics(temperature_scale(raw, t), y)['log_loss'] for t in candidates]
        temperature = float(candidates[np.argmin(losses)])
        temperatures[task] = temperature
        held = parts['audit']
        held_good = mask(held)
        hy = getattr(held, target_task)[held_good]
        before_p = probabilities['audit'][task][held_good]
        after_p = temperature_scale(before_p, temperature)
        before, after = classification_metrics(before_p, hy), classification_metrics(after_p, hy)
        report = {'n': len(hy), 'ece_before': before['ece'], 'ece_after': after['ece'],
                  'log_loss_before': before['log_loss'], 'log_loss_after': after['log_loss']}
        if task in TASKS:
            quantile = parts['conformal']
            qgood = mask(quantile)
            qy = getattr(quantile, task)[qgood]
            qp = temperature_scale(probabilities['conformal'][task][qgood], temperature)
            scores = 1 - qp[np.arange(len(qy)), qy]
            rank = math.ceil((len(scores) + 1) * .9)
            threshold = 1. if rank > len(scores) else float(np.partition(scores, rank - 1)[rank - 1])
            thresholds[task] = threshold
            included = 1 - after_p <= threshold
            report.update({'coverage': float(included[np.arange(len(hy)), hy].mean()),
                           'mean_set_size': float(included.sum(axis=1).mean()), 'conformal_n': len(qy),
                           'finite_sample_rank': rank})
        audit[task] = report
    split = {name: {'date_min': batch.frame.date.min(), 'date_max': batch.frame.date.max(),
                    'dates': sorted(batch.frame.date.unique()), 'rows': len(batch.ids),
                    'games': int(batch.frame.game_id.nunique())} for name, batch in parts.items()}
    return {'method': 'temperature+split-conformal', 'temperature': temperatures, 'thresholds': thresholds,
            'target_coverage': .9, 'audit': audit, 'split': split,
            'limitations': 'Chronological observational samples may shift; empirical coverage is not an exchangeability guarantee.'}


def sample_groups(payload, validation, encoder, matchup_counts):
    predictions = raw_distributions(payload, validation)
    counts = validation.frame.batter_id.map(encoder['batter_counts']).fillna(0).to_numpy()
    masks = {'batter_unseen': counts == 0, 'batter_1_99': (counts > 0) & (counts < 100),
             'batter_100_499': (counts >= 100) & (counts < 500), 'batter_500_plus': counts >= 500,
             'history_empty': validation.lengths == 0, 'history_available': validation.lengths > 0}
    pc = validation.frame.pitcher_id.map(encoder['pitcher_counts']).fillna(0).to_numpy()
    masks.update({'pitcher_under_100': pc < 100, 'pitcher_100_plus': pc >= 100})
    matchup = np.asarray([matchup_counts.get(key(pid, bid), 0)
                          for pid, bid in zip(validation.frame.pitcher_id, validation.frame.batter_id)])
    masks.update({'matchup_unseen': matchup == 0, 'matchup_1_29': (matchup > 0) & (matchup < 30),
                  'matchup_30_99': (matchup >= 30) & (matchup < 100), 'matchup_100_plus': matchup >= 100})
    return {name: {task: classification_metrics(p[m], getattr(validation, task)[m]) for task, p in predictions.items()}
            for name, m in masks.items()}


def write_results(report, report_dir):
    """Human-readable report derived only from saved measured experiment outputs."""
    import os
    os.environ.setdefault('MPLCONFIGDIR', str(Path(report_dir).resolve().parents[1] / '.cache/matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    report_dir = Path(report_dir)
    def number(value, percent=False):
        return '—' if value is None else (f'{value:.2%}' if percent else f'{value:.6f}')
    lines = ['# 第二週模型比較與校準成果', '',
             '本文件由實際訓練輸出的 `metrics.json` 自動產生。2025 最終測試集未載入、未打分、未選模或校準。', '',
             'Smoke：' + str(report['smoke']) + '；實驗 seed：' + str(report['seed']) + '。', '',
             '## 相同驗證樣本的三任務比較', '',
             '下表為未校準驗證結果；log loss 與 ECE 越低越好。各任務的缺標籤遮罩在所有模型間相同。', '',
             '| 模型 | 任務 | n | log loss | top-1 | top-2 | ECE |',
             '|---|---|---:|---:|---:|---:|---:|']
    for name, tasks in report['validation'].items():
        for task, values in tasks.items():
            lines.append(f'| {name} | {task} | {values["n"]:,} | {number(values["log_loss"])} | {number(values["top1_accuracy"], True)} | {number(values["top2_accuracy"], True)} | {number(values["ece"])} |')
    selection = report['selection']
    lines += ['', '![驗證任務比較](validation_comparison.png)', '',
              '## 事前規則下的選模', '', f'選定：`{selection["candidate"]}`。', '', selection['reason'], '',
              '規則：' + selection['rule'] + '。', '',
              '模型資源仍需獨立 API 服務驗收；本訓練程序不代表 Render 記憶體或線上延遲。', '',
              '## 排除與有效歷程', '', '| 分割 | 原始球數 | 可用球數 | 排除 | 特殊結果 | 缺分區 | 有效非空歷程 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for name, item in report['exclusions'].items():
        lines.append('| ' + name + ' | ' + ' | '.join(f'{item[k]:,}' for k in ['raw_rows', 'usable_rows', 'excluded_rows', 'special_result_rows', 'missing_zone_targets', 'nonempty_valid_histories']) + ' |')
    lines += ['', '## 消融', '', '所有消融沿用同一驗證集與固定訓練預算，單任務模型僅報訓練過的球種 head。', '',
              '| 配置 | 任務 | n | log loss | top-1 | ECE |', '|---|---|---:|---:|---:|---:|']
    for name, tasks in report['ablation'].items():
        for task, item in tasks.items():
            if isinstance(item, dict) and 'n' in item:
                lines.append(f'| {name} | {task} | {item["n"]:,} | {number(item["log_loss"])} | {number(item["top1_accuracy"], True)} | {number(item["ece"])} |')
    jitter = report['ablation']['coordinate_jitter']
    lines += ['', f'座標抖動訓練尺度：X σ={jitter["sigma_x"]:.4f}、Y σ={jitter["sigma_y"]:.4f}，由訓練 X IQR 固定推得；未改動驗證／校準。', '',
              '## 獨立校準與 conformal audit', '', '| 階段 | 起始日期 | 結束日期 | 完整日期數 | 場數 | 可用球數 |',
              '|---|---|---|---:|---:|---:|']
    calibration = report['calibration']
    for name, part in calibration['split'].items():
        lines.append(f'| {name} | {part["date_min"]} | {part["date_max"]} | {len(part["dates"])} | {part["games"]} | {part["rows"]:,} |')
    lines += ['', '| 任務 | T | audit n | log loss 前 | log loss 後 | ECE 前 | ECE 後 | 實測覆蓋率 | 平均集合大小 |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for task, item in calibration['audit'].items():
        lines.append(f'| {task} | {calibration["temperature"][task]:.4f} | {item["n"]:,} | {number(item["log_loss_before"])} | {number(item["log_loss_after"])} | {number(item["ece_before"])} | {number(item["ece_after"])} | {number(item.get("coverage"), True)} | {number(item.get("mean_set_size"))} |')
    lines += ['', '名目覆蓋率為 90%；audit 未參與溫度或分位數擬合。時間漂移與觀測選擇偏差仍可能存在，實測覆蓋率不等於未來實戰保證。條件結果 head 另作溫度校準，不套用主結果 head 的集合覆蓋率。', '',
              '## 訓練樣本數分組的驗證結果', '',
              '分組只依訓練期樣本數定義。直接投打對戰從未出現、1–29、30–99、100 以上分開報告；空組保留 n=0。', '',
              '| 分組 | 球種 n | 球種 log loss | 球種 top-1 | 分區 log loss | 結果 log loss |',
              '|---|---:|---:|---:|---:|---:|']
    for name, tasks in report['sample_groups'].items():
        p = tasks['pitch']
        lines.append(f'| {name} | {p["n"]:,} | {number(p["log_loss"])} | {number(p["top1_accuracy"], True)} | {number(tasks["zone"]["log_loss"])} | {number(tasks["result"]["log_loss"])} |')
    lines += ['', '## 匯出一致性與運算條件', '',
              '預算：`' + json.dumps(report['fixed_budget'], ensure_ascii=False) + '`。', '',
              '| GRU 配置 | 實際 epochs | 最大 NumPy／PyTorch 機率誤差 |', '|---|---:|---:|']
    for name, detail in report['training'].items():
        lines.append(f'| {name} | {len(detail["epochs"])} | {max(detail["numpy_export_max_abs_error"].values()):.3g} |')
    lines += ['', f'訓練、比較與校準共 {report["duration_seconds"]:.1f} 秒。', '',
              '完整方法、速度與歷程遮罩、推薦因果限制，參閱 [MODELING_METHOD.md](MODELING_METHOD.md)。', '']
    (report_dir / 'RESULTS.md').write_bytes('\n'.join(lines).encode('utf-8'))
    names = list(report['validation'])
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    for axis, task in zip(axes, TASKS):
        heights = [report['validation'][name][task]['log_loss'] for name in names]
        colors = ['#245b4a' if name == selection['candidate'] else '#a8b8ae' for name in names]
        axis.bar(np.arange(len(names)), heights, color=colors)
        axis.set_xticks(np.arange(len(names)), names, rotation=42, ha='right', fontsize=8)
        axis.set(title=task + ' validation log loss', ylabel='nats')
    fig.tight_layout()
    fig.savefig(report_dir / 'validation_comparison.png', dpi=150)
    plt.close(fig)


def run(root, output, report_dir, *, smoke=False, threads=4, epochs=10, rounds=140):
    started = time.perf_counter()
    output, report_dir = Path(output), Path(report_dir)
    # The parquet reader itself never materializes the 2025 test partition.
    frame = pd.read_parquet(root / 'data/processed/pitches.parquet', filters=[('year', '<=', 2024)])
    if frame.year.gt(2024).any() or frame.split.eq('test').any():
        raise AssertionError('2025 holdout entered week-two pipeline')
    baseline = json.loads((root / 'artifacts/baseline/model.json').read_text(encoding='utf-8'))
    train_frame = frame.loc[frame.split.eq('train')]
    validation_frame = frame.loc[frame.split.eq('validation')]
    calibration_frame = frame.loc[frame.split.eq('calibration')]
    if smoke:
        # Keep complete games/PA, not random individual pitches that sever histories.
        train_frame = train_frame.loc[train_frame.game_id.isin(train_frame.game_id.unique()[-18:])]
        validation_frame = validation_frame.loc[validation_frame.game_id.isin(validation_frame.game_id.unique()[:5])]
        epochs, rounds = min(epochs, 2), min(rounds, 12)
    encoder = fit_encoder(train_frame.loc[train_frame.state_valid & train_frame.identity_valid], baseline['labels'])
    print('Building strict previous-pitch histories (2025 excluded) ...', flush=True)
    train, validation = build_batch(train_frame, encoder), build_batch(validation_frame, encoder)
    calibration_batch = build_batch(calibration_frame, encoder)
    exclusions = {name: {'raw_rows': len(raw), 'usable_rows': len(batch.ids),
                         'excluded_rows': len(raw) - len(batch.ids),
                         'special_result_rows': int((~raw.result.isin(HISTORY_RESULTS)).sum()),
                         'missing_zone_targets': int((batch.zone < 0).sum()),
                         'nonempty_valid_histories': int((batch.lengths > 0).sum())}
                  for name, raw, batch in [('train', train_frame, train), ('validation', validation_frame, validation),
                                           ('calibration', calibration_frame, calibration_batch)]}
    report = {'seed': SEED, 'smoke': smoke, 'test_evaluated': False, 'test_loaded': False,
              'fixed_budget': {'epochs': epochs, 'lgb_rounds': rounds, 'threads': threads, 'gru_batch_size': 1024},
              'exclusions': exclusions, 'validation': {}, 'training': {}, 'ablation': {}}
    legacy = Baseline(baseline)
    for name, individual in [('league_count', False), ('pitcher_count_shrunk', True)]:
        pp = baseline_probabilities(legacy, validation, individual)
        report['validation'][name] = {task: classification_metrics(pp[task], getattr(validation, task)) for task in TASKS}
    payloads = {}
    for name, sequence in [('lightgbm_context', False), ('lightgbm_history', True)]:
        print(f'Training {name} ...', flush=True)
        payloads[name] = train_lightgbm(train, validation, sequence=sequence, rounds=rounds, threads=threads)
        report['validation'][name] = evaluate_payload(payloads[name], validation)
        write_json(report_dir / 'metrics_in_progress.json', report)
    for name, sequence, shrinkage, multitask in [('gru', True, True, True), ('gru_no_sequence', False, True, True),
                                                ('gru_no_shrinkage', True, False, True), ('gru_single_task', True, True, False)]:
        print(f'Training {name} ...', flush=True)
        payload, detail = train_gru(train, validation, encoder, epochs=epochs, threads=threads,
                                    sequence=sequence, shrinkage=shrinkage, multitask=multitask)
        if name == 'gru':
            payloads[name] = payload
        report['training'][name] = detail
        metrics = evaluate_payload(payload, validation)
        if not multitask:
            metrics = {'pitch': metrics['pitch'], 'untrained_heads_not_evaluated': True}
        if name == 'gru':
            report['validation'][name] = metrics
        else:
            report['ablation'][name] = metrics
        write_json(report_dir / 'metrics_in_progress.json', report)
    # One prespecified noise experiment: 2% of training X IQR, aspect ratio 1.2.
    jitter_scale = float((train_frame.coord_x.quantile(.75) - train_frame.coord_x.quantile(.25)) * .02)
    print(f'Training coordinate-jitter ablation (sigma_x={jitter_scale:.3f}) ...', flush=True)
    jitter_train = build_batch(train_frame, encoder, jitter=jitter_scale, seed=SEED)
    jitter = train_lightgbm(jitter_train, validation, sequence=True, rounds=rounds, threads=threads)
    report['ablation']['lightgbm_history_jitter'] = evaluate_payload(jitter, validation)
    report['ablation']['coordinate_jitter'] = {'sigma_x': jitter_scale, 'sigma_y': jitter_scale * 1.2,
        'rule': '2% of training coordinate X IQR; train-only locations/zone labels; same untouched validation'}
    del jitter_train, jitter
    # Selection is fully validation-based. Simplicity priority is fixed before scores.
    eligible = ['lightgbm_context', 'lightgbm_history']
    gm, lm = report['validation']['gru'], report['validation']['lightgbm_history']
    gru_secondary_ok = all(gm[task]['log_loss'] <= lm[task]['log_loss'] + .03 for task in ['zone', 'result'])
    if gru_secondary_ok:
        eligible.append('gru')
    best = min(report['validation'][name]['pitch']['log_loss'] for name in eligible)
    selected = next(name for name in eligible if report['validation'][name]['pitch']['log_loss'] <= best + .005)
    selection = {'candidate': selected, 'rule': 'validation pitch log loss; within 0.005 nats prefer context LGB then history LGB then GRU; GRU zone/result may degrade at most 0.03 nats vs history LGB',
                 'gru_secondary_eligible': gru_secondary_ok,
                 'reason': f'{selected} is the simplest eligible model within 0.005 nats of best validation pitch log loss ({best:.6f}).',
                 'resource_gate': 'Requires independent deployed p95<500ms and RSS<400MiB before promotion.'}
    report['selection'] = selection
    estimator = payloads[selected]
    print(f'Selected {selected}; fitting independent chronological calibration ...', flush=True)
    calibration = calibrate(estimator, calibration_batch)
    report['calibration'] = calibration
    matchup_counts = {key(pid, bid): int(n) for (pid, bid), n in
                      train_frame.loc[train_frame.state_valid & train_frame.identity_valid].groupby(['pitcher_id', 'batter_id']).size().items()}
    report['sample_groups'] = sample_groups(estimator, validation, encoder, matchup_counts)
    report['duration_seconds'] = time.perf_counter() - started
    version = 'week2-sequence-v1-smoke' if smoke else 'week2-sequence-v1'
    model = {'model_format': 'week2-v1', 'model_version': version, 'data_version': baseline['data_version'], 'data_cutoff': baseline['data_cutoff'],
             'model_name': selected, 'labels': encoder['pitch_labels'], 'result_labels': HISTORY_RESULTS,
             'players': baseline['players'], 'training_pitches': len(train.ids),
             'baseline': baseline, 'encoder': encoder, 'estimator': {name: value for name, value in estimator.items() if not name.startswith('_')},
             'result_values': fit_result_values(train_frame, baseline), 'calibration': calibration,
             'capabilities': {'sequence': bool(estimator['config']['sequence']), 'batter_conditioned_model': True,
                              'conformal': True, 'conditional_result': True},
             'model_info': {'selected_candidate': selected, 'selection_rule': selection['rule'],
                            'selection_reason': selection['reason'], 'training_rows': len(train.ids),
                            'test_evaluated': False, 'validation': report['validation'], 'calibration_audit': calibration['audit']}}
    model_bytes = (json.dumps(model, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    if len(model_bytes) > 20 * 1024 * 1024:
        write_json(report_dir / 'metrics.json', report)
        raise ValueError(f'Model artifact exceeds private Storage 20 MiB limit: {len(model_bytes)} bytes')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'model.json').write_bytes(model_bytes)
    checksum = hashlib.sha256((output / 'model.json').read_bytes()).hexdigest()
    write_json(output / 'manifest.json', {'model_version': version, 'data_version': model['data_version'],
                'data_cutoff': model['data_cutoff'], 'file': 'model.json', 'sha256': checksum,
                'smoke': smoke, 'test_evaluated': False, 'selection': selection})
    write_json(report_dir / 'metrics.json', report)
    write_json(report_dir / 'calibration_audit.json', calibration)
    write_results(report, report_dir)
    print(json.dumps({'selected': selected, 'sha256': checksum, 'output': str(output), 'report': str(report_dir),
                      'duration_seconds': report['duration_seconds'], 'test_evaluated': False}), flush=True)
    return report
