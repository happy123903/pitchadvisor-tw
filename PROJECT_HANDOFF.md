---
summary: 第三週最終測試、線上與離線驗收完成；2025全體成績退步如實保留，影片、簡報、離線包與完整交付已完成。
created: 2026-11-09
updated: 2026-11-11
tags: [project-handoff, pitchadvisor-tw, github-pages, supabase, render, week3]
---

# 球路參謀：模型交接

此檔記錄接手入口。以當下檔案與即時服務回應重新核對，不把歷史測試當成永久可用性保證。

## 第三週目前結果（接手優先讀）

- 第三週核心功能版本 `501dddc` 已發布，CI42948712495、Pages42948712357 success，Render dep-dbptfqgae00c73fh7at0 Live；相同Supabase模型與名單讀回驗證成功。後續文件／交付封存commit以實際git log為準。
- `docs/week3/FINAL_RESULTS.md`、final_evaluation.json／public.json及freeze_before_final_test.json：2025共360場102488原始球、99729共同可用、69044 API名單內。全體模型球種LL1.400057 >基準1.368926（差2.27%）；名單內1.225868 <1.271066（改善3.56%）。全體球種覆蓋83.74%，未知投手68.86%。不可宣稱全面勝出或90%保證。
- 模型／encoder／校準器保持原SHA；`/evaluation`只公開與當前bundle SHA完全對應的摘要。公開metadata.model_info.test_evaluated=true（health則為頂層test_evaluated），原模型檔false仍作第二週產物歷史證據，沒有為改旗標破壞SHA。
- 冷啟動由隔夜shutdown紀錄確認，首次25秒timeout，重試後51.514秒ready且Supabase verified，沒有重啟。`docs/week3/cold_start.json`。
- `docs/week3/deployment_verification.json`：正式新功能全部通過；25warmHTTPp95250.96ms／內部8.06ms；4客戶端20請求全200，HTTPp95318.01ms。Render記憶體取樣149.55MiB，非瞬間峰值。`cloud_release.json`保存平台證據。
- 本機Python75passed／Node10passed，真Chrome桌面／手機viewport、503、65秒timeout、取消舊回應、後端阻擋後固定案例均通過。BROWSER_QA.md與screenshots保存細節，未宣稱實體手機或關網卡。
- `serve_offline.py`同一loopback程序供應編譯網頁與/api，停用dotenv/Supabase，使用真凍結模型。Start／Stop-Offline用絕對腳本路徑＋唯一token＋建立時間核對launcher/child；不要用過期PID盲殺程序。verify_offline.py的PowerShell控制輸出使用regular log檔，避免背景子程序保留PIPE而卡住EOF。
- 離線ZIP不含Python、runtime、venv、torch、node_modules或.env；需先準備Python3.12環境。測試已從解壓包自己的root用既有venv啟動並作任意推論，不依賴原repo import fallback。OFFLINE_GUIDE.md與offline_verification.json保存證據。
- 新成果 `deliverables/球路參謀_成果簡報_v5.pptx`＋PDF為9頁，原生PowerPoint COM生成並逐頁檢視；Artifact SDK在此環境缺少，未假稱SDK finalizer跑過。5分鐘腳本在DEMO_SCRIPT.md。4分40秒MP4與21段SRT已完成，字幕燒錄且無音軌，VIDEO_GUIDE.md／video_verification.json保存來源與檢查。全7場景為本機真API操作；503有模擬標示，未假稱雲端事故或關閉實體網卡。見第三週COMPLETION.md。
- 原始瀏覽器錄影位於忽略的output/playwright，僅提交完成的MP4與SRT；錄影是本機真API，不是雲端影片，503場景有明確模擬標示。

## 目前任務與授權

- 使用者要求**完成第三週內容**。三平台操作與專案部署先前已授權；不用重問帳號建立、下載資料或一般發布權限。
- 工作目錄 `C:\Users\user\Desktop\炫晟\野革盃`；所有專案工具、資料與環境放此處。保留 `野革盃黑客松_專案計畫書_v2.md` 與原始 PPTX，不任意覆寫或加入版本庫。
- 所有 shell 命令以 `rtk` 開頭，依 `C:\Users\user\.codex\RTK.md`。`No hook installed` 只是 RTK 提示，不是 API 錯誤，不為此改全域設定。
- `.env` 只限本機，忽略且不列印。曾提醒使用者換發對話中曝光的 secret；未代為輪替、未確認已輪替，不保存其值。

