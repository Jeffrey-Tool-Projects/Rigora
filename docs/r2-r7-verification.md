# R2.1–R2.2／R7.1–R7.2 驗收紀錄

日期：2026-11-12。本次工作樹在 `88b3ebfde3c6a3ecf3c8c424cd2253426d00f4c9` 之上，含 R0／R1
與本批次尚未提交的變更。未建置或發布新的 wheel；安裝產物驗收沿用
[R0／R1 驗收紀錄](r0-r1-verification.md) 的範圍，本批次的新模組尚未在 checkout 外驗證。

## 環境

| 項目 | 內容 |
| --- | --- |
| OS | Windows 11，`10.0.26300-SP0` |
| CPU／記憶體 | AMD Ryzen 5 240 w/ Radeon 760M，12 邏輯核心，31.3 GiB |
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU，OpenGL 4.6.0，driver 621.14 |
| Python／套件 | Python 3.14.4、numpy 2.5.2、Pillow 12.3.0、PySide6 6.11.2、PyOpenGL 3.1.10 |

## 測試與檢查

| 驗證 | 結果 | 證據 |
| --- | --- | --- |
| 完整 offscreen 測試 | 1,785 passed、478 skipped、7 warnings，退出碼 0（R1 時為 1,735 passed） | [final-suite.log](../.audit/r2-r7/final-suite.log) |
| 原生平台工作區測試 | `test_puppet_workspace_init_state`、`test_puppet_workspace_cubism_import` 共 15 passed；不顯示視窗 | [native-workspace-tests.log](../.audit/r2-r7/native-workspace-tests.log) |
| Ruff／Bandit | 通過；0 issues | [ruff.log](../.audit/r2-r7/ruff.log)、[bandit.log](../.audit/r2-r7/bandit.log) |
| 原生隱藏 GL 編輯器驗收 | `status: passed`，含既有 R1 流程與本批次素材流程 | [report.json](../.audit/r2-r7/native-gui/report.json) |

上述兩個原生測試檔原本在 offscreen 下跳過，實際執行時發現兩項早於本批次的過期斷言：
初始化屬性快照少了 R1 新增的 9 個屬性；Cubism 合併測試仍要求直接修改開啟中的文件，
而 R1 已改為先在副本合併、再以交易套回同一個文件物件。兩者已依現行契約更新。
其餘 478 個 offscreen 跳過項目仍未執行，不算通過。

## R2.1 匯入預覽與差異報告

| 項目 | 實作與驗收 |
| --- | --- |
| PSD 讀取 | 保留巢狀群組（`group_path`、`parent`）、重複群組名、剪裁旗標、遮色片、填滿不透明度、原始混合鍵、附加資訊鍵、原始邊界與無像素紀錄（調整圖層等）。遮色片通道不再以圖層尺寸解碼，raw／RLE 皆不會破壞像素 |
| PSD 預覽 | `plan_psd_import` 只解碼一次，`preview` 列出每層順序、群組、狀態、id、尺寸、位置、不透明度、混合、遮色片與剪裁；`build()` 由同一份資料建立文件，預覽與匯入不會不一致 |
| 對應改進 | 群組成為巢狀 Part 並保留隱藏與不透明度；Multiply／Linear Dodge 對應 `multiply`／`additive`；剪裁對應基底圖層的 `clip_mask`；重複或非 ASCII 群組名不再產生相同 Part id |
| 差異 | 17 種 PSD 差異與 22 種 Cubism 差異，分 `error`／`warning`／`info`，JSON 可序列化，五種 UI 語言皆有標籤 |
| Cubism 預覽 | 只讀 JSON、不載入 SDK；列出參照檔案、略過的 `PartOpacity`／`Model` 曲線、缺檔、完整轉換不讀的 pose、合併時同名略過、無對應 drawable 的 hit area 與缺少的參數。缺 `.moc3`、缺 Cubism Core 或會中止合併的缺檔會停用匯入 |
| GUI | 選檔後先顯示預覽，取消不改文件；成功匯入後狀態列顯示改變的來源功能數，`last_import_preview` 保留報告 |

