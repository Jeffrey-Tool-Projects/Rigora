# Third-Party Licenses / 第三方授權聲明

---

Rigora is licensed under the MIT License. See `LICENSE` for details.

Rigora 以 MIT 授權條款發佈，詳見 `LICENSE` 檔案。

This list covers the third-party software Rigora uses, in three groups:

1. **Bundled** — inside the Windows portable build (`Rigora-windows-x64.zip`),
   and installed as dependencies of the Python package.
2. **Installed on demand** — optional packages a user installs (or the
   optional-dependency installer adds) to unlock a feature.
3. **Not bundled / user-supplied** — software Rigora works with but never
   redistributes.

本清單分三類：(1) 隨 Windows 可攜版與 Python 套件一同提供；(2) 使用者為了特定功能另行安裝的選用套件；
(3) Rigora 會配合使用但不散布、需使用者自行取得的軟體。

License identifiers below come from each package's published metadata
(checked 2026-11-12). The Windows build also copies each bundled package's
own license files into its `licenses/` folder.

以下授權標示取自各套件發布的中繼資料（2026-11-12 核對）。Windows 版另會把每個內附套件的授權檔複製到 `licenses/` 資料夾。

## 1. Bundled

### Python

- **License / 授權:** Python Software Foundation License 2.0
- **Website / 網站:** https://www.python.org
- The Windows build embeds the CPython runtime; its license is copied to
  `licenses/Python/LICENSE.txt`. / Windows 版內嵌 CPython 執行期，授權複製於 `licenses/Python/LICENSE.txt`。

### PySide6 and shiboken6

- **License / 授權:** LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only
- **Website / 網站:** https://pyside.org
- **Source code / 原始碼:** https://code.qt.io/cgit/pyside/pyside-setup.git/

Rigora uses PySide6 under the terms of the **GNU Lesser General Public
License v3 (LGPLv3)**. PySide6 is dynamically linked and distributed as
separate shared libraries (`.dll` / `.so` / `.dylib`). You may replace
these libraries with a compatible version at any time.

Rigora 依據 **GNU 較寬鬆通用公共授權條款第 3 版（LGPLv3）** 使用 PySide6。
PySide6 以動態連結方式散布，作為獨立的共享函式庫（`.dll` / `.so` / `.dylib`）。
您可隨時將這些函式庫替換為相容的版本。

A copy of the LGPLv3 is available at https://www.gnu.org/licenses/lgpl-3.0.html.

LGPLv3 全文可於上述連結取得。

### Qt (via PySide6)

- **License / 授權:** LGPL-3.0-only
- **Website / 網站:** https://www.qt.io
- **Source code / 原始碼:** https://code.qt.io/cgit/qt/qtbase.git/

Qt libraries are redistributed as part of PySide6 under the LGPLv3.

Qt 函式庫作為 PySide6 的一部分，依據 LGPLv3 一同散布。

### NumPy

- **License / 授權:** BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0
- **Website / 網站:** https://numpy.org

### Pillow

- **License / 授權:** MIT-CMU (Historical Permission Notice and Disclaimer)
- **Website / 網站:** https://python-pillow.github.io

### PyOpenGL

- **License / 授權:** BSD-3-Clause
- **Website / 網站:** https://mcfletch.github.io/pyopengl/

### imageio

- **License / 授權:** BSD-2-Clause
- **Website / 網站:** https://github.com/imageio/imageio

### imageio-ffmpeg

- **License / 授權:** BSD-2-Clause (Python wrapper) + LGPL-2.1 / GPL-2.0 (bundled FFmpeg binary)
- **Website / 網站:** https://github.com/imageio/imageio-ffmpeg
- **FFmpeg source / FFmpeg 原始碼:** https://ffmpeg.org/download.html

`imageio-ffmpeg` ships a precompiled **FFmpeg** binary that Rigora uses to
export MP4, WebM and GIF animations. The default FFmpeg build is LGPL-2.1;
if the user replaces it with a GPL-licensed build, the GPL applies.
Replacement is supported via the `IMAGEIO_FFMPEG_EXE` environment variable.

`imageio-ffmpeg` 內附預編譯的 **FFmpeg** 二進位，Rigora 用它匯出 MP4、WebM 與 GIF 動畫。
預設 FFmpeg 構建為 LGPL-2.1；若使用者替換為 GPL 構建，則套用 GPL。可透過 `IMAGEIO_FFMPEG_EXE` 環境變數指定替換的 FFmpeg。

### Nuitka (Windows build only)

- **License / 授權:** Apache-2.0
- **Website / 網站:** https://nuitka.net
- Nuitka compiles the Windows build and includes its runtime support code;
  the compiled program is not covered by Nuitka's license. / Nuitka 編譯 Windows 版並附帶其執行期支援程式碼；編譯後的程式本身不受 Nuitka 授權約束。

