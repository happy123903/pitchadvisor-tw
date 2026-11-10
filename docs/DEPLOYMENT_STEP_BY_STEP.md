# GitHub Pages＋Supabase＋Render 詳細上線步驟

查核日期：2026-11-10。GitHub 帳號為 `happy123903`，專案儲存庫為 `pitchadvisor-tw`。三平台第一週已建立並驗收；第1–7節保留從零建立的說明，既有專案更新第二週請直接依下段，不必重建。

## 既有專案更新第二週

1. 保留本機 `.env` 及 Render 既有 secret；只更新 `MODEL_VERSION=week2-sequence-v1`、`MODEL_BUNDLE_DIR=artifacts/week2`。
2. 在專案根目錄先測試與 dry run，再匯入已校驗的模型。每次部署不同版本都應先檢查 manifest，不上傳 smoke 產物。

```powershell
rtk proxy .venv\Scripts\python.exe -m pytest -q
rtk proxy .venv\Scripts\python.exe scripts/supabase_sync.py --bundle-dir artifacts/week2
rtk proxy .venv\Scripts\python.exe scripts/supabase_sync.py --bundle-dir artifacts/week2 --apply
rtk proxy .venv\Scripts\python.exe scripts/verify_supabase_model.py
```

3. 提交原始碼、鎖定檔與 `artifacts/week2/`；保留 `.gitattributes` 兩版模型的 binary 設定。不要提交 `.env`、原始資料或訓練環境。
4. 推送 main 後，Render Blueprint自動同步 `render.yaml` 的兩個非secret設定，服務與 Pages 的既有 workflow 自動發布。若需手動調整 Render，只合併上述兩個鍵，保留 Supabase key 與 CORS。不要同時重建服務或新增付費方案。
5. 檢查 `/health` 200、`model_version=week2-sequence-v1`、`data_source=supabase_verified_snapshot`；網頁新增一球壞球後應顯示1–0及已使用歷程，再執行雲端查核：

```powershell
rtk proxy .venv\Scripts\python.exe scripts/verify_week2.py --api-url https://pitchadvisor-api.onrender.com --frontend-url https://happy123903.github.io/pitchadvisor-tw/ --output docs/week2/deployment_verification.json
```

上傳後會保留第一週版本與第二週版本。回復時同時設定 `artifacts/baseline`／`week1-frequency-v1`；不要只改其中一項。第二週 [API schema](week2/API.md)、[交付驗收](week2/COMPLETION.md) 與 [模型成果](week2/RESULTS.md) 分開記錄實際狀態。

順序：建立 GitHub 儲存庫 → 上傳程式 → 建立 Supabase 並匯入 → 部署 Render → 啟用 GitHub Pages → 驗證完整網站。

「專用儲存庫」就是為球路參謀另外開一個 GitHub repository，與原本其他專案分開。本機資料夾維持 `C:\Users\user\Desktop\炫晟\野革盃`。

## 1. 建立 GitHub 儲存庫

1. 開啟 <https://github.com/new>，確認登入帳號是 `happy123903`。
2. Owner 選 `happy123903`。
3. Repository name 填 `pitchadvisor-tw`。
4. Description 可填「球路參謀：以中職歷史資料提供配球分析與可信度資訊」。
5. 選 **Public**。本次採 GitHub Free 的 Pages 路徑，需要公開儲存庫。公開後，提交的程式碼與目前基準模型統計也會公開，並非只有網頁公開。
6. 保持 README 不新增、.gitignore 不新增、License 不選；本機已有檔案，先建立空儲存庫可避免首次推送衝突。
7. 點 **Create repository**。
8. 預期得到 `https://github.com/happy123903/pitchadvisor-tw`。

官方：[建立儲存庫](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)、[GitHub Pages 可用方案](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site)。

## 2. 上傳本機程式

在 IDE 終端機開啟 PowerShell，切到專案根目錄：

