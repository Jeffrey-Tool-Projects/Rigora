# R0／R1 驗收紀錄

日期：2026-11-11。這是本次工作樹的驗證，與 `MIGRATION.md` 的歷史拆分結果分開記錄。

## 版本與環境

| 項目 | 本次基準 |
| --- | --- |
| Rigora 基礎 commit | `790553fcd8b0fd949deca60551226fac95d2f554`，另加本次尚未提交的變更 |
| Imervue 基礎 commit | `14a80a7ad136bdf6370a272450ebd60bdf1487c7`，另加主視窗關閉保護與對應測試 |
| FrontEngine commit | `9b0bc0364ebbde0ce8a491a923e21678e85fce3a`，未修改其程式 |
| OS | Windows 11，`10.0.26300-SP0` |
| 來源樹測試 | Python 3.14.4、PySide6 6.11.2 |
| 乾淨 core／GUI wheel | Python 3.14.4；core 無 Qt，GUI 安裝 PySide6 6.12.0 |
| FrontEngine 支援環境 | Python 3.13.9、PySide6 6.12.0；另保留 Python 3.14.4 的補充測試，後者不算其支援版本驗收 |
| 原生 GL | NVIDIA GeForce RTX 5060 Laptop GPU，OpenGL 4.6.0，driver 621.14 |

本次 wheel 的 225 個 Python 模組逐檔與工作樹位元組核對一致。清單保存在
[worktree-manifest.json](../.audit/r0-r1/worktree-manifest.json)。產物尚未公開發布。

| 產物 | SHA-256 |
| --- | --- |
| `rigora-0.1.0-py3-none-any.whl` | `25798f709952a0ae7d88c9a831f4367e56179518cb6bab8d058e7b71b74a1bfe` |
| `rigora-0.1.0.tar.gz` | `bba3cb62eb06dc1c0ba8deb735974e359addeb6143bd0c4f3a86b085c6c9f708` |

## 測試與安裝結果

| 驗證 | 結果 | 證據 |
| --- | --- | --- |
| 修改前完整 offscreen 基線 | 1,705 passed、478 skipped、7 warnings，退出碼 0 | [baseline-tests.log](../.audit/r0-r1/baseline-tests.log) |
| 修改後完整 offscreen 測試 | 1,735 passed、478 skipped、7 warnings，退出碼 0 | [final-suite.log](../.audit/r0-r1/final-suite.log) |
| Ruff | 通過 | [ruff.log](../.audit/r0-r1/ruff.log) |
| Bandit | 0 issues、0 files skipped | [bandit.log](../.audit/r0-r1/bandit.log) |
| wheel／sdist 建置 | 通過 | [build.log](../.audit/r0-r1/build.log) |
| 乾淨 core wheel | 無 Imervue、無 Qt／攝影機／麥克風／虛擬攝影機選用依賴；模型 IO、runtime、schema、CLI handlers／MCP 與範例通過 | [core.json](../.audit/r0-r1/final-wheel/core.json) |
| 乾淨 GUI wheel | 原生隱藏視窗、實際 GL、編輯及恢復流程通過 | [GUI report](../.audit/r0-r1/final-wheel/gui/report.json) |
| sdist 重新建 wheel 並安裝 | 通過；從 sdist 建置產物安裝至另一個 checkout 外的虛擬環境 | [sdist verification](../.audit/r0-r1/final-sdist/verification.json) |
| 作業系統唯讀 package 目錄 | core、GUI 與 sdist 重建產物皆通過；實際寫入 probe 被拒絕，驗證後還原權限 | [wheel verification](../.audit/r0-r1/final-wheel/verification.json) |
| 新 session 的獨立 headless 安裝驗證 | 通過；無 Qt、OS 唯讀目錄中完成交易、undo／redo、save point 與保存驗證 | [session core log](../.audit/r0-r1/final-session-core.log) |
| Imervue 安裝版合約及關閉保護 | 68 passed、2 warnings，退出碼 0 | [imervue-consumer.log](../.audit/r0-r1/imervue-consumer.log) |
| FrontEngine 安裝版合約，Python 3.13.9 | 53 passed、5 skipped，退出碼 0 | [frontengine313-consumer.log](../.audit/r0-r1/frontengine313-consumer.log) |

core 驗證在 `%TEMP%/rigora-wheel-*/env/Lib/site-packages/rigora` 執行，工作目錄在 checkout 外。
消費端分別使用 `.audit/r0-r1/consumer-env` 與 `.audit/r0-r1/frontengine313-env` 安裝的 wheel；
另以 Python `-I` 確認 import 路徑位於各自的 `site-packages`。FrontEngine 3.13 環境也從其
checkout 建置並安裝了 `frontengine_dev`，沒有沿用 3.14 的全域安裝。

Windows 權限 probe 先確認可讀且不可寫，再跑驗證；禁止寫入只施加於新建驗證環境的
`rigora` 目錄。初次使用泛用 W 權限時同時拒絕讀取，已用獨立暫存案例重現並改成
WD／AD／WEA／WA 權限。該次失敗不算安裝通過，表格引用的是修正後的結果。

## R0 逐項證據

