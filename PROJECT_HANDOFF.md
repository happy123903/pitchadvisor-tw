---
summary: 第二週模型與網頁已完成本機整合及Supabase讀回；序列LightGBM勝出，Render與Pages最後發布驗收進行中。
created: 2026-11-09
updated: 2026-11-10
tags: [project-handoff, pitchadvisor-tw, github-pages, supabase, render, week2]
---

# 球路參謀：模型交接

此檔記錄接手入口。以當下檔案與即時服務回應重新核對，不把歷史測試當成永久可用性保證。

## 目前任務與授權

- 使用者要求**完成第二週進度**，最新訊息「繼續」。三平台操作與專案部署先前已授權；不用重問帳號建立、下載資料或一般發布權限。
- 工作目錄 `C:\Users\user\Desktop\炫晟\野革盃`；所有專案工具、資料與環境放此處。保留 `野革盃黑客松_專案計畫書_v2.md` 與原始 PPTX，不任意覆寫或加入版本庫。
- 所有 shell 命令以 `rtk` 開頭，依 `C:\Users\user\.codex\RTK.md`。`No hook installed` 只是 RTK 提示，不是 API 錯誤，不為此改全域設定。
- `.env` 只限本機，忽略且不列印。曾提醒使用者換發對話中曝光的 secret；未代為輪替、未確認已輪替，不保存其值。

## 第二週完成的實作

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

**2025最終測試未載入／未評分**。不要為第三週簡報提前拿來選模。2023–2025原始總數1020場／293482球只是資料查核，與訓練／評估範圍不同。

完整證據：[第二週交付](docs/week2/COMPLETION.md)、[成果](docs/week2/RESULTS.md)、[方法](docs/week2/MODELING_METHOD.md)、[事前驗收](docs/week2/EXECUTION_PLAN.md)。

## 驗收與發布

- 本機 Python 63 passed；模型9項含真artifact／NumPy-PyTorch parity已實跑。Node5passed；正式TS＋Vite build通過。
- `docs/week2/local_verification.json`：真HTTP歷程／打者效果、三head、候選、sets及錯誤碼；25次暖機p95約4ms，真服務峰值約219MiB。已避免誤量約6MB venv launcher，驗收自有子程序會清理。
- `docs/week2/supabase_verification.json`：model和manifest完整位元組讀回一致；球員完整投影一致；players377／repertoire826／aggregate75424／model_versions2。Feature_version登錄為week2-v1。
- Render與Pages最終week2發布、瀏覽器桌面／手機驗收進行中；接手若見此狀態，先看下方證據檔是否已產出及最新Git/health，勿直接宣稱正式發布完成。
- 第一步歷史證據仍保留 `docs/week1/deployment_verification.json`（8a3c526、2026-11-10 18:18）；它不能代替第二週發布驗收。

## 已存在的平台

| 平台 | 本專案資源 |
|---|---|
| GitHub | `happy123903/pitchadvisor-tw`，main |
| Pages | https://happy123903.github.io/pitchadvisor-tw/ |
| Render | https://pitchadvisor-api.onrender.com |
| Render workspace | `tea-d6rflqq4d50c73bt1q0g`（My Workspace，已核對） |
| Render service | `srv-dbpe8a8m7kps73amakrg`，Free／Oregon／單worker |
| Blueprint | `exs-dbpe7dmtlv9c73fb9gq0`，autoSync，先前仍有舊Failed sync紀錄 |
| Supabase | `tffmdcuyzifepuaadglx`，pitchadvisor-tw |

Supabase沿用第一週四表／RLS／private `model-artifacts` bucket，沒有為第二週重建schema。模型包<20MiB。`SUPABASE_URL` 只能是project origin，不能加 `/rest/v1/`（先前404根因）。高權限key只用後端。

`render.yaml` 是非secret設定的來源；本機`.env`及範例已設第二週MODEL_VERSION／BUNDLE_DIR，Render亦須與其一致。若舊Blueprint未自動套用，使用Render更新兩個非secret鍵並保留其他鍵。不要因舊紅叉刪除Live服務或自動升級付費。

第一週503曾因Windows autocrlf改變JSON位元組；`.gitattributes` 已把baseline及week2的model.json標binary。保留SHA核對，不跳過檢查。

## 常用命令

```powershell
rtk proxy .venv\Scripts\python.exe -m pytest -q
rtk proxy npm.cmd --prefix web test
rtk proxy npm.cmd --prefix web run build
rtk proxy .venv\Scripts\python.exe scripts/verify_week2.py --output docs/week2/local_verification.json
rtk proxy .venv\Scripts\python.exe scripts/verify_supabase_model.py
rtk proxy .venv\Scripts\python.exe scripts/verify_week2.py --api-url https://pitchadvisor-api.onrender.com --frontend-url https://happy123903.github.io/pitchadvisor-tw/ --output docs/week2/deployment_verification.json
rtk proxy powershell -NoProfile -File scripts/Start-Local.ps1
rtk proxy powershell -NoProfile -File scripts/Stop-Local.ps1
```

啟停腳本有程序紀錄；先核對歸屬與port再操作，不盲殺程序。本機預設8000／5173。網路、CIM、Git寫入或Vite/esbuild可能受沙箱限制，依工具提升權限，不改壞應用來繞過環境錯誤。

重訓先 `uv sync --locked --group training`（uv cache/python install/bin需指專案`.cache/.tools`，完整見README），再 `scripts/build_week2.py --threads 4 --epochs 10 --rounds 140`。`--smoke`用隔離且被忽略的目錄，不可上傳。部署requirements只含推論runtime，不含torch/sklearn。CI未安裝Torch時訓練parity一項明示skip，本機已跑。

匯入先dryrun；`scripts/supabase_sync.py --bundle-dir artifacts/week2 --apply`才寫雲端。上傳表與private檔後最後登錄version，讀回用verify_supabase_model.py。不要反覆重建migration或重抓完整資料。

## 接續第三週

1. 先確認本輪week2發布／瀏覽器證據完成，再依當下使用者指令進行。
2. 凍結後執行2025最終測試，所有結果如實保留，不能再以測試成績反覆調參。
3. 冷啟動、連續切換、雲端錯誤、恢復／本機斷網備案與多人負載；暖機資料不能當冷啟動成功。
4. 固定示範案例與影片、成果簡報、五分鐘演練；本輪未改原PPTX。
5. 會員／收藏、TabPFN／Transformer為選配，未實作不影響本週核心交付；不得捏造研究勝出或因果效果。
