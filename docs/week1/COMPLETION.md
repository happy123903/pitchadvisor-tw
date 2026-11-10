# 第一週交付狀態

更新日期：2026-11-10 18:18（Asia/Taipei）。三平台部署與公開 HTTP／API 串接驗收通過；完整證據見 `deployment_verification.json`。所有本機檔案位於 `C:\Users\user\Desktop\炫晟\野革盃`，v2 與原簡報保留。

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
- [x] Supabase 遷移、權限、私有 bucket 與可重跑匯入程式；已完成實際雲端匯入，並查核四表筆數、RLS／角色權限、私有模型下載與 SHA-256。
- [x] Render Free Blueprint、GitHub Pages／CI 工作流程、環境範例與操作 README。
- [x] Render 修正版 `8a3c526` 已 Live；正式 `/health`、`/players`、`/predict` 均 HTTP 200，Supabase 整合與 Pages origin 的 CORS 已驗證。
- [x] GitHub Pages 已發布，最新建置與 deploy job 成功；公開 HTML、JavaScript、CSS 及其內的 API 網址均已核對。

## 雲端進度與尚待驗證項目

2026-11-10 已確認 Supabase 專案 `pitchadvisor-tw` 正常運作，實查為 377 球員、826 球種庫、75,424 統計列及 1 個模型版本。初次匯入 404 是 Project URL 多了 `/rest/v1/`，已修正。Render 初次健康檢查失敗是 Git 自動換行改變模型位元組；已新增 `.gitattributes` 並重新加入原始模型，提交及推送 `8a3c526`。正式 API `https://pitchadvisor-api.onrender.com` 已 Live，資料來源為 `supabase_verified_snapshot`。Blueprint 尚顯示 17:30 的失敗同步，與 17:40 已成功的服務部署為不同紀錄；本次未重跑 Blueprint 同步。

- [x] 確認 GitHub 遠端模型 blob、`.gitattributes` 與 Actions；最新版 CI 及 Pages workflow 均成功，公開儲存庫未包含 `.env`。
- [x] 在 Supabase 真正執行遷移、匯入資料並驗證資料表 RLS、匿名角色無表權限、後端讀寫權限及私有模型檔。
- [x] 部署 Render 並驗證正式 API、Supabase 整合及 CORS。
- [x] 取得 Render 雲端記憶體樣本；已觀察期間的峰值約 109.8 MiB、上限約 512 MiB，非壓力測試結論。
- [ ] 驗證閒置後喚醒穩定性與冷啟動；本輪曾遇外部請求逾時，同版本重新部署後已恢復並重驗通過，不能宣稱喚醒問題永久解決。
- [x] GitHub Pages 變數與首次發布已生效，正式網址 `https://happy123903.github.io/pitchadvisor-tw/`；成功的手動 workflow 為 `42796194047`。

**GitHub Pages、Render 與 Supabase 均已部署，公開 HTTP／API 串接驗收通過。** 真實瀏覽器視覺／點擊、手機版及閒置後喚醒穩定性仍待驗收，不能把這次部署確認當成所有體驗與負載測試已完成。

部署重現方式保留於 [詳細上線步驟](../DEPLOYMENT_STEP_BY_STEP.md)，Actions Variables 的 `VITE_API_BASE_URL` 已在發布資源中確認為 `https://pitchadvisor-api.onrender.com`。使用者的 IDE 選取內容曾將 Supabase secret key 帶入聊天，已提醒撤銷換發並更新本機與 Render；這是金鑰暴露問題，並非已驗證出金鑰無效。本輪未換發金鑰，不記錄其內容。

## 驗證證據

- [資料與基準結果](RESULTS.md)：驗證集 16,491 筆；聯盟球數 log loss 1.5941，投手球數平滑基準 1.2446。
- `baseline_metrics.json`：真實驗證指標，`test_evaluated=false`。
- `data_audit.json`、`split_manifest.json`：資料品質與逐場切分。
- `system_verification.json`：本機 HTTP、代理與暖機延遲；數據非雲端量測。
- `local_process_memory.json`：本機程序工作集，包含 Windows Python launcher 與真正的子程序。
- `artifacts/baseline/manifest.json`：模型與資料版本、校驗碼。
- `supabase_verification.json`：2026-11-10 實際雲端匯入、資料筆數、角色權限與模型讀回校驗；不含密鑰。
- `render_verification.json`：正式部署狀態、健康檢查、球員／推論 API、Pages CORS 與 Blueprint 舊紀錄；不含密鑰。
- `deployment_verification.json`：2026-11-10 18:18 三平台最終確認、GitHub 發布／CI、Supabase 實查、公開資源／推論／CORS 及同版本重新部署紀錄。

## 本次驗證限制與第二週邊界

先前瀏覽器控制受限；本次最終部署確認採公開 HTTP／API、已發布資源與平台狀態查核，**未進行真實瀏覽器的視覺與點擊驗收**，仍需補查桌面、手機版與連續切換情境。

打者條件建模、序列摘要／編輯、LightGBM、GRU、conformal 與校準屬第二週；目前 API 對非空序列明確拒絕，網站也明示尚未使用打者能力。這些能力沒有以假數字或預先算好的案例冒充。

重開本機：`powershell -NoProfile -File scripts/Start-Local.ps1`，再開 `http://127.0.0.1:5173`。停止：`powershell -NoProfile -File scripts/Stop-Local.ps1`。
