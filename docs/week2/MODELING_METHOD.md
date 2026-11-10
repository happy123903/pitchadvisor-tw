# 第二週建模方法與重現

本文件描述實際程式。選模與驗收門檻以事前固定的 [EXECUTION_PLAN.md](EXECUTION_PLAN.md) 為準；真正分數由 `build_week2.py` 產生的 `metrics.json` 提供。

## 資料邊界

Parquet 讀取時即以 `year <= 2024` 過濾，特徵建立也拒絕 2025 或 `split=test`。沿用第一週逐場 train／validation／calibration，不移動日期。球員 ID、樣本數、左右投打與速度尺度只來自訓練期。第一週模型內的球員目錄與 ΔRE 統計亦是訓練期產物。

單一打席的鍵為 `(game_id, side, pa_index)`；主客隊各有自己的 PA 索引，不能省略 side。每個訓練目標僅看之前的投球，不看當球球種、當球分區或當球結果。歷程必須能從 0–0 重播到目前球數；特殊事件、未知結果或矛盾球數會遮罩歷程。打席內換投的資料也遮罩歷程，因為公開請求的歷程 schema 沒有過去投手 ID；線上使用者需於換投時清空歷程。

第二週結果目標為壞球、好球不揮、揮空、界外、擊入場內五類。HBP 與 other 不合併到其中一類；實際排除數、缺分區與空歷程數記在報告。缺分區僅遮罩分區／條件結果任務，不直接刪除其他可用目標。

速度標準化依訓練期「投手×球種」均值與標準差；至少 20 球才使用，否則退回球種整體，再退回聯盟整體，標準差下限為 3 km/h。缺值使用零標準化值及獨立缺值指示。API 和訓練共用同一個 token encoder。

## 固定規模的比較

比較聯盟球數頻率、投手頻率、情境 LightGBM、情境加歷程摘要 LightGBM 與 GRU。每個模型在完全相同的驗證樣本與任務遮罩評估。GRU 採 32 維單層 hidden state、投打各 8 維 embedding、64 維共用 trunk；三個主 head 預測球種／13 區／五種結果。第四 head 預測給定「候選球種＋候選區域」的結果分布；當球真值僅能進入這個條件結果 head，不能進入主 head。

Embedding 乘上 `n/(n+100)` 收縮係數；未知 ID 的 embedding 為零。消融包括無歷程、無 embedding 收縮、只訓練球種、訓練座標抖動。單任務模型未訓練的其他 head 不評分。座標抖動僅施於訓練期，固定為訓練 X IQR 的 2%，Y 為其 1.2 倍；驗證與校準不改動。這是單一固定預算試驗，不能推論所有超參數配置的優劣。

LightGBM 為每任務一個 native multiclass booster。投手／打者 ID 明確標為 categorical；歷程摘要包括平均與最後一球 token、長度與空歷程指示。GRU 的訓練損失為球種 1.0，分區／主結果／條件結果各 0.35，分區未知時遮罩相關項。CPU 固定 seed，每個 GRU 最多 10 epochs、每 batch 1024；驗證球種 loss 連續 3 epochs 無改善即停止。LightGBM 上限 140 rounds、驗證 early stopping 18 rounds。

以未校準驗證球種 log loss 選模；0.005 nats 內依情境 LightGBM、歷程 LightGBM、GRU 的順序選擇較簡單者。GRU 的分區及主結果 log loss 不得比歷程 LightGBM 多 0.03 nats。完整結果如實保留，不能因為希望展示 GRU 或歷程而修改規則。最終模型的能力 flag 依所選模型實際特徵設定。

## 校準與推薦

選定模型後，既有 calibration 區間的完整日期依時間順序約分成 40% 溫度擬合、30% conformal 分位數、30% 獨立 audit。日期、場數與筆數都存入模型與報告。四個 head 各自擬合溫度；三個主 head 使用 score `1-p(true)`，以 `ceil((n+1)*0.9)` 排序位置的有限樣本分位數形成預測集合。audit 不參與溫度或分位數擬合，報告覆蓋率、平均集合大小、前後 ECE 與 log loss。

時間樣本可能有分布漂移；這些是實測結果，不宣稱交換性條件下的理論保證必然成立。主結果集合也不能解釋為候選推薦成功率。

推薦僅考慮投手曾投過至少五次的球種，且候選球種×區域在訓練期至少十個樣本。候選的條件結果機率，乘上同一目前狀態下「觀察結果的訓練期平均 ΔRE」，依預估失分變化由低到高排列。ΔRE 值以 30 個樣本向該結果的整體值收縮。此為觀察關聯；沒有反事實識別、沒有證明執行該配球會因果降低失分。

## 部署與重現

線上 artifact 為單一 UTF-8 LF JSON：LightGBM 使用 native model text，GRU 使用 NumPy 可讀權重，不需要 PyTorch runtime。匯出會對三主 head 及條件結果 head 逐一檢查 NumPy 與 PyTorch 的最大機率絕對誤差不超過 `2e-5`。manifest 使用模型檔實際位元組的 SHA-256。

```powershell
# 小型真資料端到端檢查，輸出與正式成果完全隔離
rtk proxy .venv\Scripts\python.exe scripts/build_week2.py --smoke --threads 4

# 正式固定預算比較，輸出 artifacts/week2 與 docs/week2
rtk proxy .venv\Scripts\python.exe scripts/build_week2.py --threads 4 --epochs 10 --rounds 140

rtk proxy .venv\Scripts\python.exe -m pytest tests/test_week2_models.py -q
```

正式部署仍需另外量測 API 的暖機 p95 與服務 RSS；訓練時間、訓練程序記憶體不能當成 Render 服務用量。驗收門檻為暖機 p95 <500ms、服務 RSS <400 MiB，通過前不可把候選 artifact 宣稱為已完成正式部署。

參考：[PyTorch GRU 定義](https://docs.pytorch.org/docs/stable/generated/torch.nn.GRU.html)、[LightGBM 參數](https://lightgbm.readthedocs.io/en/stable/Parameters.html)、[Conformal prediction 方法論文](https://arxiv.org/abs/2107.07511)。