測試：[test_psd_import_preview.py](../tests/test_psd_import_preview.py)、
[test_cubism_import_preview.py](../tests/test_cubism_import_preview.py)、
[test_import_preview_dialog.py](../tests/test_import_preview_dialog.py)。

## R2.2 素材更新與重新連結

| 項目 | 實作與驗收 |
| --- | --- |
| 穩定對應 | drawable 以全新匯入會得到的 id 對應圖層；改名圖層可用 `mapping` 指定。位置重疊的「消失＋新增」標為可能改名，預設不新增 |
| 保留綁定 | 「取代像素」由 UV 與靜止頂點反推貼圖在畫布上的矩形，只換像素，頂點、權重、morph、變形器、Part 與動作不變；非整數矩形以整像素裁切並同步調整 UV，取樣位置不變 |
| 尺寸變更預覽 | 每列顯示目前與新範圍；新素材超出網格時標示。重建網格會列出丟棄的權重與 morph |
| 衝突 | 畫布尺寸不同阻擋更新；UV 非矩形或共用貼圖只能重建或略過；新增圖層插在 PSD 下方圖層之上並加入群組 Part；套用前驗證動作與文件未變，失敗不改動文件 |
| 缺失貼圖 | 偵測缺少與無法解碼的貼圖、預期尺寸；依檔名在資料夾搜尋任何影像格式；重新連結前預覽尺寸與長寬比差異 |
| 交易 | 更新與重新連結各為一個 Undo 步驟；過期 revision 拒絕套用。開檔時缺貼圖會在狀態列提示選單位置 |

原生隱藏編輯器實測：預覽列出 3 個圖層並回報遮色片未套用；更新後骨骼權重保留、
畫面改變，Undo 回到完全相同的 framebuffer SHA-256，Redo 亦相同；缺貼圖檔開啟後重新連結，
畫面與原貼圖一致。測試：[test_asset_update.py](../tests/test_asset_update.py)、
[test_asset_update_workflow.py](../tests/test_asset_update_workflow.py)、
[verify_asset_workflow.py](../scripts/verify_asset_workflow.py)。

## R7.1 基準場景

[bench_scenes.py](../scripts/bench_scenes.py) 以程式產生純色貼圖與網格，不含第三方素材，
同一參數兩次建置的 archive 位元組相同，驗證器無錯誤。實際規模：

| 場景 | 文件 | Drawable | 頂點 | 三角形 | 變形器（最大深度） | 其他 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| imeru | 1 | 23 | 20,261 | — | 6（1） | 3 條物理鏈 |
| many_drawables | 1 | 400 | 14,400 | 20,000 | 4（1） | 200 個骨骼權重、200 個 morph、16 張貼圖 |
| deep_deformers | 1 | 40 | 2,560 | — | 32（32） | 32 個參數 |
| masks | 1 | 120 | 1,920 | — | 1（1） | 60 組 clip mask |
| physics | 1 | 48 | 1,728 | — | 48（1） | 48 條鏈、384 個粒子 |
| multi_pet | 4 | 92 | 81,044 | — | 24（1） | 4 份獨立 Imeru、12 條物理鏈 |

## R7.2 量測基線

[benchmark.py](../scripts/benchmark.py) 在同一台機器連續跑兩次，參數相同：每項 5 次重複、
CPU 300 幀、GL 120 幀、1024 px 目標、Imeru 300 秒長跑。CPU 幀是編輯器每幀做的工作：
動作取樣、物理、頂點合成、pose／Part 可見性、不透明度與色調。GL 是
`render_offscreen_puppet`（繪製＋FBO 讀回），多份文件時每份一個隱藏 canvas。