## 第二週既有實作（歷史基礎）

1. `src/sequence.py` 與 `web/src/sequence.ts`：完整當前打席、0–0 起、最多16球、重建球數；缺少 zone／velocity 可為 null；打席終結或球數矛盾拒絕分析。
2. `src/week2_features.py`：固定訓練期 encoder；以 game_id＋side＋pa_index 分組，避免主客打席索引混接；只用待預測球之前的歷程。速度按訓練期投手×球種平均／標準差，n<20 回退球種／聯盟；換投歷程遮罩。
3. `src/week2_training.py`、`scripts/build_week2.py`：兩類 LightGBM、GRU 與三個 GRU 消融、座標抖動比較。預算 seed20261110、4CPU threads、10epochs、140rounds，早停看驗證集。
4. `src/week2_model.py`：LightGBM native／NumPy GRU 推論；候選條件結果 head 可看候選球種／區域，主 head 不看當球真值；候選符合投手球種庫與支持門檻，條件機率乘訓練期 ΔRE 排序。
5. `api/main.py`：week1／week2格式相容，SHA與版本檢查，安全白名單 `/model-info`，Supabase登錄＋SHA＋完整球員投影查核，非法／終結歷程422，未知球員404。
6. `web/src/main.tsx`、`week2.css`：新增／編輯／刪除／清空歷程，球數自動重建，機率／熱圖／推薦／預測集合／audit／模型比較，取消舊請求避免過期結果覆蓋。

## 凍結的選模結果

| 項目 | 值 |
|---|---|
| 模型版本／格式 | `week2-sequence-v1`／`week2-v1` |
| 採用 | `lightgbm_history`，四項 capabilities 皆 true |
| 資料版本／截止 | `rebas-2023-2025-regular-v1`／2024-08-14 |
| 產物 | `artifacts/week2/model.json`＋manifest，10,422,629 bytes |
| SHA-256 | `aa3e984758796843bce68aa71fb06a4c84739a7d8048be475cc1bfe6855671ec` |
| 球種驗證 log loss | 頻率1.244698、context LGB1.201012、history LGB1.158778、GRU1.174469 |
| Audit coverage | 球種89.83%、分區90.26%、結果89.46%，名目90% |

事前規則：驗證球種 log loss 為主，0.005nats 內偏好簡單模型；GRU 分區／結果不得比history LGB差超過0.03nats。此輪不再變動架構追逐校準audit表現。

校準按完整日期分溫度9/12–9/21（5516球）、conformal9/22–10/1（5099）、audit10/5–10/11（3196）；三段互斥。分區缺值只遮罩該任務。五類結果排除特殊事件，實際樣本數在metrics。

**2025最終測試已在第三週凍結後完成**；未拿來重訓、選模或重新校準。全部可用樣本球種log loss較基準差2.27%，必須保留此結論，不只引用較好的名單內子集。2023–2025原始總數1020場／293482球只是資料查核，與訓練／評估範圍不同。

完整證據：[第二週交付](docs/week2/COMPLETION.md)、[成果](docs/week2/RESULTS.md)、[方法](docs/week2/MODELING_METHOD.md)、[事前驗收](docs/week2/EXECUTION_PLAN.md)。

## 驗收與發布

- 本機 Python 63 passed；模型9項含真artifact／NumPy-PyTorch parity已實跑。Node5passed；正式TS＋Vite build通過。
- `docs/week2/local_verification.json`：真HTTP歷程／打者效果、三head、候選、sets及錯誤碼；25次暖機p95約4ms，真服務峰值約219MiB。已避免誤量約6MB venv launcher，驗收自有子程序會清理。
- `docs/week2/supabase_verification.json`：model和manifest完整位元組讀回一致；球員完整投影一致；players377／repertoire826／aggregate75424／model_versions2。Feature_version登錄為week2-v1。
- 第二週三平台已發布及驗收。正式API為week2-sequence-v1、supabase_verified_snapshot；Pages新介面與CORS／序列／打者效果查核通過。雲端25次暖機HTTP p95 186.63ms、內部17.31ms；新Render實例記憶體兩筆樣本最大119.59MiB（不是壓力峰值）。證據docs/week2/deployment_verification.json與cloud_release.json。
- GitHub功能版本dec516c；CI42841424609、Pages42841424607 success；Render dep-dbpj7aqfenjc739t653g Live。Blueprint舊紅叉已在本次同步後變in_sync，未重建服務或改付費方案。
- 桌面1440、手機viewport390真Chrome驗收通過，詳細docs/week2/BROWSER_QA.md與10張截圖。測試自有瀏覽器與8000/5173程序已關閉。
- 第一步歷史證據仍保留 `docs/week1/deployment_verification.json`（8a3c526、2026-11-10 18:18）；它不能代替第二週發布驗收。

