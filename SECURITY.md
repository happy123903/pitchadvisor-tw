# 安全提交與發布

本專案的公開內容限程式、設定範例、公開棒球資料的衍生統計與經檢查的交付成果。金鑰、個人聯絡資料、本機路徑、原始私人文件與平台內部資源識別碼不得提交。

首次使用新的 checkout，先安裝固定版本 Gitleaks 與本儲存庫的 hooks：

```powershell
rtk proxy python scripts/setup_security.py
rtk proxy python scripts/security_check.py --mode worktree
```

`pre-commit` 讀取 Git 暫存區的實際內容；`pre-push` 檢查將推送的提交與全部祖先，包括已刪除檔案和提交中繼資料。掃描器缺少、掃描失敗或發現問題時都會阻擋，輸出只含檔案位置及規則，不列出敏感值。即使 `git add -f` 加入忽略的私人檔案，仍會被檢查。

`.env.example` 只能放空值或明確範例，真正憑證放在忽略的 `.env` 或後端平台環境變數。`VITE_` 變數會進入瀏覽器，只可放公開設定。

ZIP／PPTX 會遞迴檢查內容及作者欄位；圖片、PDF、影片等無法可靠以文字掃描的檔案由 `.security-reviewed-media.json` 的 SHA-256 固定已檢視版本。新增或變更媒體時，須先檢查畫面、作者／EXIF／XMP、註解及附件，再人工更新該清單；不要單純換 hash 讓檢查通過。來源公開資料的球員姓名與上游公開聯絡資訊保留原始出處。

GitHub Actions 的安全工作流程是推送後的第二層檢查；它不能阻止內容首次抵達 GitHub。本機 hooks 與 GitHub repository 的 Secret scanning / Push protection 才是推送前防線。不要使用 `--no-verify` 繞過檢查；新 clone 也必須執行安裝腳本。各種掃描均無法保證辨識所有形式的個資或金鑰。

若歷史中已出現敏感資料，新增一筆刪除提交無法移除舊版本。先撤銷／換發任何已曝光的憑證，再在隔離副本清理歷史，經驗證及協作者確認後才以受保護的強制推送替換遠端分支。不要直接對原始工作目錄執行破壞性重寫。參閱 [GitHub 敏感資料清除指引](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)。

本次檢查範圍、結果與限制見 [資安檢查紀錄](docs/SECURITY_AUDIT.md)。
