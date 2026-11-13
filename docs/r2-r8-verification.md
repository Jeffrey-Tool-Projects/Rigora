# R2–R8 驗收紀錄（第二批）

日期：2026-11-12。工作樹在 `88b3ebfde3c6a3ecf3c8c424cd2253426d00f4c9` 之上，含 R0–R8
所有尚未提交的變更。本批次未提交、未推送、未公開發布。R2.1–R2.2 與 R7.1–R7.2 見
[第一批紀錄](r2-r7-verification.md)。

證據檔放在 `.audit/`（由 `.gitignore` 排除，分享報告時須一併提供）。

## 環境

| 項目 | 內容 |
| --- | --- |
| OS | Windows 11，`10.0.26300` |
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU，OpenGL 4.6.0，driver 621.14 |
| Python／套件 | Python 3.14.4、PySide6 6.11.2、numpy 2.5.2、Pillow 12.3.0（開發環境）；Nuitka 建置環境為 Python 3.12.13、PySide6 6.12.0 |
| 裝置 | 本機有一支實體攝影機與數個麥克風；**驗證全程未開啟**，以 driver 邊界的替身代替。未安裝 OBS Virtual Camera、Unity Capture、NDI runtime 或 ndi-python |

## 測試與檢查

| 驗證 | 結果 | 證據 |
| --- | --- | --- |
| 完整 offscreen 測試 | 2,003 passed、478 skipped，退出碼 0（之後新增的 GUI／CLI 等價測試另列於下一列） | `.audit/final/final-suite.log` |
| 原生 GL 測試（不顯示視窗的 37 個檔案） | 417 passed、1 failed：`test_rigora_app.py` 以 100 秒逾時執行整個 `verify_gui.py`，本批次串接的流程使其超時；加入 `--skip-workflows` 後重跑 1 passed（`native-app-test.log`） | `.audit/final/native-tests.log` |
| R6 合約（含 GUI／CLI 文件位元組相同） | 43 passed | `.audit/final/r6-contracts.log` |
| Ruff／Bandit | 通過；0 issues | `.audit/final/ruff.log`、`bandit.log` |
| 隱藏原生編輯器串接驗收 | `status: passed`；串接 editor session、素材、綁定、動畫、即時輸入、桌寵控制頁與桌面角色流程；前景視窗與游標前後相同，視窗原生隱藏，關閉後無存活計時器 | `.audit/final/native-gui/report.json` |
| 範例（含 GPU 匯出） | 五類全部通過，GPU 匯出 48 幀 | `.audit/final/examples.json` |

另有 4 個測試檔（`test_desktop_pet_window.py`、`test_puppet_canvas_render.py`、
`test_puppet_physics.py`、`test_puppet_webcam_preview_dialog.py`）會在原生平台顯示視窗，
依全背景規則不在本機原生執行；它們在 offscreen 下跳過，不算通過。原生執行時發現
`test_puppet_workspace.py` 三項早於本批次的過期斷言（開檔失敗訊息、範例目錄改為套件內
`examples_dir`），已依現行行為更新。

## R2.3–R2.7 綁定工具

隱藏原生驗收（`verify_rig_workflow.py`）：套用四種部件範本後 rig doctor 沒有需要修復的項目、
57 個極值與混合參數姿勢（12 種不同畫面）中透明邊緣雜點 0、破面 0；三種遮罩參數值下
遮罩重疊像素一致；取消與失敗的修復不改動文件。網格、階層、物理、診斷與範本的單元測試見
`test_mesh_tools.py`、`test_rig_hierarchy.py`、`test_physics_tools.py`、`test_rig_doctor.py`、
`test_part_templates.py`、`test_rig_quality.py`。

## R3 動畫

隱藏原生驗收（`verify_animation_workflow.py`）：錄製兩段 take（同名以「兩者都保留」另存），
修剪關鍵點，建立合成與對嘴動作後匯出。PNG 序列 48／48 幀，兩次渲染位元組相同，alpha
0–255；MP4 含音軌，60 幀 2.000 秒（預期 61 幀 2.033 秒，`-shortest` 以音訊長度截斷，在容差
內）；取消的匯出不留下檔案。格式新增的 `compositions` 與 `take` 以 v0.1.1 驗證向下相容
（見 R8.5）。

