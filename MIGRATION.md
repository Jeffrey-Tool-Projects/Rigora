# Puppet 獨立專案拆分計畫

日期為 2026-11-11。來源為 `dev` 的 `d5fbb8339f89d75568007b4f2e319e728236db3e`。
目標是讓 Puppet 有獨立 GitHub repository、安裝套件、啟動入口與測試，並讓 Imervue 和 FrontEngine 使用同一份實作。
使用者已於 2026-11-11 選定專案品牌 **Rigora**。目標 repository 為
`Jeffrey-Tool-Projects/Rigora`，拆分期間預設 private。
Python distribution 與 import 名稱需另外核實可用性，不因 GitHub 名稱可用就視為已取得套件名稱。

## 完成條件

- 乾淨環境可以安裝新 wheel，執行模型讀寫、驗證與 runtime，無須安裝 Imervue。
- 獨立 GUI 可以開啟範例、編輯、儲存、播放、匯出並正常結束。
- Imervue 的 Puppet 分頁、桌寵、CLI、MCP 與 FrontEngine 的 Puppet adapter 使用新套件並通過合約測試。
- 新專案包含授權、格式文件、範例、測試與 CI；Imervue 不再維護第二份 runtime。
- 舊 `.puppet` 文件仍可讀取；既有 MIME、schema URL 與檔案格式版本不因品牌改名而改動。

## 已確認的邊界

靜態盤點找到 122 個 Puppet Python 模組，26 個檔案匯入 Puppet 以外的 Imervue 模組。
另有 126 個 repository 內的 Python 檔案匯入 Puppet，包含測試。這不是 126 個外部產品。
盤點不涵蓋動態字串匯入與其他 repository，必須補查 CLI registry、打包設定及 FrontEngine。

| 邊界 | 現有位置 | 拆分處理 |
| --- | --- | --- |
| 原子存檔 | `Imervue/puppet/document_io.py` → `system.atomic_write` | 先確立新核心的存檔責任，保留失敗時不破壞原檔的行為 |
| PSD | `psd_import.py` → `paint.psd_io` | 追查 PaintDocument 與圖層轉換，避免連整個 Paint 一起搬走 |
| 桌寵陰影 | `canvas_render.py` → `desktop_pet.pet_shadow` | 解開桌寵與 Puppet 的雙向依賴，決定陰影幾何與 renderer 的所有權 |
| OpenGL | `canvas_frame.py` → `gpu_image_view.gl_context` | 保留 context-aware 資源釋放，背景測試不能冒充實際 GL 驗證 |
| 宿主服務 | `workspace*`、dock、timeline | 隔離翻譯、設定、圖示、UI scale、timer、背景工作、檔案篩選與安裝器 |
| 模型與範例 | `webcam_tracker.py`、`workspace_menus.py` | 新應用自行定位資料與快取，不依賴 Imervue app_dir |
| 外部消費者 | `architecture.md` §6 | FrontEngine 的 adapter、extra 與 interchange tests 同輪遷移 |
| 格式身份 | `format_schema.py`、`docs/schemas/` | 舊 schema URL 永久保留；遷移 repository 不等於變更格式 |

`Imervue/puppet/__init__.py` 延遲載入 workspace，讓 headless 模型工具不啟動 Qt widgets。新套件必須保留這個性質。

## 執行順序與驗收