## 已存在的平台

| 平台 | 本專案資源 |
|---|---|
| GitHub | `happy123903/pitchadvisor-tw`，main |
| Pages | https://happy123903.github.io/pitchadvisor-tw/ |
| Render | https://pitchadvisor-api.onrender.com |
| Render workspace | `tea-d6rflqq4d50c73bt1q0g`（My Workspace，已核對） |
| Render service | `srv-dbpe8a8m7kps73amakrg`，Free／Oregon／單worker |
| Blueprint | `exs-dbpe7dmtlv9c73fb9gq0`，autoSync，本輪已in_sync，舊Failed sync為歷史紀錄 |
| Supabase | `tffmdcuyzifepuaadglx`，pitchadvisor-tw |

Supabase沿用第一週四表／RLS／private `model-artifacts` bucket，沒有為第二週重建schema。模型包<20MiB。`SUPABASE_URL` 只能是project origin，不能加 `/rest/v1/`（先前404根因）。高權限key只用後端。

`render.yaml` 是非secret設定的來源；本機`.env`及範例已設第二週MODEL_VERSION／MODEL_BUNDLE_DIR，Render亦須與其一致。本輪Blueprint已自動套用兩鍵並完成Live，無需重做；未透過MCP覆寫secret。不要因舊紅叉刪除Live服務或自動升級付費。

第一週503曾因Windows autocrlf改變JSON位元組；`.gitattributes` 已把baseline及week2的model.json標binary。保留SHA核對，不跳過檢查。

## 常用命令

```powershell
rtk proxy .venv\Scripts\python.exe -m pytest -q
rtk proxy npm.cmd --prefix web test
rtk proxy npm.cmd --prefix web run build
rtk proxy .venv\Scripts\python.exe scripts/verify_week2.py --output .cache/local-recheck.json
rtk proxy .venv\Scripts\python.exe scripts/verify_supabase_model.py --output .cache/supabase-recheck.json
rtk proxy .venv\Scripts\python.exe scripts/verify_week3.py --output .cache/week3-cloud-recheck.json
rtk proxy powershell -NoProfile -File scripts/Start-Local.ps1
rtk proxy powershell -NoProfile -File scripts/Stop-Local.ps1
```

啟停腳本有程序紀錄；先核對歸屬與port再操作，不盲殺程序。本機預設8000／5173。網路、CIM、Git寫入或Vite/esbuild可能受沙箱限制，依工具提升權限，不改壞應用來繞過環境錯誤。

重訓先 `uv sync --locked --group training`（uv cache/python install/bin需指專案`.cache/.tools`，完整見README），再 `scripts/build_week2.py --threads 4 --epochs 10 --rounds 140`。`--smoke`用隔離且被忽略的目錄，不可上傳。部署requirements只含推論runtime，不含torch/sklearn。CI未安裝Torch時訓練parity一項明示skip，本機已跑。

匯入先dryrun；`scripts/supabase_sync.py --bundle-dir artifacts/week2 --apply`才寫雲端。上傳表與private檔後最後登錄version，讀回用verify_supabase_model.py。不要反覆重建migration或重抓完整資料。

## 後續維護

1. 先讀第三週交付與最新Git／health，不必重做模型訓練、平台建立或資料下載。
2. 2025已被看過，不能再當新模型的未見最終測試；若要改善未知球員與漂移，另設前瞻資料與預先固定規則。
3. 本輪4客戶端20請求只是Demo負載，不等於生產容量；51.514秒是一次冷啟動，不是未來上限。
4. 會員／收藏、即時資料及更大模型仍是選配，沒有因本輪交付而假稱完成。
5. 本輪原v2及原v4 PPTX未修改、未納入Git；新增v5成果版與PDF。
