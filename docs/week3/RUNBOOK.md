# 展示前檢查與故障處理

此操作手冊更新於2026-11-11。模型固定為 `week2-sequence-v1`，SHA-256為 `aa3e984758796843bce68aa71fb06a4c84739a7d8048be475cc1bfe6855671ec`。

## 展示前

1. 開啟正式網站 `https://happy123903.github.io/pitchadvisor-tw/`，確認球員名單、版本及下一球分析出現。
2. 確認 API `/health` 的 `status=ready`、`test_evaluated=true`、模型SHA一致，且 `data_source=supabase_verified_snapshot`。單看 ready 不代表已核對 Supabase。
3. 用 `history-two` 的兩球範例確認球數1–1、已使用歷程及預測集合；顯示2025最終成績時說明全部樣本與名單內子集的差異。
4. 預先啟動本機完整模式並確認可用，準備固定案例、成果簡報與示範影片；不用現場才下載Python套件。

## 等待與備案

本次真正的隔夜閒置恢復測得 **51.514秒**：首個請求25秒逾時，有限重試後ready，沒有重新部署或重啟來製造通過。見 [cold_start.json](cold_start.json)。這是一次實測，不是未來上限。

網頁在等待20秒後顯示喚醒提示，單次連線最長65秒；逾時後可重試或直接切換「固定示範案例」。API失敗時會移除舊圖表，不把舊情境當新結果。固定案例僅顯示檔案中預算結果，任意投打／球數編輯會停用。

本機完整模式使用同一凍結模型，即時重算新輸入，並停用雲端連線。固定案例則可在後端完全不可用時展示。啟動、封裝與事前依賴準備見 [OFFLINE_GUIDE.md](OFFLINE_GUIDE.md)。

## 查核與恢復

| 觀察 | 處理 |
|---|---|
| 網頁載入，API等待很久 | 先等有限等待流程；可手動重試，或切換固定案例／本機模式。不要無限重新整理 |
| `/health` 503 | 查Render啟動紀錄的安全錯誤碼；核對MODEL_VERSION、MODEL_BUNDLE_DIR、manifest及Git模型位元組 |
| `model_checksum_mismatch` | 保留 `.gitattributes` binary設定；回到已驗證的模型位元組，勿刪除SHA檢查 |
| ready但Supabase未核對 | 查project origin、伺服器secret及對應登錄SHA／球員投影；不把快照降級叫做雲端核對成功 |
| `/evaluation` 503 | 最終報告與正在服務的模型SHA不一致或報告缺少；不得套用別版成績 |
| 固定案例無法載入 | 確認Pages子路徑與 `demo/cases.json` 存在、版本一致；不要即興補假回應 |
| 本機port被占用 | 先查本專案的程序紀錄，使用Stop-Offline；不要終止不明來源程序 |

若確實需回復網站程式，可從已驗證的第二週程式版本 `fcce803` 回復並發布；它與目前模型版本和Supabase資料相容。這會暫時沒有第三週最終測試頁／固定案例新功能。部署回復只改程式，不回復資料庫；沒有必要重跑第一週migration或重建Supabase。

若要回到第一週模型，需同時設定 `MODEL_BUNDLE_DIR=artifacts/baseline` 與 `MODEL_VERSION=week1-frequency-v1`，前端將明示不支援歷程及預測集合。此為不同能力的備援，並非本次正式模型。模型切換後重新核對SHA與Supabase來源，不以單一綠燈判定完成。

## 不可省略的解釋

- 資料來自Rebas Open Data（ODC-By），為人工紀錄的實際落點；不是意圖落點或即時串流。
- 全部2025有效樣本中，球種log loss比投手頻率基準差2.27%；API名單內子集改善3.56%。未知投手的球種集合覆蓋僅68.86%，不能將名單內結果推廣到所有球員。
- 90%是校準時的名目目標；2025全部樣本球種實測83.74%。推薦屬觀察關聯，不代表因果或實戰保證。
- 不因展示不順或成績下降，偷偷更換模型、校準器、測試年份、付費方案或未驗證的資料。