| 場景 | 開檔 ms | 存檔 ms | CPU 幀中位數 ms | CPU p95 ms | GL 繪製＋讀回中位數 ms | 匯出 fps |
| --- | --- | --- | --- | --- | --- | --- |
| imeru | 354 / 452 | 629 / 752 | 3.15 / 4.71 | 4.06 / 7.22 | 7.1 / 18.4 | 10.6 / 6.9 |
| many_drawables | 96 / 105 | 83 / 112 | 3.55 / 3.82 | 5.18 / 5.09 | 46.6 / 88.1 | 9.0 / 5.5 |
| deep_deformers | 16 / 15 | 17 / 15 | 36.4 / 31.3 | 52.6 / 46.4 | 8.2 / 14.4 | 16.3 / 11.5 |
| masks | 13 / 11 | 12 / 12 | 3.11 / 1.90 | 6.66 / 2.84 | 39.0 / 63.8 | 11.0 / 7.7 |
| physics | 15 / 13 | 19 / 13 | 6.43 / 5.56 | 9.77 / 8.84 | 14.1 / 15.1 | 14.1 / 13.5 |
| multi_pet | 1,640 / 2,053 | 3,049 / 2,999 | 16.8 / 18.2 | 22.0 / 34.9 | 26.9 / 68.7 | 8.2 / 4.9 |

每格為「第 1 次 / 第 2 次」。冷啟動（新程序，中位數）：core 匯入 544 / 501 ms、
GUI 模組匯入 1,601 / 1,441 ms、開啟 Imeru 507 / 549 ms。300 秒長跑 RSS 由
387.2 → 387.3 MiB 與 387.5 → 387.7 MiB，斜率 19.6 / 35.6 KiB/min，沒有持續增長跡象。
1024 px PNG 編碼每幀 52–135 ms，是匯出速度的主要瓶頸。

報告與原始資料：[第 1 次](../.audit/r2-r7/benchmark-run1/benchmark.md)、
[第 2 次](../.audit/r2-r7/benchmark-run2/benchmark.md)（同目錄另有 `benchmark.json`）。
另有一次與 lint 同時執行的量測已中止並捨棄，不列入。

## 限制與後續

- 兩次之間 GPU 時間最多差約 2 倍、CPU 中位數最多約 1.6 倍，可能來自筆電電源與溫度狀態。
  R7.3 訂預算前，需固定電源模式，每個場景取多次執行的中位數；本次數字只作為基線，不是預算。
- 由基線看出的優化候選：32 層變形器鏈 CPU 每幀 31–36 ms；`many_drawables` 與 `masks`
  GL 繪製 39–88 ms；Imeru 存檔 0.6–0.75 秒；1024 px PNG 編碼。R7.3 須先以 profiler 確認。
- GL 量測只在 Windows＋NVIDIA 執行；其他 GPU、Linux、macOS 未量測。多桌寵只量 CPU 與
  隱藏 canvas 繪製，沒有實際透明桌寵視窗、tray 或 hook。
- 原生測試視窗 `IsWindowVisible` 為 false；前景 HWND 與游標前後觀測有變化，與 R1 相同，
  不宣稱整個桌面狀態不變。驗證程式沒有移動滑鼠或注入鍵盤。
- 工作樹的 `pyproject.toml` 目前把 `pyside6>=6.12.0` 列入核心依賴，且本機 PySide6 為 6.11.2。
  這不是本批次的修改，但與 R0「core 不需 Qt」的驗收不符，需另行決定後重新驗證安裝產物。
- `.audit/r2-r7` 的證據檔由 `.gitignore` 排除，分享報告時須一併提供。

## 重跑方式

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
py -3 -m pytest tests/ -q -ra
py -3 -m ruff check .
py -3 -m bandit -c pyproject.toml -r rigora
$env:QT_QPA_PLATFORM = 'windows'
py -3 -m pytest tests/test_puppet_workspace_init_state.py tests/test_puppet_workspace_cubism_import.py -q
Remove-Item Env:QT_QPA_PLATFORM
py -3 scripts/verify_gui.py --source --output .audit/r2-r7/native-gui
py -3 scripts/benchmark.py --gl --soak 300 --output .audit/r2-r7/benchmark-run1
```