## R4 即時表演

隱藏原生驗收（`verify_live_workflow.py`），攝影機、麥克風與虛擬攝影機都以 driver 替身
提供，其餘為實際編輯器：

| 項目 | 結果 |
| --- | --- |
| 校正 | 中立值 4.0、靈敏度使結果落在參數中點，畫布數值與預期完全一致 |
| 仲裁 | 動作（motion）立即接管攝影機控制的參數；輸入來源表列出 28 個參數的控制者 |
| 裝置中斷 | 擷取停止送幀後回報 `device_lost` 並釋放裝置，1 秒後自動重連 |
| 失去臉部 | 參數依設定緩回預設值 |
| 切換裝置 | 先停止並釋放舊裝置，再於新索引啟動 |
| 睡眠喚醒 | 牆鐘跳躍一小時後重新啟動一次 |
| 麥克風 | 對嘴開口、串流結束後回報並重連，關閉後所有串流已關 |
| 虛擬攝影機 | 接收端每幀 120 ms 時仍送出並計算掉幀，GUI 最長間隔約 30 ms；畫面含角色像素；接收端持續失敗時輸出自動關閉並回報錯誤 |
| VTS API | 真實 loopback WebSocket：只綁 127.0.0.1、驗證與注入、第二個外掛被拒（454）、洪水請求被限速（6000）、撤銷後需重新驗證、網頁 origin 被拒 |

仍未驗收：實體攝影機／麥克風的拔插與權限（R4.1、R4.3）、實際虛擬攝影機與 NDI 接收端的
畫面、alpha、重連與延遲（R4.6）。

## R5 桌面角色

隱藏原生驗收（`verify_pet_workflow.py`）以兩個真實 `PetWindow`（各自 GL context、
`WA_DontShowOnScreen`）執行：兩者載入 Imeru 並共用材質位元組；換裝只影響其中一個；
錯誤的行為腳本被拒並保留原腳本；自我觸發規則在鏈深上限停止，每秒觸發的排程一分鐘內最多
3 次；本機不存在的 LLM 伺服器在數次失敗後進入離線且不再連線；停止一個角色不影響另一個；
隱藏時暫停 3 個驅動計時器，閒置時降為 66 ms；移到畫面外的角色回到有效區域；完全關閉後
0 個視窗、0 個計時器、0 個額外執行緒。

依本階段驗收規定，原生視窗定位（實體多螢幕、DPI、工作列）、穿透與 tray 行為另列實機驗收，
本批次未以替身結案（R5.2 保持未勾選）。

驗證程式早期兩次試跑時，行為規則的「說話」動作開啟了對話泡泡（獨立的頂層視窗），可能短暫
出現在桌面上；之後已在驗證時關閉對話並檢查沒有泡泡顯示。

## R6 自動化與宿主

8 個新命令共用 `command_ops`，CLI 與 MCP 使用同一份 schema；退出碼 0／1／2／3／4／130 與
JSON 錯誤代碼固定；長任務以子程序 job 執行，具進度、取消與冪等 `request_id`。
`test_gui_and_cli_produce_the_same_documents` 確認同一 PSD 經編輯器路徑與 CLI 得到位元組
相同的 archive，rig doctor 修復亦同。`host_api` 1.0 可在沒有 Qt 時匯入並清楚回報缺少 GUI。
消費端以新 wheel 驗證：Imervue 508 passed／8 skipped（`.audit/release/consumers/imervue.log`）、
FrontEngine Python 3.13 108 passed（`frontengine.log`），rigora 由各自環境的 site-packages 匯入。

## R7.3–R7.6 效能、資源與邊界

預算訂於 `scripts/perf_budgets.json`，最終三次中位數（`.audit/r7/final-summary/summary.md`）
全數符合，舊基線有 6 項不符。主要改善：GL 繪製 0.23–0.56×、深變形鏈 CPU 0.30×、遮罩 CPU
0.14×、Imeru 存檔 0.90×；開檔約多 30 ms 來自 R7.6 的數值檢查。資源生命週期
（`.audit/r7/lifecycle/lifecycle.json`）：context 重建後畫面像素相同、60 次文件切換記憶體
−4.9 MiB 且 handle 不增、反覆關閉回到基線、音效裝置已釋放。本批次後續變更（即時輸入仲裁、桌面角色）之後另跑一次（`.audit/final/benchmark`，未含長跑），22 項預算全數符合（`.audit/final/benchmark-summary/summary.md`）；單次量測僅作為抽查，不取代三次中位數。

