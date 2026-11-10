"""Rebuild week-one processed data, audit, baseline and deployment bundle."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.cache/matplotlib'))
sys.path.insert(0,str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from src.baseline import fit, evaluate
from src.preprocess import flatten, split_games


def write_json(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def main():
    processed, docs, bundle = ROOT/'data/processed', ROOT/'docs/week1', ROOT/'artifacts/baseline'
    for path in [processed,docs,bundle]:
        path.mkdir(parents=True,exist_ok=True)
    print('Flattening original game files ...',flush=True)
    pitches,games,identities,audit = flatten(ROOT/'data/raw')
    games,split_info = split_games(games)
    pitches = pitches.merge(games[['game_id','split']],on='game_id',validate='many_to_one')
    pitches.to_parquet(processed/'pitches.parquet',index=False)
    games.to_parquet(processed/'games.parquet',index=False)
    identities.to_parquet(processed/'identities.parquet',index=False)
    train = pitches.loc[pitches.split == 'train']
    train_ids = identities.loc[identities.date <= train.date.max()]
    data_version = 'rebas-2023-2025-regular-v1'
    model_version = 'week1-frequency-v1'
    print(f'{len(games):,} games; {len(pitches):,} pitches. Fitting train-only baseline ...',flush=True)
    model = fit(train,train_ids,model_version,data_version)
    write_json(bundle/'model.json',model)
    checksum = hashlib.sha256((bundle/'model.json').read_bytes()).hexdigest()
    write_json(bundle/'manifest.json',{'model_version':model_version,'data_version':data_version,
        'data_cutoff':model['data_cutoff'],'sha256':checksum,'file':'model.json','split':split_info})
    print('Evaluating validation set only; leaving 2025 untouched ...',flush=True)
    metrics = evaluate(model,pitches.loc[pitches.split == 'validation'])
    write_json(docs/'baseline_metrics.json',metrics)
    yearly = []
    for year,group in pitches.groupby('year'):
        yearly.append({'year':int(year),'games':int((games.year==year).sum()),'pitches':len(group),
            'coordinate_missing_rate':float((group.coord_x.isna() | group.coord_y.isna()).mean()),
            'zone_unavailable_rate':float(group.zone.isna().mean()),
            'velocity_missing_rate':float(group.velocity.isna().mean()),
            'valid_state_rate':float(group.state_valid.mean()),'resolved_identity_rate':float(group.identity_valid.mean())})
    ambiguous = identities.groupby(['role','name']).id.nunique()
    aliases = identities.groupby(['role','id'])['name'].nunique()
    summary = {'data_version':data_version,'model_version':model_version,'games':len(games),
        'pitches':len(pitches),'date_min':games.date.min(),'date_max':games.date.max(),
        'by_year':yearly,'splits':games.groupby('split').size().astype(int).to_dict(),
        'split_pitch_counts':pitches.groupby('split').size().astype(int).to_dict(),
        'split_policy':split_info,'training_cutoff':model['data_cutoff'],
        'unique_pitchers':int(pitches.pitcher_id.nunique()),'unique_batters':int(pitches.batter_id.nunique()),
        'same_name_multiple_ids':[{'role':i[0],'name':i[1],'id_count':int(n)} for i,n in ambiguous.items() if n>1],
        'same_id_multiple_names':[{'role':i[0],'id':i[1],'name_count':int(n)} for i,n in aliases.items() if n>1],
        'audit':audit,'pitch_types':pitches.pitch_type.fillna('UNKNOWN').value_counts().astype(int).to_dict(),
        'zone_definition':{'x_min':-50,'x_max':50,'y_min':-60,'y_max':60,'view':'pitcher',
                           'outer_rule':'largest abs normalized coordinate; vertical wins diagonal ties',
                           'outlier_limits':[500,600]},
        'known_limitations':[
            'PA count/outs/bases are pre-final-pitch fields, not PA-start state.',
            'Runner entries lack starting/ending base; uncertain intermediate bases are masked.',
            'Incomplete half innings are excluded from run-expectancy targets.',
            'Player identity is resolved from each game/team/role box score; names are never globally merged.',
            'Week-one prediction is pitcher/count baseline; batter and sequence modeling are scheduled for week two.',
        ]}
    write_json(docs/'data_audit.json',summary)
    write_json(docs/'split_manifest.json',{'policy':split_info,'games':games[['game_id','date','split']].to_dict('records')})
    pd.DataFrame(yearly).to_csv(docs/'yearly_quality.csv',index=False,encoding='utf-8-sig')
    train.groupby(['stadium'],dropna=False).agg(pitches=('game_id','size'),coordinate_missing=('coord_x',lambda x: x.isna().mean())).to_csv(docs/'training_stadium_quality.csv',encoding='utf-8-sig')
    # Data quality charts are descriptive; model/augmentation choices use training only.
    fig,axes = plt.subplots(1,2,figsize=(10,3.7))
    years = [str(x['year']) for x in yearly]
    axes[0].bar(years,[x['pitches'] for x in yearly],color='#245b4a')
    axes[0].set(title='Pitch records by year',ylabel='Pitches')
    axes[1].bar(years,[100*x['coordinate_missing_rate'] for x in yearly],color='#c28b39')
    axes[1].set(title='Coordinate missing rate',ylabel='Percent')
    fig.tight_layout(); fig.savefig(docs/'data_overview.png',dpi=160); plt.close(fig)
    location = train.loc[train.zone.notna() & train.pitch_code.isin(['S','B'])]
    fig,ax = plt.subplots(figsize=(5,5))
    for code,color in [('B','#b6b9b1'),('S','#245b4a')]:
        subset=location.loc[location.pitch_code==code].sample(min(4000,int((location.pitch_code==code).sum())),random_state=42)
        ax.scatter(subset.coord_x,subset.coord_y,s=2,alpha=.18,c=color,label=code)
    from matplotlib.patches import Rectangle
    ax.add_patch(Rectangle((-50,-60),100,120,fill=False,color='#b97720',lw=2))
    ax.set(xlim=(-160,160),ylim=(-190,190),xlabel='X (pitcher view)',ylabel='Y',title='Training only: called strike / ball')
    ax.legend();fig.tight_layout();fig.savefig(docs/'training_coordinate_noise.png',dpi=160);plt.close(fig)
    report = [
        '# 第一週資料與基準成果', '',
        '來源：[主辦方官網](https://blog.rebas.tw/articles/4136) → [Rebas Open Data](https://github.com/rebas-tw/rebas.tw-open-data)。',
        '', f'共 {len(games):,} 場例行賽、{len(pitches):,} 筆投球事件；日期 {games.date.min()} 至 {games.date.max()}。',
        '只讀取單場 JSON；ZIP 內合併檔不重複計算。未納入季後挑戰賽、台灣大賽或 2026 年資料。','',
        '## 年度資料品質','', '| 年度 | 場數 | 投球數 | 座標缺值 | 球速缺值 | 可用情境 |','|---|---:|---:|---:|---:|---:|']
    for x in yearly:
        report.append(f'| {x["year"]} | {x["games"]} | {x["pitches"]:,} | {x["coordinate_missing_rate"]:.2%} | {x["velocity_missing_rate"]:.2%} | {x["valid_state_rate"]:.2%} |')
    report += ['', '![年度資料品質](data_overview.png)','', '## 時間切分','',
        f'- 訓練：2023 年及 {split_info["validation_start"]} 以前的 2024 年完整比賽。',
        f'- 驗證：{split_info["validation_start"]} 至 {split_info["calibration_start"]} 以前。',
        f'- 校準：{split_info["calibration_start"]} 起的 2024 年比賽，保留供第二週使用。',
        '- 測試：2025 年完整保留，本週未計算模型測試成績。',
        '- 以 2024 年比賽日期的 70%／85% 分位分界；同日比賽不跨集合，分界不依標籤調整。',
        '', '## 驗證集球種預測','', '| 基準 | 筆數 | Log loss | Top-1 | Top-2 |','|---|---:|---:|---:|---:|']
    for name in ['league_count','pitcher_count_shrunk']:
        x=metrics[name];report.append(f'| {name} | {x["n"]:,} | {x["log_loss"]:.4f} | {x["top1_accuracy"]:.2%} | {x["top2_accuracy"]:.2%} |')
    report += ['', '## 查核結果與限制','',
        f'- 末球前球數重建不符的打席：{audit["counters"].get("pa_count_mismatch",0):,}；受影響資料不進入情境基準。',
        f'- 無法由當場成績表唯一對應 ID 的投手事件：{audit["counters"].get("pitcher_unresolved",0):,}；打者事件：{audit["counters"].get("batter_unresolved",0):,}。',
        '- 同名不同 ID 與同 ID 多名稱均保留獨立查核清單，不按姓名全域合併。',
        '- 前段球數由事件重建，最後一球的出局／壘包與分數以 PA 的末球前欄位核對。',
        '- 跑者紀錄未提供起終點壘位；中途有移動時，無法可靠推算的壘包標未知，不硬補。',
        '- 延長局起始壘包未假定為空壘；不完整半局不作完整半局期望得分標籤。',
        '- 分區採寬 100、高 120 的座標定義；帶外以正規化偏離較大的軸分區，角落不重疊。',
        '- 座標缺值與離群值不當作零；球速僅保留 40–180 的可解析值並記錄剔除。',
        '- 雜訊圖只使用訓練資料，呈現人工落點與裁判判定的綜合差異，尚未估計可分離的儀器誤差。',
        '- 目前為投手／球數頻率基準，打者只用於樣本查核；未聲稱完成打者特徵、序列模型或 conformal。',
        '- 推薦以訓練期狀態價值與歷史候選失分變化平滑排序；稀疏情境主要依賴較大群體，並非因果策略效果。',
        '', '![訓練資料落點診斷](training_coordinate_noise.png)','',
        '詳細機讀結果：`data_audit.json`、`split_manifest.json`、`baseline_metrics.json`。',
        '重跑：在專案根目錄執行 `.venv\\Scripts\\python.exe scripts/build_week1.py`。','']
    (docs/'RESULTS.md').write_text('\n'.join(report),encoding='utf-8')
    print(json.dumps({'games':len(games),'pitches':len(pitches),'training':model['training_pitches'],
                      'cutoff':model['data_cutoff'],'bundle_bytes':(bundle/'model.json').stat().st_size,
                      'validation':metrics},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
