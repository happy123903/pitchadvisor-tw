# 第三週交付與驗收

更新：2026-11-11（Asia/Taipei），對應 v3 第15–21天。第三週程式、最終評估、線上與離線驗收、簡報、腳本及字幕影片皆已完成。

## 第三週進度

| 日程 | 交付與驗收 |
|---|---|
| 15–16 | 三任務圖表、歷程、推薦、預測集合與最終報告整合；65秒連線時限、20秒喚醒提示、重試、舊請求取消；服務失敗時移除舊圖表；安全request ID與模型／耗時診斷 |
| 17–18 | 凍結後執行2025最終測試；正式CORS、版本／SHA、錯誤輸入、校準與四位使用者有限負載通過；實際隔夜冷啟動與錯誤／恢復記錄 |
| 19 | 同一凍結模型的本機完整推論、三組唯讀固定案例與離線ZIP；真實本機程序、靜態資源、任意新情境、啟停清理及包內SHA驗證通過；4分40秒實際操作MP4與繁中SRT完成 |
| 20 | 九頁可編輯成果PPTX＋PDF、五分鐘Demo腳本、來源標註、操作／恢復文件；保留原v4簡報與v2計畫書 |
| 21 | 模型／校準器維持凍結、檔案與憑證檢查、三平台核心發布通過；最終完整交付封存完成 |

## 最終模型成績

模型仍是 `week2-sequence-v1`／`lightgbm_history`，SHA-256 `aa3e984758796843bce68aa71fb06a4c84739a7d8048be475cc1bfe6855671ec`。先寫凍結紀錄，才讀取2025；未重訓、重新選模或重估溫度／集合門檻。完整 [FINAL_RESULTS.md](FINAL_RESULTS.md)、[凍結證據](freeze_before_final_test.json)、[評估原始JSON](final_evaluation.json)。

| 範圍 | n | 模型球種log loss | 投手頻率基準 | 模型相對變化 | 模型球種集合覆蓋 |
|---|---:|---:|---:|---:|---:|
| 2025全部共同可用 | 99,729 | 1.400057 | 1.368926 | 差2.27% | 83.74% |
| API凍結名單內 | 69,044 | 1.225868 | 1.271066 | 改善3.56% | 89.31% |

log loss越低越好。名單外30,685球沒有藏起來；未知投手26,931球的球種集合覆蓋僅68.86%。名目90%不是實測或未來保證。分區集合平均約10.30區，推薦的條件結果亦不能解讀為換球的因果收益。

API `/evaluation` 只在報告的模型版本、SHA與截止日完全匹配時公開摘要；缺少或不符回503。凍結模型原檔中的 `test_evaluated=false` 保留為第二週的歷史產物，服務的公開metadata則由本次已核對的最終報告顯示true。

## 系統量測

- Python **75 passed**、前端Node **10 passed**；TypeScript＋Vite建置通過。CPU PyTorch的訓練／匯出一致性測試本機已實跑，乾淨CI未安裝training群組時會明示略過該項，不把略過當作執行。
- [隔夜冷啟動](cold_start.json)：先由Render紀錄確認昨晚程序已停止；首個25秒請求逾時，有限重試後 **51.514秒** ready且Supabase核對成功。未重啟／重新部署來製造冷啟動通過；僅一次觀察，不是時間上限。
- [正式HTTP](deployment_verification.json)：25次暖機HTTP p95 **250.96ms**、API內部p95 **8.06ms**；4個客戶端共20次請求全成功，HTTP p95 **318.01ms**、內部p95 **97.97ms**。這是小型Demo負載，不是生產容量壓力測試。
- [Render證據](cloud_release.json)：新實例30秒取樣記憶體最大 **156,815,360 bytes（149.55MiB）**，低於400MiB；不冒稱為瞬間峰值。發布後未見新增error級紀錄。
- [Supabase讀回](supabase_verification.json)：model及manifest位元組與球員投影一致，沿用377球員、826球種庫列、75,424聚合列與兩版模型；沒有為最終評分重建schema或更換模型。
- [本機完整模式](offline_verification.json)：靜態資源重載、377名單、固定案例、SHA、校準與任意合法即時預測通過。實際服務程序約208.53MiB，未誤量約6MiB的venv launcher；停止後兩個Python程序、port與紀錄都清除。

## 瀏覽器與影片

- [瀏覽器驗收](BROWSER_QA.md)與[browser_verification.json](browser_verification.json)：真Chrome桌面／手機viewport、實際65秒逾時與20秒提示、503清舊圖、重試、延遲回應競態、API受阻後唯讀固定案例、本機編譯版阻擋外網後重載與任意即時推論皆通過。手機為viewport模擬，外網為瀏覽器攔截，不冒稱實體手機／關網卡；測試程序已停止。
- `deliverables/球路參謀_示範影片_v1.mp4`：**4:40、1440×1120、25fps、H.264／yuv420p、faststart、無音軌**，21段繁中字幕已燒錄，另附SRT。原片7:39.36只剪除等待，保留原速實際互動；503場景明確標示模擬，影片使用本機真API。
- [影片說明](VIDEO_GUIDE.md)與[完整解碼／視覺檢查](video_verification.json)。MP4共19,269,849 bytes，SHA-256 `fa333585925a5adecd34f2ea0c17a5253830f2973800e2c71a0975ee9dd45ffb`。
- 離線ZIP最終4,133,834 bytes，SHA-256 `914f7572eaec181acd730dce69b3268c26c8362b436e4e5e4b4c05572e464de3`；已從包內自己的root用預備環境啟動驗證，非借用原repo來源碼。

## 成果入口

- [正式網站](https://happy123903.github.io/pitchadvisor-tw/)、[API健康](https://pitchadvisor-api.onrender.com/health)、[API最終摘要](https://pitchadvisor-api.onrender.com/evaluation)。
- [離線操作指南](OFFLINE_GUIDE.md)、[故障與恢復](RUNBOOK.md)。ZIP為 `deliverables/PitchAdvisor_Offline.zip`，每個檔案有SHA清單；新電腦仍需先準備Python3.12及runtime套件，不含Python／venv／PyTorch或憑證。
- `deliverables/球路參謀_成果簡報_v5.pptx`、同名PDF：[簡報QA](PRESENTATION_QA.md)。以已安裝的原生PowerPoint產生可編輯文字／表格，九頁均匯出檢視，未宣稱使用缺少的Artifact SDK。
- [五分鐘Demo腳本](DEMO_SCRIPT.md)：明確區分自由輸入的即時模式與唯讀固定案例，涵蓋資料、序列、真實模型比較與限制。

## 範圍與限制

本輪完成產品與展示交付，不等於取得未來準確率、推薦因果收益或服務SLA。會員、收藏、即時賽事串流與更大模型屬未來工作。若未來改善未知球員或漂移，需要另設新的前瞻評估資料，不再把已看過的2025當作未見最終測試。