## R8.3–R8.5 範例、指南與發行準備

| 項目 | 結果 |
| --- | --- |
| 範例 | 基本、進階綁定、動畫、直播、桌寵腳本五類皆有來源、授權、步驟與預期結果；`run_examples.py --render` 通過，含 48 幀 GPU 匯出 |
| 指南 | 三份指南各 46 個章節標題一致；新增從素材到成品、綁定工具、桌面角色、快捷鍵、疑難排解與選用依賴；五種 UI 語言的程式內字串無缺漏 |
| 發行文件 | 版本規則、檢查清單、發布前確認與回退：[releasing.md](releasing.md)；[CHANGELOG](../CHANGELOG.md)；[平台矩陣](platform-matrix.md) |
| 授權清單 | 依套件中繼資料重寫；更正 `pyvirtualcam` 為 GPL-2.0，移除 Rigora 未使用的套件 |
| wheel／sdist | `rigora-0.1.1` wheel 在全新 venv 通過 core 與 GUI 驗收（含本批次所有隱藏原生流程）；sdist 重建後通過 core（`.audit/release/installed-wheel`、`installed-sdist`）。之後只因授權檔更新重建，程式碼相同，重建品通過 core（`.audit/final/installed-wheel.log`） |
| 校驗 | `.audit/release/dist/SHA256SUMS.txt`：wheel `df97ab1c…9e26`、sdist `a75b6929…5791` |
| Windows 可攜版 | Nuitka 建置；offscreen 與隱藏原生 smoke 通過；解壓到空資料夾、PATH 只剩 System32 時兩種 smoke 仍通過；zip SHA-256 `2878c815…4eddc`（建於授權檔更新前，程式碼相同） |
| 升降版 | v0.1.1 開啟本版寫出的檔案（含合成與 take）且保留所有動作，本版開啟 v0.1.1 存回的檔案；可攜版 v0.1.1 → 本版 → v0.1.1 共用設定檔皆通過且設定保留（`.audit/release/upgrade/upgrade.json`） |

## 限制與待決事項

- R4.1、R4.3、R4.6、R5.2 需要實機或實際接收端，依規定未勾選；2026-11-13 經維護者決定與 R8.6 一併移出本次範圍。已取得的部分實機證據（`.audit/device/events.jsonl`）：列舉裝置不開啟裝置；真實攝影機啟動追蹤並下載臉部模型；停止後擷取執行緒結束並釋放攝影機。
- R8.6 公開發布須由維護者決定；本批次未建立 tag、未推送、未上傳。
- 工作樹的 `pyproject.toml` 把 `pyside6>=6.12.0` 列為核心依賴（早於本批次），與 R0「core
  不需 Qt」不符，且使乾淨安裝 core 時一併下載 PySide6 6.12.0。core 程式路徑仍不載入 Qt
  （安裝版檢查通過），但套件中繼資料的取捨需另行決定。
- GL 與效能只在本機 Windows＋NVIDIA 量測；Linux、macOS 見平台矩陣。

## 重跑方式

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'; py -3 -m pytest tests -q -ra
py -3 -m ruff check .; py -3 -m bandit -c pyproject.toml -r rigora
Remove-Item Env:QT_QPA_PLATFORM
py -3 scripts/verify_gui.py --source --output .audit/final/native-gui
py -3 examples/run_examples.py --render --output .audit/final/examples-out
py -3 -m build --outdir .audit/release/dist
py -3 scripts/verify_wheel.py .audit/release/dist --gui --output .audit/release/installed-wheel
py -3 scripts/verify_wheel.py .audit/release/dist --sdist --output .audit/release/installed-sdist
.audit/nuitka-env/Scripts/python.exe scripts/build_windows.py --output .audit/release/windows --native
py -3 scripts/verify_upgrade.py --output .audit/release/upgrade --old-exe <v0.1.1>/Rigora.exe --new-exe .audit/release/windows/Rigora.dist/Rigora.exe
py -3 scripts/release_checksums.py .audit/release/dist --check
```