```powershell
Set-Location -LiteralPath 'C:\Users\user\Desktop\炫晟\野革盃'
```

目前本機已初始化 Git，分支為 `main`，尚無提交與遠端。若你是在日後的另一台電腦重新操作，先依當時狀態確認，不要盲目重複新增遠端。

先加入程式、部署設定與第一週模型。分開列出，避免連原始資料或原簡報一起上傳：

```powershell
rtk git add .gitignore .env.example .github README.md pyproject.toml uv.lock requirements.txt requirements-lock.txt render.yaml
rtk git add api src scripts tests supabase docs web artifacts/baseline
rtk git add '野革盃黑客松_專案計畫書_v3.md'
rtk git diff --cached --stat
```

檢查暫存清單沒有 `.env`、`.venv`、`.tools`、`.cache`、`web/node_modules`、`web/dist`、`data/raw` 或 `data/processed`。這些已有忽略規則；原簡報與 v2 本次不加入。`artifacts/baseline/model.json` 與 `manifest.json` 要加入，讓 CI 測試與首次部署有可驗證模型。

若尚未設定提交身分，先設定本儲存庫專用的名稱與 GitHub noreply 信箱：

```powershell
rtk git config user.name 'happy123903'
rtk git config user.email '91250441+happy123903@users.noreply.github.com'
```

再提交並推送：

```powershell
rtk git commit -m 'Add week-one PitchAdvisor baseline and deployment setup'
rtk git remote add origin https://github.com/happy123903/pitchadvisor-tw.git
rtk git push -u origin main
```

若推送跳出 GitHub 登入／瀏覽器授權，使用你的帳號完成。若出現 `origin already exists`，先確認是否已設定正確遠端，不要直接刪除它。若使用密碼登入被拒，改用 Git Credential Manager 的瀏覽器登入；GitHub 帳號密碼不作為 HTTPS Git 推送密碼。

重新整理儲存庫頁面，確認根目錄可見 `render.yaml`、`api/`、`web/`、`supabase/`、`artifacts/baseline/` 與 `.github/workflows/`。

第一次推送可能讓 `Build and deploy web` 工作因尚未設定 API 網址而失敗；最後完成 Render 與 Pages 設定後會重新執行，這時才是完整部署驗收。

## 3. 建立 Supabase 專案與資料表

1. 開啟 <https://supabase.com/dashboard>，註冊或登入，可使用 GitHub 登入。
2. 沒有 Organization 時先建立一個自己的組織，方案選 Free。
3. 點 **New project**。
4. Project name 填 `pitchadvisor-tw`。
5. 設定 Database password，使用強密碼並保存在密碼管理工具。此密碼與後續 API secret key 是不同東西，本專案的 HTTP 匯入腳本不需要填資料庫密碼。
6. Region 可選 Singapore（若畫面提供）；選定 Free 專案後建立，等待專案可用。
7. 進入左側 **SQL Editor**，新增一個查詢。
8. 在 IDE 開啟 `supabase/migrations/202611090001_week1.sql`，複製全部內容到 SQL Editor。
9. 確認目前操作的是新建的本專案，按 **Run**。
10. 到 Table Editor 檢查以下四張表存在；剛建立時沒有資料是正常的：

| 表格 | 用途 |
|---|---|
| `players` | 訓練版本球員名單 |
| `pitcher_repertoire` | 投手實際投過的球種 |
| `aggregate_stats` | 聚合統計與價值估計 |
| `model_versions` | 模型版本與資料截止日 |

再到 **Storage** 確認 `model-artifacts` bucket 已建立，且為 **Private**。SQL 已設定表的 RLS 與角色權限；不用為了讓網頁讀取而將全部表改成公開，網頁會呼叫 FastAPI。

若建立專案時關閉了 Data API，到 **Integrations → Data API** 開啟。此專案需要透過 REST 匯入與讀取 `public` 的既定資料表，遷移檔已明確授予後端角色所需權限；不必額外新增匿名公開讀寫政策。

