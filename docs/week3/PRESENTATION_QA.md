# 第三週成果簡報驗收

日期：2026-11-11（Asia/Taipei）。成果為九頁可編輯 PowerPoint 與同內容 PDF，搭配 [五分鐘 Demo 腳本](DEMO_SCRIPT.md)。原始初審 v4 簡報保留，沒有覆寫。

## 實際輸出與檢查

- [成果簡報 v5 PPTX](../../deliverables/球路參謀_成果簡報_v5.pptx)：九頁，16:9，文字為可編輯物件，四張資料表為原生 PowerPoint 表格，九頁均有口述時程與來源備註。
- [成果簡報 v5 PDF](../../deliverables/球路參謀_成果簡報_v5.pdf)：由同份簡報以 PowerPoint 原生功能輸出，九頁。
- 以 Microsoft PowerPoint 16.0 重新開啟輸出檔，檢查全部文字物件與表格儲存格的實際文字高度、可用高度及畫布邊界：**0 項文字溢出、0 項越界**。
- 由 PowerPoint 輸出九張 1600 × 900 PNG，逐頁開啟檢視。標題、表格、日期及百分比可讀，沒有文字裁切、錯字型或物件重疊。第 5 頁使用第三週真實瀏覽器操作截圖。
- 使用簡報工具附帶的 `inspect_presentation_package_integrity.py --fail-on-findings`：九頁、**0 findings、pass**。
- PDF 確認檔頭、完整 EOF 與九個頁面物件。視覺檢查以同一 PowerPoint 產生的逐頁 PNG 為依據，沒有宣稱另外使用 PDF renderer 逐頁比對。

## 內容核對

第 6 頁驗證數字對應第二週 [RESULTS.md](../week2/RESULTS.md)。第 7 頁對應第三週 [FINAL_RESULTS.md](FINAL_RESULTS.md)，同時呈現全部 99,729 球與線上名單內 69,044 球，明列全體球種 log loss 比頻率基準差 2.27%、名單內改善 3.56%，以及全體集合覆蓋率 83.74%、未知投手分組 68.86%。沒有把較好的子集代表全部，也沒有把名目 90% 覆蓋視為保證。

第 8 頁冷啟動 51.5 秒來自 [隔夜休眠喚醒觀測](cold_start.json)，明確標為一次實測。三種模式區分雲端即時、本機完整推論及唯讀固定案例。資料來源及 ODC-By 歸屬放在第 3、9 頁與相關備註。

## 工具與驗證範圍

本機沒有 `@oai/artifact-tool` runtime，也沒有連接的 PowerPoint 文件工具 session。本次依可用環境採已安裝的 **原生 PowerPoint COM** 建立、重新開檔與輸出，未安裝替代簡報套件，沒有使用 python-pptx，也沒有聲稱通過不可用的 Artifact SDK finalizer。版面檢查採原生文字範圍、封裝檢查與實際圖片檢視。

五分鐘時程為現場講解排練稿。操作影片另以實際錄製長度和字幕記錄，不能將排練時程當成錄影檔長度或已錄音的證據。
