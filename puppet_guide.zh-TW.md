# Puppet 指南 — 直播與動畫製作

請在公開的 Rigora 原始碼 checkout 執行 `python -m pip install ".[gui]"`，再執行 `python -m rigora`。此處從原始碼安裝，不依賴 PyPI 發行版本。本指南的編輯器也可在已安裝 Rigora 的 Imervue Puppet 分頁使用。套件範例由 `rigora.system.app_paths.examples_dir()` 定位；以下 `examples/` 路徑指 Rigora 原始碼 checkout。

從「我想做 VTuber 風直播或短動畫」走到「我已經在 OBS 上直播 / 我手上有一個 MP4 檔」的完整流程，用 Rigora 的 **Puppet** 分頁完成。

兩條路：

1. **直播** — 用滑鼠 / 麥克風 / 攝影機驅動 puppet rig，把結果送進 OBS 串流或錄影。
2. **動畫製作** — 錄一段 take、編輯動作時間軸、輸出 GIF / MP4 / WebM。

兩者共用同一個 rig 跟參數系統，差別只在輸出端是直播虛擬鏡頭還是磁碟上的檔案。

---

## 目錄

- [快速開始](#快速開始)
- [從素材到完成的角色](#從素材到完成的角色)
- [Part 1 — OBS 直播整合](#part-1--obs-直播整合)
- [Part 2 — 製作動畫](#part-2--製作動畫)
- [Part 3 — 桌面角色](#part-3--桌面角色)
- [匯入 rig](#匯入-rig)
- [進階功能](#進階功能)
- [選用依賴](#選用依賴)
- [鍵盤快捷鍵](#鍵盤快捷鍵)
- [疑難排解](#疑難排解)

---

## 快速開始

1. 啟動 Rigora（從原始碼跑就 `python -m rigora`）。
2. 點視窗頂端的 **Puppet** 分頁。
3. **File > Examples > Imeru**（或工具列的 **Examples ▾** 下拉）。內附的 rig — Rigora 的吉祥物 — 居中載入。
4. 在底部 **Motions** 擺放欄點 8 個動作中的任一個 — rig 立刻動起來。
5. 工具列的 **Reset to rest** 按鈕把 rig 拉回靜止姿勢。

這是基本款。下面解釋怎麼把這個 idle rig 變成直播或影片檔。

---

## 從素材到完成的角色

從分層插畫到能直播、做動畫、待在桌面上的角色，一條完整路徑。每一步都連到對應章節。

1. **匯入。** **File > Import PSD…** 會先列出每個圖層，以及匯入無法保留的功能（遮色片、不支援的混合模式），確認前不會改動任何東西（[從 PSD](#從-psd)）。Cubism 模型走 **File > Import Cubism…**。
2. **檢查 rig。** **Tools > Rig doctor…** 列出損壞的網格、權重與左右對稱問題、缺少的標準綁定以及驗證錯誤，套用前先預覽每項修正（[Rig doctor 與部件範本](#rig-doctor-與部件範本)）。
3. **加入標準部件。** **Tools > Part templates…** 幫你選的圖元加上眨眼、嘴型、轉頭與擺動（[部件範本](#rig-doctor-與部件範本)）。
4. **細修。** 用 **Mesh** 選單調整網格與權重（[編輯網格與權重](#編輯網格與權重)），在擺放欄整理變形器與參數群組（[整理變形器與參數](#整理變形器與參數)），用 **Tools > Physics chains…** 調頭髮與衣物（[物理](#物理)）。
5. **校正並表演。** 在 **Live > 輸入裝置與校正…** 選裝置、調追蹤，然後開始直播（[Part 1](#part-1--obs-直播整合)）。
6. **做動畫。** 錄 take、編輯關鍵點、編排合成並匯出（[Part 2](#part-2--製作動畫)）。
7. **放到桌面。** 在 Desktop Pet 分頁載入 rig 並給它一個腳本（[Part 3](#part-3--桌面角色)）。
8. **素材更新時。** **File > Update art from PSD…** 只換像素、保留綁定（[從 PSD 更新素材](#從-psd-更新素材)）。

每個會改動 rig 的步驟都是一個 **Edit > Undo** 步驟。

---

## Part 1 — OBS 直播整合

目標：在 OBS 上有一個 webcam 風視窗顯示你的 puppet，被你的臉 / 麥克風 / 滑鼠驅動，準備好放進直播。

### 1.1 輸入端（什麼驅動 rig）

Puppet 工具列有 6 個即時輸入 toggle（**Live** 選單也有同樣 6 個），可以同時開（彼此不衝突、只要驅動不同參數）。

| Toggle | 驅動 | 選用依賴 |
|---|---|---|
| **Drag-track head** | `ParamAngleX/Y`、`ParamEyeBallX/Y` 跟著在 canvas 上移動的滑鼠游標 | 無 |
| **Auto-blink** | `ParamEyeLOpen/ROpen` 每 ~4.5 秒眨一次眼 | 無 |
| **Mic lip-sync** | `ParamMouthOpenY` 跟著麥克風音量、`ParamMouthForm` 跟著母音音色 | `sounddevice` |
| **Webcam tracking** | 臉部 landmark 驅動頭部 yaw/pitch/roll、眼睛開合、視線與嘴巴開合 | `opencv-python` + `mediapipe` |
| **Auto idle** | 呼吸循環 + 頭 / 身體輕微 drift | 無 |
| **Idle motions** | 每 8 秒從 `Idle` 群組隨機播一個動作 | 無 |

典型臉部追蹤 VTuber 設定：開 **Webcam tracking** + **Auto-blink** + **Mic lip-sync**。打開 *Webcam tracking* 時會跳出預覽視窗，顯示攝影機畫面 + 偵測到的 landmark — 用來確認 tracker 真的有看到你。

> **首次使用注意** — webcam tracking 需要 `mediapipe` 的 face-landmark 模型。Rigora 第一次啟用會自動下載（~3.7 MB，從 Google Cloud Storage）到 `<Rigora data directory>/models/face_landmarker.task`，之後直接用快取。

**Live > 輸入裝置與校正…** 選擇攝影機與麥克風，並調整追蹤怎麼帶動 rig。設定存成具名的設定檔（例如每個房間或座位一份）：

- **靈敏度**、**死區**、**平滑** 套用在每個追蹤參數上。平滑在任何攝影機幀率下效果相同。
- **擷取中立姿勢（2 秒）** — 開著攝影機追蹤、放鬆坐好後按下。Rigora 記下你靜止時的姿勢，當成每個參數的預設，頭稍微偏一點就不會被當成「看向別處」。
- **多久後回到中立** / **回歸時長** — 臉離開畫面時，rig 等這段時間後緩緩回到靜止姿勢，而不是停在表情中途。
- **麥克風增益**、**麥克風噪音閘**、**嘴型同步平滑** 調整麥克風對嘴；噪音閘讓環境雜音不會讓嘴巴抽動。

列出裝置不會開啟它們；只有 **Webcam tracking** 會打開攝影機。

多個輸入驅動同一個參數時，同一時間只有一個來源控制它。優先順序較高的來源立即接管；較低的來源要等目前控制者停止寫入 0.25 秒（你拖過的滑桿是 1 秒）。順序：正在拖的滑桿 → VTS 外掛 → 播放中的動作 → 攝影機 → 麥克風 → 自動眨眼 → 滑鼠 → 待機。所以播放中的動作會蓋過攝影機，攝影機追蹤眼睛時會停用自動眨眼。**Live > 輸入來源…** 會列出每個參數目前由誰控制、上面疊了哪些表情。

**Output > VTS API** 是另一種輸入：它在 `ws://127.0.0.1:8001`（只限本機）開一個精簡版 VTube Studio Public API 伺服器，支援這個協定的臉部追蹤程式連上後，可以列出 rig 的參數並寫入數值。它只涵蓋追蹤程式需要的請求，不是完整的 VTube Studio API — 支援清單、token 規則與速率限制見 [VTS API 支援範圍](docs/vts-api-support.md)（英文）。token 12 小時後到期、關閉 API 時失效，也可以在 **Output > 即時狀態…** 立即撤銷。

### 1.2 輸出端（OBS 怎麼看到 rig）

三條路。新手用 **A**，要 pixel-perfect alpha 合成用 **B**；**C** 完全不用設定。

#### Path A — Virtual Camera

Puppet canvas 變成 OBS「視訊擷取裝置」來源清單裡的一台 webcam。

```bash
pip install pyvirtualcam
```

加上平台對應的虛擬攝影機驅動：

- **Windows**：裝 OBS Studio 26+，自帶 *OBS Virtual Camera* 驅動。第一次打開 OBS、右下角點 **Start Virtual Camera** 註冊驅動，之後 `pyvirtualcam` 才找得到。
- **macOS**：OBS for Mac 自帶 system extension，首次執行會要求在「系統設定 → 隱私權與安全性」啟用。
- **Linux**：`sudo apt install v4l2loopback-dkms` 然後 `sudo modprobe v4l2loopback exclusive_caps=1 card_label="Rigora"`。

接線：

1. Puppet 分頁開啟 rig，工具列 / **Output > Virtual camera** 打勾。狀態列會告訴你實際裝置名（通常是 *OBS Virtual Camera*）。
2. OBS：**Sources > + > Video Capture Device**，下拉選步驟 1 印出的裝置名。

**為什麼背景是洋紅色？**

虛擬攝影機走 DirectShow / AVFoundation / v4l2loopback，三個傳輸層**只有 RGB、沒有 alpha 通道**。OBS 把進來的影像當不透明 RGB 處理，所以 Rigora 在角色以外填什麼顏色，OBS 就顯示什麼顏色。挑 `#FF00FF` 是業界標準 chroma-key 色 — 幾乎不會出現在自然膚色 / 髮色 / 瞳色裡，去背容差可以開很寬。

**OBS 端去背：**

1. *Video Capture Device* 來源右鍵 → **Filters**
2. **Effect Filters → + → Color Key**
3. 設定：
   - **Key Color Type**：`Custom Color`
   - **Custom Color**：HEX `FF00FF`
   - **Similarity**：從 `80` 起跳，邊緣有殘留洋紅色就拉到 `200–300`
   - **Smoothness**：`30–50`，邊緣不會太硬
4. 關閉對話框 — 濾鏡會跟著來源，之後重啟虛擬攝影機都自動套用

#### Path B — NDI（專業、真實 alpha）

NDI 在 LAN 上以 < 50 ms 延遲傳 RGBA。不用色鍵 — alpha 通道整條傳過去。

```bash
pip install ndi-python
```

加上：

1. 從 <https://ndi.video/tools/> 下載 **NDI Tools** — installer 包含 runtime DLL，`ndi-python` 會 link 進去。
2. OBS 端裝 **obs-ndi** 插件：<https://github.com/obs-ndi/obs-ndi/releases>

接線：

1. Puppet 分頁工具列 / **Output > NDI output** 打勾。狀態列顯示來源名（預設 *Imervue Puppet*）。
2. OBS：**Sources > + > NDI Source**，下拉選步驟 1 的來源名。

角色直接合成到 OBS 場景，零色鍵濾鏡。Off-screen render 把角色外的區域填成完全透明。

**`ndi-python` Windows 編譯前置**

`ndi-python` 只 ship source distribution，pip 拿到後從 C++ 編。Windows 上要：

- **Visual Studio Build Tools 2022** 勾「**使用 C++ 的桌面開發**」工作負載
- **CMake**（安裝時勾 *Add to system PATH*）
- **NDI SDK**（跟 NDI Tools 不同，去 <https://ndi.video/for-developers/ndi-sdk/> 抓）裝在預設 `C:\Program Files\NDI\NDI 6 SDK\`
- 環境變數 `NDI_SDK_DIR` 指向 SDK 安裝路徑

嫌麻煩就走 Path A。

#### Path C — Window Capture（零安裝）

OBS **Sources > + > Window Capture** 可以直接抓 Rigora 視窗。沒有虛擬攝影機驅動、沒有 SDK。Trade-off：

- 抓整個 Rigora 視窗（含外殼），要加 OBS *Crop/Pad* filter 裁到只剩 puppet 區。
- Puppet 工作區的棋盤格背景也會跟著串。
- 受 Rigora 視窗大小限制。

只適合臨時 demo。要正式直播用 A 或 B。

### 1.3 角色獨立渲染路徑

Virtual Camera 與 NDI 都用 off-screen framebuffer 重畫，**不含棋盤格背景跟任何編輯器外殼**。Rigora 視窗裡的工具列 / 擺放欄 / 狀態列純粹是給你編輯用的，串流只有角色 drawable 本身。輸出長邊上限 1080 px（避免 3503×7777 的 Cubism canvas 把 DirectShow 驅動搞掛）。

### 1.4 兩段 take 之間重置

**Loop** 關閉時動作會停在最後一格，**Pause** 會停在當下姿勢，即時輸入也會把參數留在最後寫入的值。點工具列 **Reset to rest**（或 **Edit > Reset to rest**）一鍵歸零：

- Motion player 直接停（不走淡出）
- 所有即時輸入 toggle 取消勾，**Record motion** 也會停止（錄到的 take 會保留）
- Active expressions 清空
- Pose groups 還原第一個 member
- 物理鏈彈回靜止姿勢
- 參數值還原到 authored defaults

狀態列確認：「*Rig reset to neutral pose.*」

### 1.5 即時狀態與裝置問題

**Output > 即時狀態…** 顯示每個輸出與裝置的執行情形：接收端看到的名稱、解析度、實際與目標幀率、掉幀數、連線狀態與最近錯誤。VTS API 會顯示已連線的外掛數。

畫面透過兩格的佇列送往虛擬攝影機與 NDI。接收端比 rig 慢時，舊的影格會被丟掉並計數；編輯器本身不會等接收端。持續傳送失敗時輸出會自動關閉，狀態列會說明原因。

Rigora 會自行處理常見的裝置問題：

| 問題 | 會發生什麼 |
|---|---|
| 攝影機被拔除或被其他程式佔用 | 追蹤會回報，並在 1、2、4、8、15 秒後重試，之後停下等你按 **重試裝置** |
| 麥克風被拔除 | 對嘴會回報，並以相同方式重試 |
| 攝影機存取被拒 | 不自動重試；在系統設定允許攝影機存取後按 **重試裝置** |
| 臉部模型下載失敗 | 不自動重試；確認網路後按 **重試裝置** |
| 追蹤中在校正對話框換攝影機 | 先釋放舊攝影機，再啟動新的 |
| 電腦睡眠 | 喚醒後重新啟動一次追蹤 |

關閉一個輸入會停止它的擷取執行緒並釋放裝置。

---

## Part 2 — 製作動畫

目標：磁碟上有一個 `.mp4` / `.webm` / `.gif` / `.png` 檔。

### 2.1 從即時 take 錄製動作

最簡單的路徑：用臉 / 麥克風 / 滑鼠驅動 rig、即時錄下參數值，Rigora 烘焙成一個之後可以播 / 循環 / 儲存的 `Motion`。

1. 開啟 rig。
2. 啟用想驅動 rig 的即時輸入（webcam / drag / blink / lip-sync / idle），或準備自己拖 **Parameters** 擺放欄的滑桿。
3. **Output > Record motion**。對話框問你動作名稱（預設 `user_motion`），確認後開始錄製。
4. 表演 — 動臉 / 講話 / 移動滑鼠 — 持續多久都可以。
5. 再選一次 **Output > Record motion** 停止錄製。
6. 新動作出現在 **Motions** 擺放欄。如果已有同名動作，Rigora 會問你：**取代它**、**兩者都保留**（新 take 取有編號的名稱）或 **捨棄新錄製**。加入動作會重新載入 rig，參數、表情跟物理都回到預設值，而且是一個 **Edit > Undo** 步驟。點它播放，或 **File > Save As…** 把它存進 `.puppet` 檔。

每個 take 會記住錄製時間、取樣率與當時開著的即時輸入；取代動作時也會記下它取代了哪個 take。**Motions** 擺放欄的提示文字會顯示這些資訊。

錄製速率 30 Hz。沒變動的軌（整段都不變的參數）自動丟掉。每個保留的軌在每兩個相鄰取樣之間產生一個 linear segment。錄製器讀的是參數本身的值（滑桿、動作、即時輸入），所以表情疊加跟物理輸出不會錄進 take。錄出來的動作不屬於任何群組。

### 2.2 編輯錄好的動作

**Motion Timeline** 對話框可以事後微調動作的關鍵點。

1. 在 **Motions** 擺放欄點動作讓播放器載入它，再選 **Edit > Edit motion…**。
2. 從 **Track** 清單挑一個參數。圖表顯示該軌的關鍵點：X 軸是動作長度內的時間，Y 軸是該參數自己的範圍（rig 沒定義這個參數時為 −1 到 1）。
3. 拖黃色的點移動關鍵點的時間跟數值。`cubic-bezier` segment 可以拖紫色控制把手塑形。每個 segment 都畫成兩個關鍵點之間的直線。
4. **緩動** 會重塑目前顯示軌道的每個 segment：挑一種緩動曲線（例如 `ease-in-out-sine`），再按 **套用到此軌道**。關鍵點留在原位；`elastic` 與 `bounce` 會變成每個 segment 16 個 linear 關鍵點。**精簡關鍵影格** 會在每條軌上刪掉與前後關鍵點連線相差在 **容許誤差**（參數範圍的百分比）以內的關鍵點 — 把 30 Hz 的 take 精簡到真正重要的關鍵點，旁邊的標籤會顯示精簡前後的關鍵點數。對話框不能單獨新增關鍵點。
5. 每次拖曳都會更新記憶體中的動作，並把 canvas 重新擺到播放器目前的時間點。**File > Save As…** 才會把修改寫進 `.puppet` 檔。

一次處理多個關鍵點：

- 在空白處拖曳可框選關鍵點。參數很多時，**篩選軌道…** 可以縮小 **Track** 清單。
- **複製關鍵影格** 與 **貼上到…** 把選取的關鍵點複製到同一軌或另一軌的其他時間；**移動…** 平移它們的時間與數值；**縮放時間…** 拉長或壓縮它們的間距。
- **吸附** 在拖曳、移動與貼上時把時間對齊到 1/30 秒、1/60 秒或 0.1 秒。
- **切線** 把選取關鍵點的曲線設成 `linear`、`smooth`、`flat` 或 `stepped`。
- 動作有聲音時，波形會畫在關鍵點後面，方便把嘴型關鍵點對齊音節。

不會造成任何改變的操作（例如沒有選取關鍵點）會在圖表下方說明，動作維持原樣。對話框關閉後，每次編輯都能用 **Edit > Undo** 復原。

### 2.3 手動 keyframe 編輯（不錄 take）

Puppet 分頁沒有建立新動作用的 keyframe 編輯器。不靠即時表演也想做出動作：

1. 打開 **Output > Record motion**，自己拖 **Parameters** 擺放欄的滑桿 — 滑桿變化跟其他即時輸入一樣會被錄下。
2. 停止錄製，再用 **Edit > Edit motion…** 調整關鍵點（見 2.2）。
3. 要精準的 keyframe，就直接手寫 `.puppet` zip 裡的 `motions/<name>.json`，並把名稱加進 `puppet.json` 的 `motions`（見 [`FORMAT.md`](rigora/puppet/FORMAT.md)）。

每個滑桿旁的 **Set key** 按鈕是綁骨用的工具，不是動作 keyframe：它把每個變形器目前的 form 存成該參數在滑桿目前值的 key。**Edit > Add Parameter** 會新增一個 `ParamN` 滑桿（−1 到 1）供你打 key。

Parameter blends — 在兩個以上參數構成的網格上替變形器 form 打 key，例如用 `ParamAngleX × ParamAngleY` 在 2D 網格上控制頭部方向 — 從 `puppet.json` 的 `parameter_blends` 讀取；Puppet 分頁沒有編輯它的介面。

### 2.4 輸出

| 動作 | 輸出 |
|---|---|
| **Output > Capture frame…** | 把目前 frame 存成透明背景的單張 PNG。適合做縮圖 / 靜態頭像。 |
| **Output > Record…** | 先選 GIF / WebM / MP4 檔，接著用 `imageio` 以 30 fps 寫入影格，直到你再次切換關閉；codec 依副檔名決定。工具列按鈕就是同一個 toggle。 |
| **Output > Export all motions…** | 選資料夾跟容器格式（`.mp4`、`.gif` 或 `.webm`）；每個動作從頭播放並錄滿它的長度，存成 `<motion-name>.<ext>`。適合批次產出反應 clip、idle loop 等。 |
| **Output > Export animation…** | 離線逐格渲染一個動作或合成，不受螢幕更新率影響。可選 PNG 序列、GIF、MP4 或 WebM，以及尺寸、幀率、時間範圍、透明背景（PNG 與 WebM 保留 alpha），並先讓物理預熱，讓頭髮在第一格就已穩定。影片可以帶動作的聲音。匯出會排進佇列並顯示每個工作的進度；取消或失敗的匯出不會留下半成品，按 **重試** 可以再跑一次。檔案已存在時預設保留，除非你選擇覆寫或改名。 |

錄影用跟串流一樣的**角色獨立 off-screen render**，所以你不用事後 crop 掉外殼。GIF / WebM / MP4 的影格依文件長寬比縮進長邊 1080 px，背景為白色（這些格式不帶 alpha），每邊取 16 的倍數。PNG 擷取保留文件尺寸，長邊上限 4096 px。

### 2.5 動作配音

一個動作可以攜帶 `sound_path` — 一個 WAV 檔的絕對路徑。動作開始播放時聲音跟著播放並與動作同步：拖動時間軸時聲音跳到同一時間，循環動作每圈重新播放聲音，播放與聲音偏差超過 80 毫秒時動作會跟著聲音的時鐘走。**Pause** 跟 **Stop** 會停止聲音。把 Cubism `.model3.json` 疊加到已開啟的 rig（見*匯入 rig*）時，會從動作項目的 `Sound` 欄位填入；**Live > 從音訊檔對嘴…** 則會以一個 WAV 為中心建立新動作：嘴巴（`ParamMouthOpenY`）隨它的音量張開，而這個 WAV 就是動作的聲音。選項可以設定關鍵點速率、嘴巴比聲音提前多少（預設 40 毫秒，看起來最同步），以及讓字與字之間閉嘴的靜音閘。其他動作仍要編輯 `.puppet` zip 內的 `motions/<name>.json` — Puppet 分頁沒有設定它的欄位。WAV 檔本身不會存進 `.puppet`。**驗證** 會列出聲音檔不存在的動作，**File > 重新連結聲音…** 會在你選的資料夾裡依檔名尋找，並以一個可復原的步驟更新路徑。

如果沒裝 `PySide6.QtMultimedia`，音訊優雅停用，動作的視覺軌仍然會播。

### 2.6 用合成編排動作

合成把幾個動作放在同一條時間軸上一起播放 — 例如身體揮手的同時臉在笑 — 而不必修改動作本身。開啟 **Edit > 合成…**：

1. **新增** 建立一個合成，設定 **長度（秒）**。按 F2 改名。
2. 加入圖層。圖層是 **override**（依強度取代下層設定的值）或 **additive**（把自己的動作疊加上去）。每個圖層可設權重或靜音。
3. 選一個圖層並加入片段：選動作、開始時間、可選的動作內偏移與長度、循環、淡入淡出、權重與靜音。同一圖層內，淡入中的片段會與前一個片段交叉淡化。
4. **預覽** 在 canvas 上播放合成，不會修改 rig。問題（缺少的動作、重複的圖層名稱、負的時間）會列在表格下方，修正前對話框不會儲存。
5. **OK** 以一個可復原步驟儲存合成。**儲存並烘焙為動作** 會另外把選取的合成加成一般動作，可以編輯、讓 hit area 播放，或給不支援合成的程式使用。

**Output > Export animation…** 也可以選合成。合成會存進 `.puppet` 檔（見 [`FORMAT.md`](rigora/puppet/FORMAT.md#composition)）。

---

## Part 3 — 桌面角色

**Desktop Pet** 分頁把 rig 放到桌面上。它的 **角色** 分頁可以同時執行多個角色，每個都有自己的 rig、腳本與設定；停止其中一個不影響其他角色，配置會記住誰在哪裡執行。腳本可以包含行為規則 — 點擊、拖放、熱鍵、音樂節拍與計時，搭配條件、冷卻與優先順序 — 腳本編輯器會在執行前檢查並預覽。螢幕被拔除、縮放改變或電腦喚醒時，角色會回到看得見的位置；沒有動靜時以 15 fps 重繪，隱藏時停止重繪。選用的本機 LLM 可以產生新台詞，但它的回覆只能觸發角色自己的動作與表情。

[桌面角色指南](docs/desktop-companions.md)（英文）涵蓋以上所有內容與完整的事件、動作清單；[範例](examples/README.md)（英文）附有現成的行為腳本。

---

## 匯入 rig

### 從 PNG

**File > Import PNG…** 先詢問網格的格子大小（預設 64 px；越小網格越密），再對影像跑 `auto_mesh`：

- 用正方形格子鋪滿影像，完全透明的格子全部丟掉
- 預先設定 Cubism 標準參數目錄（`ParamAngleX/Y/Z`、`ParamEyeLOpen/ROpen`、`ParamMouthOpenY`、`ParamBreath` …）
- 產生單一 drawable、還沒有變形器的 rig — 從 **Edit** 選單加入變形器

適合：快速 prototype、單張無分層的角色圖。

### 從 PSD

**File > Import PSD…** 把每個可見、非空的圖層變成獨立 drawable — 一個裁到圖層不透明範圍的四邊形，依圖層順序疊放 — 每個圖層群組變成一個 Part。接著預先設定標準參數目錄，再依圖層名稱自動綁骨：

- 名稱含左右與開閉狀態的眼睛圖層（`eye_l_open`、`EyeRClose` …）跟著 `ParamEyeLOpen` / `ParamEyeROpen` 淡入淡出，所以 Auto-blink 會切換它們
- 嘴巴圖層（`mouth_open`、`mouth_close`、`mouth_a` … `mouth_o`）跟著 `ParamMouthOpenY` 跟 `ParamMouthForm` 淡入淡出，所以 Mic lip-sync 會切換它們
- `head` / `face` 圖層共用一個以 `ParamAngleZ` 打 key（±15°）的旋轉變形器
- `hair` / `bang` / `fringe` 圖層共用一個 warp 變形器，外加一條從 `ParamAngleX` 到 `ParamHairFront` 的物理鏈；warp 以 `ParamHairFront` 打 key，髮尾會左右擺動

其他圖層（身體、手臂、衣服）不會加任何變形器。

適合：美術提供的多圖層角色檔。

匯入前會先開 **匯入預覽**：列出每個圖層的順序（上層在前）、群組、狀態、drawable id、尺寸、位置、不透明度、混合、遮色片與剪裁，以及與 PSD 的所有差異，分成「阻擋匯入」「影響結果」「說明」三級。按取消不會改動目前文件。PSD 功能對應如下：

| PSD 功能 | 匯入後 |
| --- | --- |
| 圖層群組、巢狀群組 | Part、子 Part；隱藏群組與群組不透明度會保留 |
| 正常／色彩增值／線性加亮 | `normal`／`multiply`／`additive` |
| 其他混合模式 | 以 `normal` 繪製（列入差異） |
| 剪裁遮色片 | 對基底圖層網格設 `clip_mask` — 用的是它的 alpha 外框，不是逐像素（列入差異） |
| 圖層遮色片、向量遮色片、填滿不透明度、圖層效果、調整圖層 | 不套用（列入差異） |
| 文字、智慧型物件、填滿圖層 | 以檔案內儲存的像素匯入（列入差異） |
| 隱藏或空白圖層、剪裁到隱藏基底的圖層 | 略過（列入差異） |
| 名稱含 `A-Z a-z 0-9 _ -` 以外字元或重複 | 以清理後的唯一 id 儲存（列入差異） |

### 從 PSD 更新素材

**File > Update art from PSD…** 把重新匯出的 PSD 套到目前的 rig，不必重新綁定。每個 drawable 以相同 id（全新匯入時由圖層名稱產生的 id）對應圖層；對話框逐列顯示變更、目前與新的範圍、問題及動作：

- **取代像素，保留網格**（有變更時的預設）：保留頂點、骨骼權重、morph、變形器與動作，只替換現有網格下的像素。新圖層比網格大時會標示「新素材超出網格範圍」。
- **重建網格**：依新素材建立新的四邊形；該 drawable 的骨骼權重與頂點 morph 會丟棄，數量顯示在狀態列。
- **新增圖元**（新圖層）：插在 PSD 中下方圖層的正上方，並加入所屬群組的 Part。
- **保留／隱藏**：用於 PSD 已沒有的 drawable。

位置相同、一個消失一個新增的組合會標成「可能是重新命名的圖層」，預設不新增。畫布尺寸與 rig 不同時會阻擋更新。UV 不是單純矩形或共用貼圖的 drawable 只能重建或略過。整次更新是一個 Undo 步驟。

### 重新連結貼圖

開啟缺少貼圖的檔案時，狀態列會提示。**File > Relink textures…** 列出缺少或無法讀取的貼圖、使用它的 drawable 與預期尺寸。*搜尋資料夾…* 會找同名檔案（任何影像格式）；*選擇影像…* 可手動指定。影像沿用既有 UV，尺寸不同時會延展到網格上並註記。重新連結是一個 Undo 步驟。

### 從 Cubism `.moc3`

**File > Import Cubism…** 會先顯示匯入模式說明（勾 *Don't show this again* 以後就跳過）。它同時接受 `.moc3` 跟對應的 `.model3.json` manifest — 不管選哪個、只要工作區還沒開 rig，匯入器都會跑完整 sample-and-reconstruct 轉換：

1. 透過 Cubism Native SDK 載入 `.moc3`（使用者自備 — 把 SDK 解壓到 `<cwd>/sdk/` 或設 `CUBISM_CORE_DLL` 環境變數指向 DLL）。直接挑 `.moc3` 也可以，只要旁邊有同名 `.model3.json`，工作區會自動找到 manifest。
2. 把每個 Cubism 參數從 min 掃到 max，記錄每個 drawable 的形變頂點。
3. 同時擷取參數驅動的 *visibility* 切換 — 比耶 / 捂臉 / 哭等手勢切換都能完整保留。
4. 把 `.model3.json` bundle 裡既有的 motion / expression / physics / hit-area / display-name 全部 fold 進 puppet。bundle 的 `motions/` 資料夾裡、manifest 沒列到的動作會歸入 `Idle` 群組。

轉換好的 rig 會開在 canvas 上；用 **File > Save As…** 寫成自包含的 `.puppet` zip，不需要附 Cubism SDK 就能散布（SDK 永不打包 — Live2D 的 Free Material License 規定）。

> **疊加到既有 rig**：如果已經開了一個 `.puppet`，這時候挑 `.model3.json` 會把它的 JSON 部分疊到目前文件上：名稱或 id 還不存在的 motions、expressions、physics、hit areas、pose groups，再加上 display names — 適合把 Cubism 動作庫嫁接到自己手繪的 PSD rig。`.moc3` 路徑永遠新建文件；要往既有 rig 加動作，挑 `.model3.json` 或單檔 `.motion3.json` / `.exp3.json` / `.physics3.json` / `.pose3.json` / `.cdi3.json`。

選 `.moc3` 或 `.model3.json` 時會先開 **Cubism 匯入預覽**。它只讀 JSON 檔、不載入 Cubism SDK，逐項列出參照檔案是否存在，以及差異：runtime 不支援的動作曲線（`PartOpacity`、`Model`）、缺少的聲音、user data、完整轉換不讀取的 pose 群組、keyform 取樣近似；疊加時另列因同名而略過的動作或表情、找不到對應 drawable 的 hit area，以及 rig 沒有的參數。缺 `.moc3`、缺 Cubism Core 程式庫，或缺少會讓疊加中止的附屬檔時，**匯入**按鈕會停用。

---

## 進階功能

### 參數

每個會動的值都是 *parameter*，有 min、max、default。參數的每個 `key` 存的是某個參數值下的變形器 form；runtime 在目前值兩側的兩個 key 之間線性內插，超出頭尾就維持端點 key。Cubism 標準 id 參考 `rigora/puppet/standard_params.py`。

### 變形器

- **Rotation** — 錨點 + 角度，套用在變形器自己 `drawables` 清單裡的 drawable。`parent` 只決定順序：父節點先於子節點執行，但父節點的旋轉只移動它自己列出的 drawable，子節點的錨點也不會跟著父節點動。要讓 body lean 帶著 head + arms 一起動，就把它們也列進身體的變形器。
- **Warp** — 蓋在 `bounds` 矩形上的 `rows × cols` 雙線性網格；範圍內的頂點跟著網格走，範圍外的不動。用於臉頰擠壓、衣服皺褶、頭髮擺動。
- **Bone rotation** — `bone_rotation` 變形器（骨頭 id + 錨點 + 角度）替帶有 `bone_weights` 的 drawable 做蒙皮：每個頂點依權重混合各骨頭的旋轉。骨頭之間同樣不會繼承旋轉。
- **Vertex morphs** — Cubism 式每 drawable 的 delta 陣列，在參數預設值跟極值之間做線性混合。`.moc3` 轉換器產生這個。

### Pose groups

互斥的 drawable 可見度。同時只顯示群組裡一個成員：在 **Pose** 擺放欄挑要顯示的成員，其他成員隱藏。用於武器切換、嘴型變體、costume 切換。預設顯示群組的第一個成員；成員本身的 `visible` 旗標不起作用。

### 物理

Verlet pendulum 鏈用於頭髮 / 衣物 / 緞帶。*輸入參數*（例如 `ParamAngleX`）讓鏈錨點橫向移動；重力 + 阻尼 + per-particle 彈簧把鏈拉回靜止；尖端橫向位移映射回 *輸出參數*（例如 `ParamHairFront`），限制在 −1…1。靜止時輸出等於輸入，所以輸入一變化，鏈就會延遲跟上並甩過頭，看起來就是擺動。

Puppet 分頁顯示中且 rig 有物理鏈時，canvas 用自己的時鐘每秒推進約 60 次，所以輸入停下後鏈還會繼續擺。物理鏈的輸出會蓋過滑桿、動作或表情在該參數上的值。**Reset to rest** 會把所有鏈彈回靜止。

物理鏈來自 Cubism 匯入（`.physics3.json`）、PSD 自動綁骨的頭髮規則、部件範本，或 **Tools > Physics chains…**。這個對話框可以編輯輸入與輸出參數、粒子數、長度、剛性、阻尼與重力，並能儲存、重用預設。它會警告無法運作的鏈（缺少參數、輸出同時是輸入）以及會讓輸出飽和的設定；每次修改都是一個 Undo 步驟。物理鏈存在 `.puppet` 檔裡的 `physics.json`。

### 編輯網格與權重

開啟 **Mesh > Edit mesh** 之後：

- 點頂點選取，**Shift**＋點加入選取，在空白處拖曳可框選（按住 **Shift** 加入選取）；
- 拖曳已選的頂點會移動整組選取；
- **Lock selected vertices** 讓這些頂點在拖曳其他頂點時保持不動，**Unlock all vertices** 解除；
- **Show weights…** 以顏色顯示某根骨骼的權重；**Smooth weights**、**Normalize weights** 與 **Mirror weights left → right** 編輯選取頂點的骨骼權重；
- **Mirror selected vertices** 與 **Delete selected vertices…** 會改變網格；刪除前會列出受影響的三角形、權重與 morph。

每次編輯都是一個 Undo 步驟。

### 整理變形器與參數

**Bones** 擺放欄把變形器顯示成樹狀。可以依名稱搜尋，把一列拖到另一列上改變父層（拖到空白處則脫離父層），用 **Up** / **Down** 移動順序，**Lock** 讓變形器不能被改父層或改順序，**Hide** 把它從清單隱藏（**Show hidden** 會再顯示）。出現父層循環時會警告並列出相關的變形器。

**Parameters** 擺放欄把滑桿分成 Head、Eyes、Mouth、Body、Hair 與 Other 群組，**Filter parameters…** 可縮小清單。每個滑桿的 **⋯** 選單有 **Edit range…**（會讓既有 key、blend key 或表情值落到範圍外的範圍會被拒絕）與 **Preview key forms**（逐一預覽該參數的 key）。**Reset all** 把所有滑桿還原成預設值。

### Rig doctor 與部件範本

**Tools > Rig doctor…** 檢查 rig，並依類別整理結果：網格問題（零面積或損壞的三角形、重複或未使用的頂點）、加總不等於 1 的骨骼權重、缺少鏡像對應的左右圖元、自動綁骨會加上的標準綁定（例如頭部傾斜、頭髮擺動），以及 **Validate** 會回報的所有問題。選取項目可預覽每項修正，再一起套用成一個 Undo 步驟。命令列可用 `rigora rig-doctor` 執行相同檢查。

**Tools > Part templates…** 為你選的圖元加上現成綁定：**眨眼**、**嘴型**、**轉頭**（已有頭部傾斜時會沿用，不會再疊一層）與 **擺動**。對話框會列出每個範本要建立的內容，並在與既有綁定重疊時警告。

### 表情

參數覆寫堆疊，疊在滑桿 / 動作值上。模式：`additive`（最終 = base + value）、`multiply`（最終 = base × value）、`overwrite`（最終 = value）。從 **Expressions** 擺放欄切換；啟用中的表情依開啟順序套用。

用於瞬時情緒：*smile*、*surprised*、*angry*。內附的 Imeru rig 帶 7 個表情（`smile` / `happy` / `surprised` / `sad` / `angry` / `blush` / `sleepy`）。

### Hit areas

命名的點擊區域。hit area 的範圍是它所列 drawable 在目前（已變形）位置的外框；在範圍內按左鍵（**Edit mesh** 關閉時）會執行它的動作。它的 `motion` 指定動作群組 — 從該群組隨機播一個動作（`TapHead` 會挑一個 `TapHead` 動作）；沒有動作屬於該群組時，播放同名的動作。它的 `expression` 會切換該表情（點 body → 切換 `surprised`）。範圍重疊時，含最前面 drawable 的那個勝出。

內附的 Imeru rig 定義了兩個：點她的頭（`Head`）播放 `TapHead` 動作，點她的身體（`Body`）播放 `TapBody` 動作。用 **File > Import Cubism…** 轉換的 rig 會帶入模型的 `HitAreas`，但只有範圍、沒有動作；在 `puppet.json` 的 `hit_areas` 清單替它們加上 `motion` 或 `expression` 才會有反應。Puppet 分頁沒有 hit area 編輯器。

---

## 選用依賴

Puppet 分頁的核心（渲染、參數系統、動作播放、PNG / PSD / Cubism 匯入）跑在預設 `requirements.txt` 上。更重的依賴用 `try / except` 包起來，缺了也不會壞其他功能。

| 功能 | 選用依賴 | 安裝 |
|---|---|---|
| Webcam 臉部追蹤 | `opencv-python` + `mediapipe` | `pip install opencv-python mediapipe` |
| 麥克風對嘴 | `sounddevice` | `pip install sounddevice` |
| 虛擬攝影機輸出 | `pyvirtualcam` + 平台驅動 | `pip install pyvirtualcam`，見上面 Path A |
| NDI 輸出 | `ndi-python` + NDI runtime + NDI SDK（編譯時用） | 見上面 Path B |
| Cubism `.moc3` 匯入 | 使用者自備 Cubism Native SDK DLL | <https://www.live2d.com/sdk/about/> |
| 動作音訊播放 | `PySide6.QtMultimedia` | 通常跟著 PySide6；缺的話從平台的 QtMultimedia 包補 |
| 匯出 GIF／MP4／WebM 動畫 | `imageio` ＋ `imageio-ffmpeg`（在 `gui` extra 中） | `pip install "rigora[gui]"`；PNG 序列兩者都不需要 |
| VTS API 輸入 | `PySide6.QtWebSockets` | 隨 PySide6 提供 |
| 桌面角色全域熱鍵 | `pynput` | `pip install "rigora[hotkeys]"` |
| 桌面角色音樂節奏 | `sounddevice` 與 WASAPI loopback 裝置（Windows） | `pip install "rigora[lipsync]"` |
| 桌面角色 LLM 對話 | 本機 [Ollama](https://ollama.com) 伺服器（或提供相同 API 的 HTTPS 端點） | 另行安裝；Rigora 不會下載任何東西 |

切換一個缺少 Python 套件的功能時，會開啟該套件的安裝程式，裝好後自動開啟功能。套件已安裝但裝置或 runtime 失敗（沒有麥克風、沒有虛擬攝影機驅動、沒有 NDI runtime）時，toggle 會自動取消勾，狀態列會說明原因。**File > Install dependencies…** 可以一次裝齊所有 Python 選用包；Cubism SDK 跟 NDI runtime 因為授權需要手動裝。

---

## 鍵盤快捷鍵

| 按鍵 | 動作 |
|---|---|
| **Ctrl+S** | 儲存（第一次會詢問檔名） |
| **Ctrl+Z** / **Ctrl+Shift+Z** | 復原／重做上一個 rig 編輯 |
| **F2** | 重新命名選取的合成（合成對話框） |
| **Shift**＋點擊或拖曳 | 加入頂點選取（Edit mesh） |

其他指令都在選單與工具列上。Canvas 接受這些滑鼠操作：

| 操作 | 動作 |
|---|---|
| **中鍵拖曳** | 平移 |
| **滑鼠滾輪** | 縮放（以游標為中心）；**Tools > Fit to Window** 重新貼合視窗 |
| **左鍵** | 觸發游標下的 hit area；**Edit mesh** 開啟時選取游標 8 px 內的頂點（最前面的 drawable 優先），在空白處則開始框選 |
| **左鍵拖曳** | **Edit mesh** 開啟時移動選取的頂點（鎖定的頂點不動） |
| **右鍵** | 清除 bone 選取 overlay |

---

## 疑難排解

### 「Webcam tracking 開了什麼都沒發生」

預覽視窗會彈出顯示攝影機畫面；如果畫面裡沒有臉，沒有參數會被驅動。預覽視窗的狀態列顯示 *"No face in frame"*。移到鏡頭前或改善光線。

如果預覽是黑的：攝影機被其他 app 佔用、或 OS 拒絕了攝影機存取。macOS 首次使用會要求權限 — 檢查「系統設定 → 隱私權與安全性 → 攝影機」。

### 「攝影機追蹤一直說攝影機中斷」

攝影機停止傳送畫面 — 通常是被拔除或被其他程式佔用。Rigora 會在 1、2、4、8、15 秒後重試，之後停下來等候；**Output > 即時狀態…** 會顯示倒數，**重試裝置** 會立即再試。如果存取被拒，請先在系統隱私權設定允許攝影機。臉部模型下載失敗不會自動重試：確認網路後按 **重試裝置**。

### 「追蹤程式送來的值沒有作用」

開啟 **Live > 輸入來源…**：這個參數多半由其他來源控制。正在拖的滑桿、播放中的動作與其他外掛都比 VTS 外掛優先。每秒送超過 120 個請求的外掛會收到錯誤 6000；被其他外掛佔用的參數會回錯誤 454。見 [VTS API 支援範圍](docs/vts-api-support.md)。

### 「匯出動畫說缺少能力」

PNG 序列需要有 OpenGL 的桌面工作階段；GIF 需要 `imageio`；MP4 與 WebM 需要 `imageio-ffmpeg`。在命令列上會是退出碼 4、錯誤代碼 `capability_missing`。取消或失敗的匯出絕不會留下半成品。

### 「OBS 看到洋紅色背景」

設計使然 — 見上面 Path A。在 OBS 的 *Video Capture Device* 來源加 Color Key filter、`Custom Color = #FF00FF`。

### 「ndi-python 安裝失敗、找不到 cmake」

`ndi-python` 從原始碼編。裝 CMake、Visual Studio C++ Build Tools、NDI SDK — 見 Path B 前置。不需要 NDI 的話用 Path A。

### 「動作播完 rig 卡在最後一個姿勢」

Motions 擺放欄的 **Loop** 關閉時，播到結尾的動作會停在最後一格，**Pause** 也會停在當下姿勢。**Stop** 會依動作的淡出時間（動作沒設定時為 0.5 秒）把動作的參數緩緩帶回預設值。工具列的 **Reset to rest** 一次把所有參數、表情、pose group 跟物理鏈還原。

### 「桌面角色的腳本沒有載入」

行為規則有問題的腳本會整份被拒絕，角色會繼續使用原本的腳本。開啟 **Edit script… > Behaviors** 並按 **Check**：每個問題都會標出位置，例如 `rules[2].do[0]: unknown action 'shout'`。

### Cubism 轉換器把相機顯示成「多一隻手」

轉換來的 Cubism rig 上的比耶 / 照相 / 捂臉手勢是用 Cubism 動態可見度旗標驅動的。轉換器把這些切換存成 `opacity_keys` 曲線，所以每個道具只在對應參數拉起時出現。如果轉換出來的 `.puppet` 一直顯示這些道具，代表它的 drawable 缺少這些曲線 — 從 **File > Import Cubism…** 重新轉換並儲存結果。

---

## 檔案格式參考

`.puppet` 是 zip 容器、含 JSON manifest 跟 PNG 紋理。完整規格見 [`rigora/puppet/FORMAT.md`](rigora/puppet/FORMAT.md)。

內附 demo rig：[`examples/puppet/imeru.puppet`](examples/puppet/imeru.puppet)，由 `examples/puppet/imeru/build.py` 重新產生（見 [`examples/puppet/README.md`](examples/puppet/README.md)）。
