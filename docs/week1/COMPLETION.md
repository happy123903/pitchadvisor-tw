# 第一週交付狀態

日期：2026-11-09。所有本機檔案位於 `C:\Users\user\Desktop\炫晟\野革盃`，v2 與原簡報保留。

## 已完成

- [x] 從使用者指定官網確認資料連結，再下載官方 Releases 的四份 2023–2025 例行賽 ZIP。
- [x] 記錄下載來源、版本、位元組數、ZIP CRC、SHA-256 與官方 schema。
- [x] 攤平 1,020 場比賽、293,482 筆投球事件，排除同 ZIP 合併檔，保留事件來源索引。
- [x] 球員 ID 與別名查核、前球球數重建、缺值／異常標記、不可還原壘包遮罩。
- [x] 13 分區、年度與球場品質盤點、訓練期座標診斷圖與資料字典。
- [x] 固定訓練／驗證／校準／測試切分；2025 年未用於建模與成效選擇。
- [x] 訓練期狀態價值函數、聯盟球數基準、投手球數平滑基準及歷史候選排序。
- [x] FastAPI 真實模型查詢、名單、健康檢查、版本校驗與必要錯誤處理。
- [x] React／TypeScript 介面：情境選擇、機率圖、13 區熱圖、候選與樣本資訊。
- [x] 本機 API、前端與 Vite 代理實際 HTTP 驗證；20 次暖機請求及程序記憶體紀錄。
- [x] 23 項自動測試通過，TypeScript 與前端正式建置通過。
- [x] Supabase 遷移、權限、私有 bucket 與可重跑匯入程式；已完成離線 dry run。
- [x] Render Free Blueprint、GitHub Pages／CI 工作流程、環境範例與操作 README。

## 尚未完成：需要建立／連接雲端專案

使用者已確認目前尚未建立 GitHub 專案儲存庫、Supabase 專案與 Render 服務；目前也未提供這三者的專案設定或服務憑證。因此以下不能標示為已完成：

- [ ] 新建本專案 GitHub 儲存庫並上傳程式與模型包。
- [ ] 在 Supabase 真正執行遷移、匯入資料並驗證匿名權限。
- [ ] 部署 Render，實測雲端記憶體、冷啟動與 API。
- [ ] 設定 GitHub Pages 變數並首次發布公開網址。

**因此，第一週的本機實作與可部署設定已交付，但 v3 第 5–7 天涉及的真實雲端匯入與首次線上部署尚未完成。** 本機 HTTP 成功不等於雲端上線成功。

已提供 Supabase 與 Render 的連接方式；連接後可沿用現有程式完成雲端步驟。GitHub 目前連接器可讀寫既有儲存庫，但沒有建立新儲存庫的功能；可先在 GitHub 建立本專案專用儲存庫，再提供網址。不要把 API 金鑰貼在聊天。

## 驗證證據

- [資料與基準結果](RESULTS.md)：驗證集 16,491 筆；聯盟球數 log loss 1.5941，投手球數平滑基準 1.2446。
- `baseline_metrics.json`：真實驗證指標，`test_evaluated=false`。
- `data_audit.json`、`split_manifest.json`：資料品質與逐場切分。
- `system_verification.json`：本機 HTTP、代理與暖機延遲；數據非雲端量測。
- `local_process_memory.json`：本機程序工作集，包含 Windows Python launcher 與真正的子程序。
- `artifacts/baseline/manifest.json`：模型與資料版本、校驗碼。

## 本次驗證限制與第二週邊界

瀏覽器控制服務不可用，因此已做 API、前端 HTTP、代理、TypeScript 與建置檢查，**未完成真實瀏覽器的視覺與點擊驗收**。若服務恢復，需補查桌面、手機版與連續切換情境。

打者條件建模、序列摘要／編輯、LightGBM、GRU、conformal 與校準屬第二週；目前 API 對非空序列明確拒絕，網站也明示尚未使用打者能力。這些能力沒有以假數字或預先算好的案例冒充。

重開本機：`powershell -NoProfile -File scripts/Start-Local.ps1`，再開 `http://127.0.0.1:5173`。停止：`powershell -NoProfile -File scripts/Stop-Local.ps1`。
