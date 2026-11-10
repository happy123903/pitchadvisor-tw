# 第一週資料字典與處理規則

來源為主辦方官網所列 Rebas Open Data。實際來源文件保存在 `sources/schema/`，下載版本與 SHA-256 在 `sources/download_manifest.json`。

## 檔案與範圍

| 輸出 | 意義 |
|---|---|
| `data/processed/games.parquet` | 一列一場，1,020 場例行賽；`seasonId:seq` 為唯一識別 |
| `data/processed/pitches.parquet` | 一列一個 `type=PITCH` 事件，共 293,482 列 |
| `data/processed/identities.parquet` | 當場、該隊、該角色的原始球員 ID 與姓名對照 |
| `docs/week1/split_manifest.json` | 各比賽的訓練、驗證、校準與測試歸屬 |

ZIP 中的 `*-G數字.json` 為單場檔，`*-OpenData.json` 合併檔不再讀取。2023 年 300 場、2024 年 360 場、2025 年 360 場。未含季後挑戰賽、台灣大賽與 2026 年賽事。

## 逐球主要欄位

| 欄位 | 型態／來源 | 時點或處理 |
|---|---|---|
| `game_id`, `date`, `year`, `stadium` | game | 比賽來源識別；日期使用來源欄位 |
| `side`, `inning`, `pa_index`, `event_index` | PA／events | 客／主場進攻、局數、原始索引；共同辨識單球 |
| `pitcher_id`, `batter_id` | 當場 PitcherBox／BatterBox | 由球員名稱對應該隊該角色的唯一 ID，不按全資料姓名合併 |
| `pitcher_name`, `batter_name` | event，缺少時 PA | 保留來源顯示名稱，不作永久主鍵 |
| `pitcher_hand`, `batter_hand` | PA | 事件球員與 PA 不一致時標未知，避免套用錯誤左右手 |
| `balls`, `strikes` | 依 pitchCode 逐事件累計 | **本球之前**球數；最後一球與 PA 末球前欄位核對 |
| `outs`, `bases` | 前 PA 結束狀態＋事件／末球前 PA 錨點 | 本球之前；`bases` 位元一壘 +1、二壘 +2、三壘 +4 |
| `count_valid`, `bases_known`, `state_valid` | 處理旗標 | 球數重建符合、壘包已知、整體情境可用；未知不是空壘 |
| `identity_valid` | ID 對照檢查 | 投打均能由當場成績表唯一辨識 |
| `pitch_type`, `pitch_code` | event.pitchType／pitchCode | **當球目標／結果**；不作預測當球的輸入 |
| `result` | pitchCode 與末球 PA 結果 | 壞球、無揮棒好球、揮空、界外、進場、觸身球或其他 |
| `velocity` | event.velocity | 可解析且 40–180 的值，其餘未知；保留缺值率 |
| `coord_x`, `coord_y` | event.coordX／coordY | 可解析的原始數值；缺值不補零 |
| `zone` | 座標轉換 | 0–12；未知座標或超過範圍上限則無分區 |
| `before_score`, `runs` | PA／runner | 攻方本球之前累計得分、本事件得分；末球使用 PA 前後比分核對 |
| `next_balls`, `next_strikes`, `next_outs`, `next_bases` | 事件／PA end 欄位 | 結束打席後球數歸零；壘包不可還原時標未知 |
| `transition_known` | 前後狀態查核 | 只對可靠轉換估計候選的失分變化 |
| `runs_to_end`, `complete_half` | 同半局後續累計得分 | 完整三出局半局才建立剩餘得分標籤；此欄是訓練目標，不是當球特徵 |
| `is_final_pitch`, `history_length`, `pa_result` | PA／events | 歷程與核對資訊；PA 最終結果不能直接用於預測當球 |
| `split` | 固定日期分界 | train／validation／calibration／test |

原始實例的打席結果欄位為 `result`（單數）；解析器另相容 schema／資料版本可能使用的 `results`。PA 的 `balls`、`strikes`、`outs`、`bases` 為「結束打席前」欄位，不能直接複製到整個打席的每球。

## 球數與特殊事件

- `B` 增加壞球；`S`、`SW`、`FT`、`TRY_BUNT`、`FOUL_BUNT` 增加好球。
- 一般 `F` 在兩好球後維持兩好球；觸擊界外可能形成第三好球。
- `H`、`BUNT` 為球進場的打席終止事件；觸身球依末球 PA 結果另標。
- `BASE`、`NO_PITCH`、`SUB` 不新增逐球列，但其得分／出局可能改變後續情境。
- 末球球數與來源不符時，該打席受影響逐球資料保留在 Parquet，`count_valid=False`，排除情境基準。
- runner 沒有起終點壘位。中途跑壘後無法唯一推算的壘包，保守標未知，至可靠錨點再恢復。
- 延長局開始不假定空壘；沒有三出局結束的半局（例如再見比賽）不當完整半局價值標籤。

## 13 分區

投手視角，右為 X 正、上為 Y 正；官方描述單位約 0.5 公分，並以好球帶寬 100%、高 120% 描述座標。此版本採 X `[-50,50]`、Y `[-60,60]` 為帶內邊界，分為三等欄、三等列。

| ID | 區域 | ID | 區域 | ID | 區域 |
|---:|---|---:|---|---:|---|
| 0 | 左上 | 1 | 中上 | 2 | 右上 |
| 3 | 左中 | 4 | 正中 | 5 | 右中 |
| 6 | 左下 | 7 | 中下 | 8 | 右下 |
| 9 | 帶外上方 | 10 | 帶外右側 | 11 | 帶外下方 |
| 12 | 帶外左側 | | | | |

帶外比較 `abs(x/50)` 與 `abs(y/60)`，偏離較大軸決定區域；相同時歸垂直區域。四區互斥且含角落，熱圖由上向下顯示，無須額外左右鏡射。`abs(x)>500` 或 `abs(y)>600` 是本專案的離群值篩選規則，不是官方好球帶定義。

## 不洩漏與版本

球員顯示名稱、左右手、球種清單、樣本統計、價值函數與候選均只取訓練期。2025 年只做描述性資料品質盤點，沒有參與模型估計、超參數選擇或模型成效排名。驗證與校準日期在看模型成績前依日期切分，同日完整比賽不跨集合。

模型包同時包含 `model_version`、`data_version`、`data_cutoff`，manifest 另保存 SHA-256。API 啟動前檢查一致性，失敗時回報 503。球員改名保留同 ID 的別名紀錄，同名不同 ID 不合併。
