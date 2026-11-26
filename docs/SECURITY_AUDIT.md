# 專案資安與隱私檢查

日期：2026-11-26（Asia/Taipei）。本紀錄不保存金鑰、個人路徑、雲端內部識別碼或私人作者名稱。

## 檢查範圍與結果

- 初始 Git：166 個追蹤檔、7 筆 main 提交；本機全部 ref 涵蓋210個blob，main祖先為203個blob。已 fetch 遠端分支後檢查。Gitleaks 8.30.1 與本機環境憑證的精確比對均未發現 API Key；提交信箱使用 GitHub noreply。
- 隱私問題：4 份文件包含使用者目錄；部署／交接文件包含不需公開的內部資源識別碼；成果 PPTX 及 PDF 有本機作者中繼資料。原始v2計畫書與v4提案簡報只存在本機工具快照ref及本機檔案，不在main／origin/main提交歷史；不可把本機全ref掃描命中誤稱為GitHub外洩。
- 目前版本已泛化路徑、遮蔽內部資源識別碼、清除私人操作敘述與簡報／PDF 作者。PPTX 除核心中繼資料外所有封裝項目位元組相同；PDF 9 頁修改前後的渲染像素完全一致。
- 檢查 31 張追蹤 PNG 與 9 頁 PDF；影片全檔解碼成功並每 10 秒抽查，共 28 張影格。未對影片每一影格進行 OCR；媒體 SHA 清單不能取代新增內容的人工檢查。
- npm audit：119 個套件、0 已知漏洞。pip-audit：35 個部署套件、以及包含開發／訓練的 53 個唯一鎖定套件版本，均為 0 已知漏洞；同一 torch 版本的 CPU build 以相同基礎版本查詢公告。
- GitHub API 讀回：Secret scanning 與 Push protection 原已啟用，開啟中的 secret alert 為 0。未將任何原始碼變更推送至 GitHub。
- Supabase：遷移檔包含四張表的 RLS、撤銷匿名／登入角色直接存取，以及 private Storage。今日專案狀態為 `INACTIVE`，即時 SQL 不可用；advisor 空清單不作為今日權限驗證通過的證據。未恢復或修改雲端資料庫。

## 本次補強

- 擴充 `.gitignore`，涵蓋本機關聯圖、輸出、私人原始文件、憑證與資料庫備份。
- 加入 Gitleaks、隱私檢查、暫存區檢查、完整祖先歷史檢查及 GitHub Actions。掃描輸出不含敏感值，ZIP／PPTX 內的 `.env` 和金鑰亦會阻擋。
- API 在 JSON 解析前限制請求本文為 16 KiB，包含無 Content-Length 的分塊請求；422 回應不再回傳原始輸入及任意欄位名稱。
- 帶伺服器金鑰的 Supabase 請求要求乾淨的 HTTPS origin；停用 Uvicorn 預設 access log，保留既有不記錄 query/body 的診斷紀錄。
- 更新離線包並重新執行真實本機 HTTP／封裝執行及程序清理驗證，結果通過；模型內容與凍結 SHA 保持一致。
- Python 87 項測試通過；前端 10 項測試、TypeScript 與 Vite 正式建置通過。初次測試遇到系統暫存目錄權限問題，改用隔離的專案暫存路徑後通過。

## 尚未完成的遠端處置與限制

1. 原分支及 GitHub 的歷史仍包含上述已確認公開的私人資訊；工作目錄清理不會改寫舊提交。隔離副本已保留並清理原有七筆提交，另加入本次補強提交，八筆提交共238個歷史項目檢查為0發現；確認原始v2計畫書與v4提案簡報不在副本的任何提交中。尚未替換原分支或強制推送。實際pre-push已驗證：原main的210個項目有39個去重後位置／規則命中而被拒絕；清理後副本的238個項目0命中並放行。此過程未聯絡遠端，也沒有推送。
2. 舊維護紀錄提及一次憑證曝光，沒有可驗證的換發完成證據。Git 掃描沒有找到金鑰，不能據此斷定當時的憑證已撤銷；仍需私下在供應商端確認並換發。[GitHub 官方處置指引](https://docs.github.com/en/code-security/tutorials/remediate-leaked-secrets/remediating-a-leaked-secret)也要求先處理憑證本身。
3. 公開推論 API 仍是無登入的展示服務，只有並行數與請求大小限制，沒有使用者配額或分散式速率限制。正式擴大使用前應補上流量控管；CORS 不等於存取授權。
4. 本次為程式、設定、依賴、檔案與 Git 歷史審查，並非全面滲透測試。未驗證暫停中的雲端資料庫、所有 GitHub 外部副本／快取／Actions 歷史日誌或任意編碼／影像隱藏資訊。

## Supabase 重啟後複驗

2026-11-26：專案 ACTIVE_HEALTHY；四表 RLS 開啟，匿名與 authenticated 無直接資料權限；model-artifacts bucket 為 private。實際讀回模型與 manifest 位元組、SHA、登錄及完整球員名單均一致。advisor 僅四筆 INFO（RLS 無公開 policy），符合後端專用設計。使用者已授權清理歷史並推送。此段更新先前暫停時的檢查限制。