| 工作 | 完成內容 |
| --- | --- |
| R0.1 | 保存基礎 commit、環境、修改前後完整測試、警告與跳過原因；沒有重用歷史遷移數字 |
| R0.2 | checkout 外的 core／GUI wheel、sdist 重建、缺選用依賴及 OS 唯讀目錄驗證；實際 framebuffer 與清理證據另列 |
| R0.3 | [公開介面與消費端矩陣](public-api.md)，含缺套件退化、設定／工作管理、close／shutdown 契約及實際消費端測試 |
| R0.4 | 修正格式規格的 schema 路徑、現行 CLI 指令及品牌敘述；三份指南區分 Rigora 資料目錄，保留真實 NDI 預設來源名與永久格式 ID |
| R0.5 | CI 改成辨識唯一 wheel，拒絕混入多版本產物；固定 Imervue revision。FrontEngine 遠端 CI 評估後暫不加入，理由及本機替代驗收記於公開契約 |

## R1 逐項證據

| 工作 | 實作與驗收 |
| --- | --- |
| R1.1 | `DocumentSession` 擁有路徑、save point／saved revision、dirty、選取與文件識別；狀態列顯示未儲存標記。實際播放、參數輸入及 NumPy morph cache 不造成 dirty |
| R1.2 | Qt-free undo／redo、可巢狀複合交易與例外回滾；參數、drawable／骨骼權重、變形器、表情、姿勢、物理、動作都有往返測試。mesh／timeline gesture 在完成時建立一筆歷史；預設最多 100 筆、128 MiB 估算歷史預算 |
| R1.3 | 開檔、替換匯入及獨立／Imervue 主視窗關閉提供 Save／Discard／Cancel。取消、取消 Save As、寫入中斷與 PermissionError 保留文件與 save point；Reset to rest 保留 authored 資料及錄製 take |
| R1.4 | 原子恢復 archive、可設定間隔、每個程序與文件獨立識別及程序鎖。測試涵蓋活躍程序排除、程序直接退出、損壞 archive、寫入失敗及實際 GUI 選擇恢復後另存；原檔與恢復來源均保留 |
| R1.5 | 開檔／匯入捕捉 revision，過期結果拒絕套用；Cubism 合併先在副本執行，失敗不污染文件。錄製拒絕過期 take，文件修改／切換／undo 停止舊輸出工作，批次匯出的舊 timer 保持失效；錯誤回報步驟與重試方式 |

核心與故障測試見 [test_document_session.py](../tests/test_document_session.py) 和
[test_workspace_session.py](../tests/test_workspace_session.py)。原生整合驗收由
[verify_editor_session.py](../scripts/verify_editor_session.py) 在真正的隱藏編輯器執行，
不使用桌面鍵鼠注入。

## 實際渲染與背景觀測

安裝版原生驗證確認 23 個 drawable、透明背景、非單色角色像素與動作造成的畫面變化。
中立姿勢儲存重開後的像素 SHA-256 與原始中立姿勢相同。關閉後 active timer 為空，
Desktop Pet 控制頁建立成功，未啟動可見桌寵或系統 tray。

- [中立 framebuffer](../.audit/r0-r1/final-wheel/gui/imeru-neutral.png)
- [動畫 framebuffer](../.audit/r0-r1/final-wheel/gui/imeru-animated.png)
- [重開 framebuffer](../.audit/r0-r1/final-wheel/gui/imeru-roundtrip.png)

原生測試視窗的 `IsWindowVisible` 檢查為 false。前景 HWND 與游標前後觀測有變化，
因此不宣稱整個桌面狀態保持不變，也不從前後差異推斷變化來源。驗證程式只讀取這些狀態，
沒有移動滑鼠、注入鍵盤或啟動可見視窗。

## 限制與後續階段

- 478 個 offscreen 跳過項目不算通過；原生驗證只覆蓋報告列出的流程，沒有聲稱跑完所有被跳過的 GL 測試。
- FrontEngine 的 5 個跳過項目需要 Windows 目錄符號連結權限。本次未更動系統權限以執行它們。
- 攝影機、麥克風、網路輸出、可見桌寵、tray、Linux／macOS 實機與效能預算仍屬後續階段，沒有用本次測試宣稱完成。
- Imervue 的 host-close 變更在本機工作樹；要交付嵌入編輯保護，須與本次 Rigora wheel 一起交付。CI pin 待該消費端變更提交並在遠端可用後再推進；本次沒有宣稱遠端 CI 已執行。
- `.audit/r0-r1` 的原始 log、JSON 與圖像保留於本機並由 `.gitignore` 排除。上面的相對連結供目前工作區檢閱；分享報告時需一併帶出證據檔案。

## 重跑方式

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
py -3 -m pytest tests/ -q -ra
py -3 -m ruff check .
py -3 -m bandit -c pyproject.toml -r rigora
py -3 -m build --outdir .audit/r0-r1/dist
py -3 scripts/verify_wheel.py .audit/r0-r1/dist --gui --readonly --output .audit/r0-r1/final-wheel
py -3 scripts/verify_wheel.py .audit/r0-r1/dist --sdist --readonly --output .audit/r0-r1/final-sdist
```

`--gui` 的原生隱藏視窗驗證限 Windows；其他平台的 core／sdist 驗證不需要該選項。
每次報告須附當次 source revision、工作樹變更及產物 hash，不以版本字串 `0.1.0` 識別不同 build。