## 2. Installed on demand (optional)

These packages are **not** in the base install. They are added when the user
enables a feature that needs them, either with `pip install "rigora[...]"` or
through **File > Install dependencies…**.

以下套件**不在**基本安裝中，使用者啟用需要它們的功能時才安裝（`pip install "rigora[...]"` 或 **File > Install dependencies…**）。

### OpenCV (opencv-python)

- **License / 授權:** Apache-2.0
- **Website / 網站:** https://opencv.org
- **Feature / 功能:** webcam tracking (camera capture) / 攝影機追蹤（擷取畫面）

### MediaPipe

- **License / 授權:** Apache-2.0
- **Website / 網站:** https://github.com/google-ai-edge/mediapipe
- **Feature / 功能:** webcam face landmarks / 攝影機臉部特徵點

On first use Rigora downloads MediaPipe's `face_landmarker.task` model from
Google's model storage, checks its SHA-256 and keeps it in the Rigora data
folder. The model is covered by its own model card's terms.

首次使用時 Rigora 會從 Google 的模型儲存位置下載 MediaPipe 的 `face_landmarker.task`，核對 SHA-256 後存放在 Rigora 資料夾。該模型依其 model card 條款使用。

### sounddevice

- **License / 授權:** MIT
- **Website / 網站:** https://github.com/spatialaudio/python-sounddevice
- **Feature / 功能:** microphone lip-sync, desktop pet music rhythm / 麥克風對嘴、桌面角色音樂節奏

`sounddevice` is a Python binding for the PortAudio library (MIT), which its
wheels include.

`sounddevice` 是 PortAudio（MIT）的 Python 綁定，其 wheel 內含 PortAudio。

### pyvirtualcam

- **License / 授權:** GPL-2.0
- **Website / 網站:** https://github.com/letmaik/pyvirtualcam
- **Feature / 功能:** virtual-camera output / 虛擬攝影機輸出

`pyvirtualcam` is GPL-2.0 and is never bundled; installing it is the user's
choice. It needs a separately installed virtual-camera driver (such as OBS
Virtual Camera), which has its own license.

`pyvirtualcam` 為 GPL-2.0，從不隨 Rigora 提供，由使用者自行選擇安裝。它需要另行安裝的虛擬攝影機驅動（例如 OBS Virtual Camera），該驅動依其自身授權。

### NDI Python (ndi-python)

- **License / 授權:** MIT (Python wrapper)
- **Website / 網站:** https://github.com/buresu/ndi-python
- **Feature / 功能:** NDI® output / NDI® 輸出

The underlying **NDI® SDK and runtime by Vizrt** are proprietary and governed
by their own license at https://ndi.video/legal/ndi-sdk-license-agreement/;
users install them separately.

底層的 **Vizrt NDI® SDK 與執行期**為專有軟體，依其授權（https://ndi.video/legal/ndi-sdk-license-agreement/）規範，需使用者另行安裝。

### pynput

- **License / 授權:** LGPL-3.0
- **Website / 網站:** https://github.com/moses-palmer/pynput
- **Feature / 功能:** desktop pet global hotkeys / 桌面角色全域熱鍵

## 3. Not bundled / user-supplied

Rigora never redistributes the following. Users obtain them under their own
terms.

下列軟體 Rigora 從不散布，使用者需依各自條款取得。

### Live2D Cubism Native SDK

- **License / 授權:** Live2D Cubism SDK license (see the official site)
- **Website / 網站:** https://www.live2d.com/sdk/license/
- **Integration / 整合方式:** ctypes binding in `rigora/puppet/cubism_native_bridge.py`,
  which looks for `Live2DCubismCore` in `<cwd>/sdk/` and the
  `CUBISM_CORE_DLL` environment variable.

The Cubism SDK may not be redistributed as part of another product. Users who
want to convert `.moc3` models download it themselves and accept Live2D's
terms. Opening and playing `.puppet` files never needs it.

Cubism SDK 不得作為其他產品的一部分散布。要轉換 `.moc3` 模型的使用者需自行下載並同意 Live2D 條款。開啟與播放 `.puppet` 檔從不需要它。

### Local LLM servers and models

Desktop pet dialogue talks to a server the user runs, by default
[Ollama](https://ollama.com) (MIT) on `localhost`. Rigora downloads no model;
each model's license is chosen by the user.

桌面角色對話連到使用者自行執行的伺服器，預設為本機的 [Ollama](https://ollama.com)（MIT）。Rigora 不下載任何模型，模型授權由使用者自行選擇。
