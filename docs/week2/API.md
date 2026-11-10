# 第二週 API 契約

更新日期：2026-11-10。正式 API 位址為 `https://pitchadvisor-api.onrender.com`，互動規格為 [`/docs`](https://pitchadvisor-api.onrender.com/docs)。實際線上版本以 `/health` 為準；本文件與真實第二週模型的本機回應核對過。

- 第二週模型：`week2-sequence-v1`，所選候選為 `lightgbm_history`。
- 資料版本：`rebas-2023-2025-regular-v1`；模型訓練截止 `2024-08-14`。資料版本名稱包含 2025，不代表模型使用 2025 訓練或評測。
- 四個能力旗標 `sequence`、`batter_conditioned_model`、`conformal`、`conditional_result` 在此版本均為 `true`；前端仍應依實際回應判斷。
- 公開端點不需要 Supabase 金鑰。Supabase 存取由後端處理，請求中不傳送金鑰。

## 端點

| 方法／路徑 | 用途與主要回應 |
|---|---|
| `GET /health` | `status`、`model_version`、`data_version`、`data_cutoff`、`capabilities`、`data_source`、`data_source_error`。模型未就緒回 503。 |
| `GET /players` | `players`、資料版本與截止日；可用 `role=pitcher` 或 `role=batter`、`q=姓名片段` 篩選，依樣本數遞減排序。每位球員含 `id, role, name, hand, sample_count, data_version`。 |
| `GET /metadata` | 資料稽核摘要、`training_pitches`、`pitch_types`、`sequence_schema`、模型能力與校準摘要。 |
| `GET /model-info` | 模型版本、選模規則、各候選驗證摘要、獨立校準稽核結果。不回傳模型權重、樹或環境設定。 |
| `POST /predict` | 依目前情境及可選歷程重新推論，回傳下述三個任務、候選推薦與不確定性。 |

## 推論請求

請用 `Content-Type: application/json`。物件不接受未定義欄位，數字與布林使用 JSON 原生型別。

| 欄位 | 規則 |
|---|---|
| `pitcher_id`、`batter_id` | 從 `/players` 取得相應角色的 ID，不以姓名代替。 |
| `state.balls` | 整數 0–3。 |
| `state.strikes` | 整數 0–2。 |
| `state.outs` | 整數 0–2。 |
| `state.bases` | 恰好三個布林值，依序為一壘、二壘、三壘；不接受 `0/1` 代替。 |
| `sequence` | 可省略或為空陣列；有提供時，須為**當前打席從 0–0 起、待預測球之前的完整歷程**，最多 16 球。 |
| `sequence[].pitch_type` | 使用 `/metadata.pitch_types` 內的球種代碼。 |
| `sequence[].zone` | 整數 0–12，或未知時為 `null`／省略。 |
| `sequence[].velocity` | 有限數字 40–180，單位 km/h；未知時為 `null`／省略，不填 0。 |
| `sequence[].result` | `ball`、`called_strike`、`swinging_strike`、`foul`、`in_play` 五者之一。 |

分區採投手視角：好球帶內 0–8 為由左上到右下的九宮格；外圍 9 上、10 右、11 下、12 左。分區定義與人工座標限制詳見 [資料字典](../DATA_DICTIONARY.md)。

有歷程時，重播結果必須等於 `state.balls/strikes`。兩好球後的一般界外球仍維持兩好球。第四顆壞球、第三個好球或擊入場內會終結打席，不能再對同一打席預測下一球。`in_play` 雖是合法結果名稱，但包含它的非空歷程會被判定為打席已結束。

空歷程代表未知／未提供歷程，因此可搭配任何合法球數；它不宣稱球數是 0–0。更換打者或投手時應清除歷程；此 schema 沒有過去投手 ID，不能表示打席內換投前後的混合序列。不要只截取最後幾球假裝完整打席。

以下為第二週實際模型已驗證回 200 的範例；部署不同資料版本時應重新取得球員 ID 與球種代碼：

```json
{
  "pitcher_id": "KPTzi",
  "batter_id": "LlGVK",
  "state": {
    "balls": 1,
    "strikes": 1,
    "outs": 0,
    "bases": [false, false, false]
  },
  "sequence": [
    {"pitch_type": "CH", "zone": null, "velocity": null, "result": "ball"},
    {"pitch_type": "CH", "zone": 4, "velocity": 145.0, "result": "called_strike"}
  ]
}
```

此範例回應 `sequence_used: true`，`history_summary` 為兩球、1–1 球數、未知分區一球、未知球速一球。

## 推論回應與解讀

| 欄位 | 意義 |
|---|---|
| `pitch_probabilities` | `{pitch_type, name, probability}` 陣列。 |
| `zone_probabilities` | 13 個 `{zone, name, probability}`。 |
| `result_probabilities` | 五種結果的 `{result, probability}`。各任務機率各自正規化，浮點計算可能有微小總和誤差。 |
| `recommendations` | 最多五個候選，依 `expected_run_change` 由低至高排序。含球種、分區、直接／匯集樣本數、條件結果機率、方法與 `causal: false`。 |
| `sample_counts` | `pitcher`、`batter`、`matchup`、`league_state` 的訓練樣本支持。 |
| `sequence_used`、`history_summary` | 明確標示是否使用歷程，以及長度、重建球數、未知分區／球速數；摘要也含 `sequence_used`。 |
| `prediction_sets` | `pitch`、`zone`、`result` 各含 `labels`、`target_coverage`、`threshold`。 |
| `prediction_set` | 保留舊介面名稱，第二週等於 `prediction_sets.pitch.labels`。 |
| `calibration` | 溫度、集合門檻、日期切分與獨立 audit；`method` 為 `temperature+split-conformal`。 |
| `model_info` | 所選候選、驗證指標與校準 audit 的公開摘要；`test_evaluated: false`。 |
| `source_mode` | 本次服務啟動時的模型／Supabase 核對狀態，見下表。 |
| `warnings`、`elapsed_ms` | 解讀限制與伺服器推論時間；此時間不含瀏覽器網路往返或 Render 休眠喚醒。另含版本、截止日、模型名稱與能力旗標。 |

溫度校準調整機率；split conformal 使用另一段資料決定 `1-p(true)` 門檻，再由未參與擬合與門檻計算的 audit 量測覆蓋率。90% 是名目目標，不是每個候選的成功率，也不是必然達成的實戰保證。`conditional_result` 有獨立溫度，但不套用主結果任務的 conformal 集合。完整方法與分數見 [MODELING_METHOD.md](MODELING_METHOD.md)、[RESULTS.md](RESULTS.md)。

推薦只考慮投手訓練期至少投過五次的球種，以及匯集樣本至少十次的球種×區域。排序使用候選的條件結果分布乘上訓練期的結果 ΔRE 價值；它反映歷史觀察關聯，未識別反事實或證明因果降低失分。人工記錄的實際落點也不等於投手瞄準點。

## 資料來源與降級

| `source_mode`／`health.data_source` | 意義 |
|---|---|
| `supabase_verified_snapshot` | 啟動時已核對 Supabase 的模型版本、資料版本、截止日、SHA 與完整球員目錄投影；推論使用已載入的模型快照，不是每次都即時讀取資料庫。 |
| `local_snapshot` | 使用本地已校驗模型，未設定雲端核對。 |
| `local_snapshot_supabase_unavailable` | 雲端暫時無法核對，保留本地模型服務；附安全錯誤代碼與警語。 |
| `local_snapshot_supabase_mismatch` | 雲端模型或球員目錄與本地不符，保留本地模型服務；不可當成 Supabase 串接驗收成功。 |

`status: ready` 僅表示模型可提供服務。驗收三平台串接時還要核對預期模型版本及 `supabase_verified_snapshot`。核對是啟動時快照，並非持續資料庫監控。

回復第一週 `week1-frequency-v1` 時，`sequence`、`batter_conditioned_model`、`conformal` 能力為 `false`；空歷程仍可推論，非空歷程回 `history_not_supported`。第一週的 `prediction_set`、`prediction_sets`、`calibration`、`model_info` 為 `null`，前端應隱藏對應功能，不虛構校準或歷程結果。

## 錯誤處理

| HTTP 狀態 | 處理 |
|---|---|
| `404` | 球員 ID 不在該模型相應角色的目錄內，重新讀取 `/players`。 |
| `422`，`detail` 為陣列 | JSON 型別、範圍、必要欄位、最多 16 球、額外欄位等 schema 錯誤。 |
| `422`，`detail` 為物件 | 語意錯誤，含 `code`、`message`，部分含從 0 起算的 `index`。可能為 `history_unknown_pitch_type`、`history_count_mismatch`、`history_pa_ended`、`history_after_pa_end`、`history_not_supported`。 |
| `503` | 模型未就緒，`detail.code` 可能為 `model_checksum_mismatch`、`model_manifest_version_mismatch`、`configured_model_version_mismatch`、`unsupported_model_format`、`model_bundle_load_failed`、`model_not_ready`。請查部署設定與私有日誌，不將憑證貼入請求或回報。 |

API 不把底層 HTTP 例外字串或憑證回傳給用戶。瀏覽器 CORS 只允許後端設定的來源；公開 API 不使用 cookie 憑證。前端應處理 Render 喚醒等待、取消過期請求，並清除舊情境的結果，避免在新情境下顯示舊推薦。

驗證：`rtk proxy .venv\Scripts\python.exe -m pytest tests/test_api.py tests/test_sequence.py -q`。本文編寫時真實第二週 artifact 與第一週相容測試共 34 項通過，沒有跳過真模型檢查。HTTP 與資源驗收另見 `local_verification.json`／部署驗收紀錄；本機數字不能視為 Render 的延遲。