官方：[建立 Supabase 專案與 SQL Editor](https://supabase.com/docs/guides/getting-started/quickstarts/flask)。

## 4. 取得 Supabase URL、secret key 並匯入

先取得兩個值：

| 值 | 取得位置／格式 |
|---|---|
| Project URL | 專案的 **Connect** 視窗；例如 `https://你的專案ref.supabase.co` |
| Secret key | **Settings → API Keys → Secret keys**，建立或複製 `sb_secret_...` |

`SUPABASE_URL` 只填專案網域，**不要包含 `/rest/v1/`**。Data API 頁面可能顯示完整 REST 網址，但匯入程式會自行加上 `/rest/v1/`；填入完整 REST 網址會造成路徑重複並回傳 404。Render 的同名環境變數也使用不含路徑的 Project URL。

此處使用伺服器端 secret key，不是 `sb_publishable_...`。如果介面顯示 legacy `service_role`，程式也相容，但新設定優先使用新型 secret key。不要貼到聊天、GitHub 原始碼或前端變數。[官方金鑰說明](https://supabase.com/docs/guides/getting-started/api-keys)

在本機專案根目錄複製 `.env.example` 為 `.env`；若 `.env` 已存在，編輯既有檔案即可。可在 PowerShell 執行：

```powershell
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
```

用 IDE 開啟 `.env`，填入自己的值：

```dotenv
SUPABASE_URL=https://你的專案ref.supabase.co
SUPABASE_SECRET_KEY=sb_secret_填入你自己的完整金鑰
MODEL_VERSION=week1-frequency-v1
MODEL_BUNDLE_DIR=artifacts/baseline
ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:4173,http://localhost:4173
```

`.env` 只留在本機，已列於 `.gitignore`。在專案根目錄先跑離線檢查：

```powershell
rtk proxy .venv\Scripts\python.exe scripts/supabase_sync.py
```

確認顯示 `mode: dry_run`，再真正匯入：

```powershell
rtk proxy .venv\Scripts\python.exe scripts/supabase_sync.py --apply
```

本版應處理的筆數如下；日後重訓可能改變：

| 表格 | 第一週筆數 |
|---|---:|
| `players` | 377 |
| `pitcher_repertoire` | 826 |
| `aggregate_stats` | 75,424 |
| `model_versions` | 1 |

結束時預期看見 `Cloud import complete`。到 Storage 開啟 `model-artifacts/week1-frequency-v1/`，應有 `model.json` 與 `manifest.json`。

資料採 upsert，可重跑；若中途失敗，先處理錯誤再執行同一命令，不用手動刪表。若需要由我接手，完成平台連接後即可使用已準備的腳本，不必把 secret key 貼在對話。

## 5. 讓 Render 連上 GitHub 並部署 FastAPI

1. 開啟 <https://dashboard.render.com/>，註冊或登入，可使用 GitHub 帳號。
2. 點 **New → Blueprint**。
3. 若尚未連 GitHub，按畫面提示授權；GitHub 的 repository access 可選 **Only select repositories**，只勾選 `pitchadvisor-tw`。
4. 回 Render，選 `happy123903/pitchadvisor-tw`，按 Connect。
5. Blueprint 名稱可填 `pitchadvisor-stack`，Branch 選 `main`，Blueprint Path 為 `render.yaml`。
6. 確認會建立一個 `pitchadvisor-api` Python Web Service，方案為 **Free**。本專案資料庫已使用 Supabase，不需另外建立 Render Postgres。
7. 依 Blueprint 提示輸入以下三個環境變數，值不必加引號：

| Render 環境變數 | 要填的內容 |
|---|---|
| `SUPABASE_URL` | 與本機 `.env` 相同的 Project URL |
| `SUPABASE_SECRET_KEY` | 與本機 `.env` 相同的 secret key |
| `ALLOWED_ORIGINS` | `https://happy123903.github.io` |

`ALLOWED_ORIGINS` 只含通訊協定與網域，**不加 `/pitchadvisor-tw/`，也不要加結尾斜線**。這是瀏覽器來源網域，與完整網頁路徑不同。

其餘設定已寫在 `render.yaml`：Python 3.12、安裝 requirements、啟動 FastAPI、單程序、`/health` 健康檢查與模型版本，不需要自己重新組裝啟動命令。

8. 檢查後點 **Deploy Blueprint**，等待部署完成。失敗時看 Events／Logs，保留錯誤訊息，分享時不要附上金鑰。
9. 記下 Render 實際提供的 HTTPS 網址，例如 `https://pitchadvisor-api-xxxx.onrender.com`。這只是示例，必須使用你畫面上的實際網址。
10. 開啟 `<Render實際網址>/health`。

預期回傳包含：

```json
{
  "status": "ready",
  "model_version": "week1-frequency-v1",
  "data_source": "supabase_verified_snapshot"
}
```

這是部分欄位示例，實際回應還有資料版本與能力旗標。`status=ready` 只證明模型可用；確認 Supabase 連接時，要同時檢查 `data_source`。若是 `local_snapshot` 或 `local_snapshot_supabase_unavailable`，表示仍使用本機快照，應確認 Supabase 匯入、URL 與 key，再重新部署。

再試 `<Render實際網址>/players` 與 `/docs`，應能看到球員名單與 API 文件。

官方：[連 Git provider](https://render.com/docs/git-provider)、[Blueprint 建立流程](https://render.com/docs/infrastructure-as-code)、[環境變數](https://render.com/docs/blueprint-spec)。

## 6. 啟用 GitHub Pages 並設定後端網址

1. 回到 GitHub 的 `pitchadvisor-tw` 儲存庫。
2. 進 **Settings → Secrets and variables → Actions**。
3. 選 **Variables** 分頁，按 **New repository variable**。
4. Name 填 `VITE_API_BASE_URL`。
5. Value 填 Render 的實際 HTTPS 根網址，例如 `https://pitchadvisor-api-xxxx.onrender.com`，不加 `/docs`、`/predict` 或 `/api`。
6. 按 **Add variable**。要放在 Variables，本版工作流程使用 `vars.VITE_API_BASE_URL`；只放在 Secrets 不會被目前設定讀到。
7. 進 **Settings → Pages**。
8. 在 **Build and deployment → Source** 選 **GitHub Actions**。
9. 專案已有工作流程，不需另外建立 Jekyll、Static HTML 或 `gh-pages` 分支。
10. 到上方 **Actions**，左側選 **Build and deploy web**，按 **Run workflow**，Branch 選 `main`，再按執行。
11. 等 `build`、`deploy` 均成功後，到 Settings → Pages 按 **Visit site**。

既有正式網址：`https://happy123903.github.io/pitchadvisor-tw/`。第二週目前版本與驗收證據以 `docs/week2/COMPLETION.md` 為準。

GitHub Pages 只取得公開的 API 網址。Supabase key 只留在本機 `.env` 與 Render 後端，不需填入前端或 GitHub Pages 設定。

官方：[建立 repository variable](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-variables)、[Pages 選用 GitHub Actions](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)。

## 7. 最後逐項確認

| 檢查 | 成功條件 |
|---|---|
| GitHub 程式 | 正確的 repository／main 上可見完整程式與模型包，沒有 `.env` |
| Supabase | 四張表有資料，私有 bucket 有兩個模型檔 |
| Render | 部署成功，`/health` 回報正確模型版本及 Supabase 驗證狀態 |
| Pages | build 與 deploy 成功，正式網址開啟正常 |
| 實際分析 | 修改投手／球數後可重新分析，機率、熱圖與樣本能顯示 |

免費 Render 閒置 15 分鐘後會休眠，重新啟動可能約需一分鐘；先開一次 `/health` 等待恢復，再測網站。這和 Vite 本機量測延遲不同。[官方限制](https://render.com/docs/free)

## 8. 常見問題

| 現象 | 先檢查 |
|---|---|
| Git push 顯示 repository not found | GitHub 上已建立儲存庫、網址與登入帳號是否正確 |
| Git commit 提示沒有 identity | 設定本儲存庫 `user.name` 與 `user.email`，再提交 |
| `rtk` 顯示 No hook installed | 這是自動節省 token 功能的提示；手動執行 `rtk proxy` 仍會執行命令，無須為了解決 Supabase 匯入而安裝 hook |
| Supabase 匯入 HTTP 404 | 先檢查 `.env` 的 `SUPABASE_URL` 只含專案網域，沒有 `/rest/v1/`；再確認正確專案的資料表與 Data API |
| Supabase 匯入 401 | URL 與 secret key 是否來自同一個專案，是否複製完整 |
| Supabase 匯入 403／permission denied | 遷移是否已在正確專案執行，是否使用伺服器 secret key |
| Supabase 找不到資料表 | 確認遷移、`public` schema 與 Data API 已啟用 |
| Render 看不到 GitHub repository | 重新檢查 Render 的 GitHub app 是否獲准存取此儲存庫 |
| Render 503／模型尚未就緒 | `artifacts/baseline` 是否已提交；若從 Storage 載入，確認私有檔、模型版本與 key |
| Render 建置成功，但 `/health` 一直 503；模型 checksum 不一致 | Windows 的 Git 換行轉換可能改變模型位元組。保留 `.gitattributes` 的模型 binary 設定，重新 `git add .gitattributes artifacts/baseline/model.json`、commit、push；不要略過 SHA-256 驗證 |
| Blueprint 顯示 Failed sync，但服務已 Live／ready | 比對 Blueprint 的 lastSync 與服務部署版本；舊的同步失敗可與後來成功的服務部署同時存在。確認 API、Supabase 整合與 CORS 後可繼續 Pages，不因舊紀錄重建服務 |
| Render ready，但資料來源為 local_snapshot | Supabase 尚未被成功驗證；檢查匯入與環境設定後重新部署 |
| Actions 停在 Require deployed API | 到 Variables 設 `VITE_API_BASE_URL`，再 Run workflow |
| API 單獨能開，網頁卻報跨來源錯誤 | Render 的 `ALLOWED_ORIGINS` 必須是 `https://happy123903.github.io`，更新後重新部署 |
| 網頁顯示「尚未設定雲端 API 網址」 | 設定變數後重新執行建置；前端變數不是在執行時動態讀取 |
| Pages 404 或畫面空白 | 確認部署來源、工作流程成功、網址有 `/pitchadvisor-tw/`，以及儲存庫名稱未改 |

## 9. 如果要授權 Codex 接手操作

上面的網址、金鑰與環境變數，是讓「網站後端」連接平台。若希望 Codex 也能讀取或操作你的專案，需另外連接對應服務。

1. 在支援 Plugins 的 ChatGPT／Codex 介面開啟 **Plugins**。
2. 搜尋 **Supabase**，開啟後安裝，依提示登入並完成 Connect／授權。
3. 搜尋 **Render**，同樣完成安裝及連接自己的帳號／工作區。
4. 若需要選擇可存取的組織或專案，選本次建立的專案。
5. 回到本專案對話，提供 GitHub 儲存庫網址、Supabase 專案 Dashboard 網址與 Render 服務網址即可；不要提供 secret key。

如果 IDE 沒有 Plugins 入口，可使用支援的 ChatGPT 桌面版或 Codex CLI；CLI 有 `/plugins` 瀏覽入口。安裝不等於已登入授權，須完成服務連接才可使用對應工具；若安裝後工具尚未載入，依介面提示重新開啟對話。

此處依 OpenAI Docs 的外掛說明整理；特定外掛能否顯示與存取哪些帳號，仍取決於你的介面、帳號與工作區權限。[外掛說明](https://learn.chatgpt.com/docs/plugins)