| 階段 | 工作 | 通過條件 |
| --- | --- | --- |
| 1 | 固定來源 revision、檔案 SHA-256、雙向 import 清單與原專案測試基準 | 可重查來源；失敗與跳過項目明確記錄 |
| 2 | 選定品牌與套件名；建立新 GitHub 專案，保留來源與授權 | 遠端 repository、可見性及來源記錄可核對；沒有 SDK、憑證或私人模型 |
| 3 | 分離 document、archive、schema、runtime 與存檔支援 | 在未安裝 Imervue 的環境通過讀寫、錯誤輸入、動畫與物理測試 |
| 4 | 解開 PSD、pet shadow、GL 與宿主服務依賴，建立獨立 GUI 入口 | 範例開啟、存檔、播放、匯出、關閉成功；設定及模型快取屬於新應用 |
| 5 | 完成 wheel/sdist、可選依賴、範例資源與 CI | 從建置產物安裝並驗證，不靠 checkout 的 sys.path；不自動發布 PyPI |
| 6 | 同輪遷移 Imervue 與 FrontEngine 呼叫者、打包設定與合約文件 | GUI／桌寵／CLI／MCP／FrontEngine 合約皆通過，才移除舊實作 |
| 7 | 同步各語言文件、版本相依、安裝方式與發行流程 | 全套測試、ruff、bandit 通過；舊 schema URL 仍有效 |

新套件不反向依賴 Imervue。暫存 source snapshot 只供拆分使用，不視為可安裝版本。
階段 2 的來源匯入優先保留選定路徑的歷史；只在新的隔離 clone 執行歷史篩選，不改寫 Imervue 歷史。
若先上傳 snapshot，必須標明來源 commit，且不得宣稱保留了逐檔歷史。

## 本次執行紀錄

已建立本機靜態 import 清單及 260 個候選搬移檔案的 SHA-256 manifest。
候選清單涵蓋 Puppet 程式、專屬測試、範例、schema、使用指南及授權。
它尚未包含可獨立執行測試所需的共用 fixtures，不能直接當成獨立專案的完整內容。

原專案完整測試以 `QT_QPA_PLATFORM=offscreen` 執行，避免搶佔前景。
這會跳過需要實際 GL widget 的測試，不能代表 GUI／OpenGL 驗證完成。
核心基準為 161 passed、13 skipped，涵蓋 `test_puppet_document_io.py`、`test_puppet_runtime.py`、
`test_puppet_format_schema.py`、`test_puppet_physics.py`、`test_puppet_archive_contracts.py`。
ruff 通過；bandit 未發現問題。原專案完整測試為 17,886 passed、1,439 skipped、9 warnings，
退出碼 0，耗時 771.98 秒。這是原 Imervue 的 offscreen 基準，不是新 Rigora 的獨立安裝驗證。
現有 `test_coverage.md` 為使用者原本的未追蹤檔案，不納入本次變更。

盤點資料在 [source-inventory.json](migration/source-inventory.json)。
原 Imervue checkout 的 `.audit/puppet-split/source-snapshot.zip` 保存候選檔案，依 manifest 逐檔核對 SHA-256。
SHA-256 對應本機 tracked 檔案位元組，Windows 換行可能與 Git blob 不同。
這份 ZIP 不包含 Git 歷史，也沒有獨立套件設定。

另已讀取 `D:/Codes/FrontEngine/FrontEngine/utils/imervue/runtime.py` 與 `pyproject.toml`，
確認其實際 imports 與 `puppet = ["Imervue>=1.0.90"]`，不只依賴架構文件的描述。

工作量檢查點放在階段 1 結束。先確認測試基準與跨專案合約，再進入程式搬移；不把數百個模組的搬移與品牌改名混在同一階段。

## Rigora 來源抽取

已在 `D:/Codes/Rigora` 建立隔離 checkout，使用 git-filter-repo 2.47.0 篩選選定路徑，
保留 179 筆相關歷史提交，包含舊 `plugins/puppet/` 路徑。未改寫 Imervue 歷史。
加入新專案文件前，260 個檔案的 Git blob 與來源 revision 全數一致；`git fsck --full` 通過。
新專案的 `migration/` 保存選取路徑、commit mapping 與來源記錄。

程式碼暫時維持原 import 路徑。下一階段從 document／archive／runtime 與原子存檔邊界開始，
讓新套件在未安裝 Imervue 的環境通過測試，再接續 GUI 與呼叫者遷移。
