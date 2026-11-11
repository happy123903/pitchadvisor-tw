# 球路參謀 PitchAdvisor TW

以 Rebas 中職歷史逐球資料，建立依投打、情境與本打席歷程即時推論的配球分析工具。React／TypeScript 前端部署於 GitHub Pages，FastAPI 在 Render 執行，Supabase 保存資料與私有模型版本。

**第三週進度（2026-11-11）**：2025凍結模型最終測試、有限等待／重試、固定案例與本機完整推論、冷啟動及小型並發、九頁成果簡報與Demo腳本已完成；核心功能已發布至三平台並實查通過。Python75項、前端10項測試通過，4分40秒繁中字幕操作影片與最終交付封存亦已完成。完整證據見 [第三週交付紀錄](docs/week3/COMPLETION.md)。正式網站：[球路參謀](https://happy123903.github.io/pitchadvisor-tw/)。

## 第三週交付與展示

- [2025最終測試](docs/week3/FINAL_RESULTS.md)：99,729球，全部樣本球種log loss **1.400057**，比投手頻率基準1.368926差2.27%；API名單內69,044球則為1.225868，比基準1.271066改善3.56%。全部樣本球種集合覆蓋 **83.74%**，未知投手僅68.86%；名目90%不是保證。
- [離線指南](docs/week3/OFFLINE_GUIDE.md)及 `deliverables/PitchAdvisor_Offline.zip`：同版模型可即時重算任意合法情境，網頁與API都在127.0.0.1:8765；新電腦仍須事先安裝Python3.12及runtime，包內不含環境與憑證。
- 固定案例可由網站頂端切換，僅選三組已計算輸入輸出，所有情境編輯唯讀；即使後端不可用也可使用，不冒充自由輸入的即時推論。
- `deliverables/球路參謀_成果簡報_v5.pptx`、同名PDF與 [五分鐘Demo腳本](docs/week3/DEMO_SCRIPT.md)；原v4簡報保留。[示範影片](deliverables/球路參謀_示範影片_v1.mp4)長4分40秒，字幕已燒錄，無旁白；另附同名SRT與[影片說明](docs/week3/VIDEO_GUIDE.md)。
- [恢復手冊](docs/week3/RUNBOOK.md)：一次隔夜冷啟動51.514秒後恢復。網頁20秒顯示喚醒提示、65秒有限等待，失敗可重試或直接進入固定案例。

已完成準備時，完整本機模式可直接啟動：

```powershell
rtk proxy powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/Start-Offline.ps1
```

結束時使用 `scripts/Stop-Offline.ps1`，只停止本次擁有的程序。重新產生離線包用 `scripts/build_offline_bundle.py`，需在斷網前備好依賴。

## 快速開啟本機網站

本資料夾已準備 `.venv`、`web/node_modules` 與基準模型包，可直接在專案根目錄執行：

```powershell
powershell -NoProfile -File scripts/Start-Local.ps1
```

- 網站：<http://127.0.0.1:5173>
- API 文件：<http://127.0.0.1:8000/docs>
- 服務狀態：<http://127.0.0.1:8000/health>

預覽程序於背景啟動，不另外開視窗。結束時執行：

```powershell
powershell -NoProfile -File scripts/Stop-Local.ps1
```

目前版本可選投打、球數、出局數與壘包，新增／編輯／刪除歷程後重新推論；打者條件與歷程會影響模型。三項任務為球種、13 區落點與五類投球結果，另提供候選配球、訓練樣本數與預測集合。歷程需從同一打席 0–0 完整輸入，最多 16 球；未知球速／落點可留空，球數自動重建。換投或換打者時開始新打席。

驗證集球種 log loss：投手頻率 1.244698、情境 LightGBM 1.201012、序列 LightGBM **1.158778**、GRU 1.174469。校準稽核球種覆蓋率 **89.83%**，名目 90%，平均集合 2.52 類。各項比較與限制見 [第二週成果](docs/week2/RESULTS.md)。

## 從乾淨環境重建

需求：Python 3.12、Node.js 24、npm、uv。所有本機程式與資料均留在此專案目錄；以下以 Windows PowerShell 為例。

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.cache/uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path (Get-Location) '.tools/python'
$env:UV_PYTHON_BIN_DIR = Join-Path (Get-Location) '.tools/bin'
uv python install 3.12
uv sync --python 3.12 --locked
.venv\Scripts\python.exe scripts/download_data.py
.venv\Scripts\python.exe scripts/build_week1.py
Set-Location web
npm ci --cache ../.cache/npm
npm run build
Set-Location ..
```

Python 依賴鎖在 `uv.lock`，部署用套件鎖在 `requirements-lock.txt`；前端依賴鎖在 `web/package-lock.json`。原始資料與環境已列入 `.gitignore`，不隨原始碼上傳。

上述指令重建第一週資料與基準。第二週產物已提交，可直接服務；若要重新訓練，額外安裝 CPU 訓練群組（沿用上述 uv 目錄設定）：

```powershell
rtk proxy uv sync --python 3.12 --locked --group training
rtk proxy .venv\Scripts\python.exe scripts/build_week2.py --threads 4 --epochs 10 --rounds 140
```

`--smoke` 只作管線試跑，輸出到忽略的 `artifacts/week2-smoke/` 與 `docs/week2/smoke/`，不可部署。線上 runtime 不安裝 PyTorch；GRU 比較的 NumPy 匯出已與 CPU PyTorch 驗證一致。方法與重現設定見 [MODELING_METHOD.md](docs/week2/MODELING_METHOD.md)。

資料來源鏈為：[野革盃官網](https://blog.rebas.tw/articles/4136) → [官方 Open Data](https://github.com/rebas-tw/rebas.tw-open-data) → 官方 Releases。下載程式驗證 ZIP 大小、CRC 與 SHA-256，並在 `docs/sources/download_manifest.json` 保存來源、版本與校驗碼。2025 年選用 2026-11-07 發布的更新版本；未混入 2026 年賽事。

只讀單場 JSON，不讀同一 ZIP 中的合併檔；先取得四份完整例行賽 ZIP，再執行建置。網路失敗時可重跑下載，不會把 `.part` 當作完成檔案。

## 成果與資料

- [資料與基準結果](docs/week1/RESULTS.md)：年度筆數、缺值率、切分與真實驗證指標。
- [資料字典](docs/DATA_DICTIONARY.md)：欄位來源、時點、未知值與排除規則。
- `docs/week1/data_audit.json`：完整查核、球員名稱異常與事件分布。
- `docs/week1/split_manifest.json`：逐場固定時間切分。
- `data/processed/pitches.parquet`：攤平後逐球資料；`games.parquet`、`identities.parquet` 為比賽與身分對照。
- `artifacts/baseline/`：訓練期統計、價值函數、查詢快照與校驗 manifest。
- `artifacts/week2/`：正式序列模型、特徵編碼、校準器、第一週查詢快照與 SHA-256 manifest。
- [第二週比較、消融與校準](docs/week2/RESULTS.md)、[事前驗收規則](docs/week2/EXECUTION_PLAN.md)。
- [三週完整計畫](野革盃黑客松_專案計畫書_v3.md)。

訓練截止 2024-08-14，驗證自 2024-08-16 起，校準自 2024-09-12 起；2025已在模型凍結後作最終評估，未用來重選模型或校準。球員名單只由訓練期資料建立，未見過的 ID 不自動按姓名合併。

## 驗證

```powershell
rtk proxy .venv\Scripts\python.exe -m pytest -q
rtk proxy npm.cmd --prefix web test
rtk proxy npm.cmd --prefix web run build
rtk proxy .venv\Scripts\python.exe scripts/verify_week2.py --output .cache/local-recheck.json
rtk proxy .venv\Scripts\python.exe scripts/supabase_sync.py --bundle-dir artifacts/week2
```

`verify_week2.py` 自行啟停獨立本機 API，檢查真實歷程／打者效果、三任務與推薦、錯誤情境及 25 次暖機 HTTP。Windows 量測實際服務程序而非 venv launcher；本次峰值約 219 MiB、p95 約 4ms。這是本機單一使用者結果，不代表冷啟動或多人負載。雲端 HTTP／CORS 與真實瀏覽器操作分開記錄。

## Supabase：建立後匯入

1. 建立本專案專用的 Supabase Free 專案，在 SQL Editor 執行 `supabase/migrations/202611090001_week1.sql`。
2. 複製根目錄 `.env.example` 為 `.env`，在本機填入專案 `SUPABASE_URL` 與伺服器端 secret／service-role key。不要貼到聊天、前端變數、程式碼或 Git。
3. 先執行 dry run，再指定 `--apply`：

```powershell
rtk proxy .venv\Scripts\python.exe scripts/supabase_sync.py --bundle-dir artifacts/week2
rtk proxy .venv\Scripts\python.exe scripts/supabase_sync.py --bundle-dir artifacts/week2 --apply
rtk proxy .venv\Scripts\python.exe scripts/verify_supabase_model.py --output .cache/supabase-recheck.json
```

匯入包含球員、投手可用球種、聚合統計、私有模型包與版本登錄。採主鍵 upsert，可重跑；只有表與模型包成功上傳後才登錄可服務版本。不要對其他專案或不相容資料表執行此遷移。

公開 API 由 FastAPI 限定，Supabase 表對匿名／一般登入使用者不開放，模型 bucket 為私有。後端高權限 key 可能繞過 RLS，僅在伺服器保存，不能把 RLS 當成該 key 的限制。

## Render：部署 API

1. 使用本專案 GitHub 儲存庫，提交原始碼、鎖定檔、`docs/`、`artifacts/baseline/` 與 `artifacts/week2/`，排除原始資料、環境及 `.env`。
2. Render 以此儲存庫建立 Blueprint，使用根目錄 `render.yaml`，保持 Free 方案。
3. 設定 `SUPABASE_URL`、`SUPABASE_SECRET_KEY`，以及 `ALLOWED_ORIGINS=https://<GitHub帳號>.github.io`。CORS 來源不含儲存庫路徑。
4. 設 `MODEL_BUNDLE_DIR=artifacts/week2`、`MODEL_VERSION=week2-sequence-v1`（與 `render.yaml` 一致），確認 `/health` 為 200、版本符合，且 `data_source=supabase_verified_snapshot`。已提交的模型包可直接載入；缺少本機包時，會使用固定版本從私有 Storage 下載並核對校驗碼。

Render 的執行檔案系統不作持久儲存；模型仍需保留在儲存庫或私有 Storage。API 回傳資料來源狀態，無法確認 Supabase 時會明示快照；沒有可用一致模型時回報 503。

## GitHub Pages：部署前端

1. 在儲存庫 Settings → Secrets and variables → Actions → Variables 設定 `VITE_API_BASE_URL`，值為已就緒的 Render HTTPS 網址。
2. Settings → Pages 選 GitHub Actions；推送 `main` 或手動執行 `pages.yml`。
3. 工作流程會檢查 API 變數、建置前端並發布。標準專案網址為 `https://<帳號>.github.io/<repo>/`。
4. 個人首頁型儲存庫 `<帳號>.github.io` 的 `PAGES_BASE_PATH` 應改成 `/`；本設定預設一般專案儲存庫。

`VITE_` 變數是公開設定，只放 API 網址。設定缺少時網站會清楚顯示錯誤，不能以固定假資料替代。正式建置的 `web/dist/` 需要 HTTP 服務，不應直接雙擊 HTML；本機優先使用 `Start-Local.ps1`。

## 限制與授權

人工座標可能有誤差；資料是實際落點，不是意圖落點。壘包移動若無法由事件唯一還原則標為未知；不完整半局不當作完整期望失分標籤。候選依「候選球種／分區的條件結果機率 × 訓練期 ΔRE」排序，屬觀測資料分析，不宣稱因果或實戰保證。結果五分類排除觸身球等特殊事件；2025全部樣本13 區預測集合平均仍達 10.30 區，不能宣稱精準控球。2025最終成績已公開，未拿來選模；後續模型改動須另設新的前瞻評估。

資料來源：Rebas 野球革命 Open Data（ODC-By）。[官方授權](https://github.com/rebas-tw/rebas.tw-open-data/blob/main/LICENSE)與本機副本 `docs/sources/REBas-LICENSE`。第三方資料、程式套件與模型依各自授權使用；本文件沒有替原創專案程式碼另行指定開源授權。
