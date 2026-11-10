# 球路參謀 PitchAdvisor TW

以 Rebas 中職歷史逐球資料，建立可即時查詢的配球分析工具。前端為 React／TypeScript，後端為 FastAPI，預計部署至 GitHub Pages、Supabase 與 Render。

**第一週狀態**：資料下載、清洗、資料查核、頻率基準、價值函數、13 分區、本機 API 與前端已完成；雲端專案尚未建立，實際 Supabase 匯入與公開網站部署仍待完成。詳見 [第一週交付狀態](docs/week1/COMPLETION.md)。

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

目前版本可選投打、球數、出局數與壘包，查看球種分布、13 區落點、候選失分變化及樣本。**打者目前只用於樣本查核，不參與球種機率建模；非空序列會明確回報尚未支援。** 序列摘要、LightGBM、GRU、校準及預測集合依 v3 排在第二週，沒有用假結果替代。

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

資料來源鏈為：[野革盃官網](https://blog.rebas.tw/articles/4136) → [官方 Open Data](https://github.com/rebas-tw/rebas.tw-open-data) → 官方 Releases。下載程式驗證 ZIP 大小、CRC 與 SHA-256，並在 `docs/sources/download_manifest.json` 保存來源、版本與校驗碼。2025 年選用 2026-11-07 發布的更新版本；未混入 2026 年賽事。

只讀單場 JSON，不讀同一 ZIP 中的合併檔；先取得四份完整例行賽 ZIP，再執行建置。網路失敗時可重跑下載，不會把 `.part` 當作完成檔案。

## 成果與資料

- [資料與基準結果](docs/week1/RESULTS.md)：年度筆數、缺值率、切分與真實驗證指標。
- [資料字典](docs/DATA_DICTIONARY.md)：欄位來源、時點、未知值與排除規則。
- `docs/week1/data_audit.json`：完整查核、球員名稱異常與事件分布。
- `docs/week1/split_manifest.json`：逐場固定時間切分。
- `data/processed/pitches.parquet`：攤平後逐球資料；`games.parquet`、`identities.parquet` 為比賽與身分對照。
- `artifacts/baseline/`：訓練期統計、價值函數、查詢快照與校驗 manifest。
- [三週完整計畫](野革盃黑客松_專案計畫書_v3.md)。

本週訓練截止 2024-08-14，驗證自 2024-08-16 起，校準自 2024-09-12 起；2025 年作為測試資料保留，未計算測試成績來挑模型。球員名單只由訓練期資料建立，未見過的 ID 不自動按姓名合併。

## 驗證

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/supabase_sync.py
.venv\Scripts\python.exe scripts/verify_local.py
```

最後一項需先啟動本機服務，會檢查實際 API、Vite 代理與 20 次暖機 HTTP 請求。效能結果只代表本機單一使用者，不代表 Render 免費服務或冷啟動。瀏覽器控制服務目前不可用，本次未執行真實瀏覽器視覺驗收，不能把 HTTP 驗證當成完整瀏覽器端到端測試。

## Supabase：建立後匯入

1. 建立本專案專用的 Supabase Free 專案，在 SQL Editor 執行 `supabase/migrations/202611090001_week1.sql`。
2. 複製根目錄 `.env.example` 為 `.env`，在本機填入專案 `SUPABASE_URL` 與伺服器端 secret／service-role key。不要貼到聊天、前端變數、程式碼或 Git。
3. 先執行 dry run，再指定 `--apply`：

```powershell
.venv\Scripts\python.exe scripts/supabase_sync.py
.venv\Scripts\python.exe scripts/supabase_sync.py --apply
```

匯入包含球員、投手可用球種、聚合統計、私有模型包與版本登錄。採主鍵 upsert，可重跑；只有表與模型包成功上傳後才登錄可服務版本。不要對其他專案或不相容資料表執行此遷移。

公開 API 由 FastAPI 限定，Supabase 表對匿名／一般登入使用者不開放，模型 bucket 為私有。後端高權限 key 可能繞過 RLS，僅在伺服器保存，不能把 RLS 當成該 key 的限制。

## Render：部署 API

1. 建立本專案 GitHub 儲存庫，提交原始碼、鎖定檔、`docs/` 與 `artifacts/baseline/`，排除原始資料、環境及 `.env`。
2. Render 以此儲存庫建立 Blueprint，使用根目錄 `render.yaml`，保持 Free 方案。
3. 設定 `SUPABASE_URL`、`SUPABASE_SECRET_KEY`，以及 `ALLOWED_ORIGINS=https://<GitHub帳號>.github.io`。CORS 來源不含儲存庫路徑。
4. 確認 `/health` 為 200 且版本符合。已提交的模型包可直接載入；缺少本機包時，會使用固定 `MODEL_VERSION` 從私有 Storage 下載並核對校驗碼。

Render 的執行檔案系統不作持久儲存；模型仍需保留在儲存庫或私有 Storage。API 回傳資料來源狀態，無法確認 Supabase 時會明示快照；沒有可用一致模型時回報 503。

## GitHub Pages：部署前端

1. 在儲存庫 Settings → Secrets and variables → Actions → Variables 設定 `VITE_API_BASE_URL`，值為已就緒的 Render HTTPS 網址。
2. Settings → Pages 選 GitHub Actions；推送 `main` 或手動執行 `pages.yml`。
3. 工作流程會檢查 API 變數、建置前端並發布。標準專案網址為 `https://<帳號>.github.io/<repo>/`。
4. 個人首頁型儲存庫 `<帳號>.github.io` 的 `PAGES_BASE_PATH` 應改成 `/`；本設定預設一般專案儲存庫。

`VITE_` 變數是公開設定，只放 API 網址。設定缺少時網站會清楚顯示錯誤，不能以固定假資料替代。正式建置的 `web/dist/` 需要 HTTP 服務，不應直接雙擊 HTML；本機優先使用 `Start-Local.ps1`。

## 限制與授權

人工座標可能有誤差；資料是實際落點，不是意圖落點。壘包移動若無法由事件唯一還原則標為未知；不完整半局不當作完整期望失分標籤。當前頻率基準與失分變化排序屬觀測資料分析，不宣稱因果或實戰保證。

資料來源：Rebas 野球革命 Open Data（ODC-By）。[官方授權](https://github.com/rebas-tw/rebas.tw-open-data/blob/main/LICENSE)與本機副本 `docs/sources/REBas-LICENSE`。第三方資料、程式套件與模型依各自授權使用；本文件沒有替原創專案程式碼另行指定開源授權。
