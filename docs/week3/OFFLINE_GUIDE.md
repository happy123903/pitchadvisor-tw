# 本機完整推論與斷網備案

本備案提供和正式服務相同的凍結 LightGBM 模型、前處理、校準器與真實即時推論。網頁及 `/api` 由單一本機程序提供，連到 `http://127.0.0.1:8765/`，不依賴雲端 API。固定案例另有明確標示，不會冒充任意情境即時結果。

## 在斷網之前準備

既有專案已安裝 `.venv` 與前端套件時，在專案根目錄執行：

```powershell
rtk proxy .venv\Scripts\python.exe scripts/build_offline_bundle.py
rtk proxy powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/Start-Offline.ps1
```

建置會用 `VITE_API_BASE_URL=/api`、`PAGES_BASE_PATH=./` 編譯網頁並複製到 `.cache/offline-web`；雲端用的建置應另以正式 API 網址重新執行。啟動後確認 `http://127.0.0.1:8765/api/health` 回傳 `status=ready`、`model_version=week2-sequence-v1`、`data_source=local_snapshot`，SHA 應為 `aa3e984758796843bce68aa71fb06a4c84739a7d8048be475cc1bfe6855671ec`。

下載包為 `deliverables/PitchAdvisor_Offline.zip`。它包含編譯網頁、必要 API／模型程式、模型及 manifest、來源授權、真實固定案例與最終測試報告。依明確檔案清單打包，沒有 `.env`、金鑰、原始訓練資料、`.venv`、PyTorch 或 `node_modules`。`OFFLINE_MANIFEST.json` 記錄包內每個檔案的 SHA-256。

## 解壓縮包的使用條件

**ZIP 不內含 Python 與第三方 runtime。新電腦不能在完全未準備的斷網環境直接執行。** 請在斷網之前安裝 Python 3.12 及 `requirements-lock.txt` 套件，或使用已驗證且仍位於原安裝位置的既有 `.venv`。Python venv 通常依賴原本的 Python 安裝；不要只複製 `.venv` 到另一台電腦就假設可攜。

若需全新環境，在有網路時先準備（不需要 training 群組或 PyTorch）：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

解壓縮後進入 `PitchAdvisor_Offline` 資料夾，指定已準備的 Python：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/Start-Offline.ps1 -PythonExe "C:\完整路徑\環境\Scripts\python.exe"
```

執行本包不需要 Node 或 RTK。也可前景執行 `python scripts/serve_offline.py --port 8765`，以 Ctrl+C 停止；`--web-dir` 可指定另一份已編譯的本機網頁。

## 斷網演練

1. 啟動本機服務後開啟 `http://127.0.0.1:8765/`，確認資料與模型版本。
2. 關閉外部網路連線，保留本機 loopback；重新載入頁面，確認 JS／CSS／案例仍由本機取得。
3. 變更投打、球數與壘包，新增合法完整歷程；確認機率與推薦隨實際輸入改變。
4. 查看 2025 最終測試摘要，並切換「固定示範案例」檢查模式標示。固定案例只切換已計算輸出。
5. 連線恢復後再選擇使用正式網站；本機服務本身始終停用雲端憑證與雲端核對。

程式在匯入 API 前停用 dotenv、清空 Supabase URL／secret，固定本機模型目錄與版本；啟動時明確執行掛載 API 的 lifespan。測試會攔截所有 HTTP client 的外部傳輸，並實際驗證靜態檔重新取得、模型健康、名單、最終摘要與任意合法預測。測試與實際瀏覽器斷網結果分開記錄，不把單純固定案例當作完整推論證據。

2026-11-11 已實際通過：3 項離線測試、真正 loopback HTTP 靜態檔重載與新情境推論、校準器／SHA 一致、Windows launcher 與真正 Python child 啟停，以及解壓縮目錄搭配既有 Python runtime 的獨立執行。詳細程序與 ZIP 私有值掃描紀錄保存在儲存庫 `docs/week3/offline_verification.json`；ZIP 不包含任何真實金鑰。這些查核不代表未安裝 Python 的新電腦已備妥。

同日亦完成真實 Chrome 操作：阻擋所有外部 HTTP、保留 `127.0.0.1` loopback，先確認外部負向探針確實被阻擋，再重新載入本機資產並新增非固定情境與歷程。實際 POST 的輸入與新機率分布均已確認；切換固定案例後輸入唯讀且不額外呼叫 API。這是瀏覽器層的外部網路阻擋演練，沒有切換 Windows 實體網路或飛航模式。

## 停止與故障處理

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/Stop-Offline.ps1
```

啟動器以隱藏視窗啟動 Python，記錄唯一 instance ID、launcher 與實際推論程序 PID。停止器只處理命令列同時匹配本專案腳本絕對路徑及該 instance ID 的 Python 程序，並再次核對建立時間，避免重用 PID 誤停其他程序。Windows venv 的真正服務 child 也會停止。

若 8765 已使用，可用 `Start-Offline.ps1 -Port 8766`。啟動未成功請查看 `.cache/offline.stderr.log`。模型 SHA 不符會拒絕啟動；請還原凍結檔案，不要跳過校驗。缺少套件時應在有網路的準備階段補齊，不要把展示當天的網路當作必要條件。

資料來源：[Rebas Open Data](https://github.com/rebas-tw/rebas.tw-open-data)，ODC-By 授權副本保留於 `docs/sources/REBas-LICENSE`。模型仍有最終測試中已揭露的 OOD、覆蓋率與觀測偏差限制，詳見 [FINAL_RESULTS.md](FINAL_RESULTS.md)。
