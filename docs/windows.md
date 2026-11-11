---
title: Windows download
description: Run the portable Windows application without installing Python.
permalink: /windows/
---

[Download the latest release](https://github.com/Jeffrey-Tool-Projects/Rigora/releases/latest)
· [繁體中文說明](#traditional-chinese)

## Download and open Rigora

Use 64-bit Windows 10 version 1809 or later, or Windows 11, with a working
OpenGL graphics driver.
The portable build includes Python and the core GUI dependencies.

1. Open the [latest GitHub release](https://github.com/Jeffrey-Tool-Projects/Rigora/releases/latest).
2. Download `Rigora-windows-x64.zip` and `SHA256SUMS.txt` from **Assets**.
3. Verify the ZIP's checksum as described below.
4. Use **Extract All** to extract the complete ZIP to a writable folder.
5. Open the extracted `Rigora` folder and double-click `Rigora.exe`.

The extracted layout includes:

```text
Rigora/
  Rigora.exe
  _internal/
```

Keep the entire folder together. Do not run the executable inside the ZIP or
move `Rigora.exe` away from `_internal`. This is a portable application, not an
installer. You do not need to install Python or create a virtual environment.

## Open a character

Select **File > Examples > Imeru**, then play a motion in the **Motions** dock.
Use the editor's open action for your own `.puppet` document.

You can also pass a document path from PowerShell:

```powershell
& "C:\Apps\Rigora\Rigora.exe" "C:\Characters\my-model.puppet"
```

Replace both paths with your actual locations. The portable build includes the
core editor, the bundled Imeru example, and image, animation, and video export.

Webcam tracking, microphone lip-sync, virtual camera, NDI, and global hotkey
packages are not bundled. Use the
[source installation]({{ '/getting-started/' | relative_url }}#create-an-environment)
with the relevant [optional extras]({{ '/reference/' | relative_url }}#optional-features)
if you need those features. Do not assume installing packages into a separate
Python environment adds them to the executable.

## Verify the download

In the folder containing the downloaded ZIP, run:

```powershell
Get-FileHash .\Rigora-windows-x64.zip -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
```

Compare the reported hash with the entry for `Rigora-windows-x64.zip` in
`SHA256SUMS.txt`. They must match. Download both files from the same release on
the official repository. A matching checksum checks file integrity; it is not a
code-signing certificate.

The executable is unsigned, so Windows SmartScreen may show a warning. Check
the repository, release, and checksum before deciding whether to run it. Do not
disable antivirus protection to launch Rigora.

## Settings and updates

Settings and cached data are stored under `%LOCALAPPDATA%\Rigora` by default.
Your `.puppet` documents remain wherever you save them. The application's data
directory is separate from the extracted program folder.

To update, close Rigora and extract the new release into a new folder. Open the
new `Rigora.exe` after verifying the download. Keep your documents backed up;
replacing the program folder does not replace the application-data directory.

## Troubleshoot startup

| Symptom | Check |
| --- | --- |
| Missing DLL or `_internal` file | Extract the full ZIP again. Keep the executable and its companion files together. |
| Blank canvas or graphics error | Update the graphics driver and check OpenGL support in the current desktop session. |
| A camera, microphone, or output feature is unavailable | These optional packages are not included in the portable build. Use a source installation with the required extras. |
| No Windows asset on a release | Use a release that includes `Rigora-windows-x64.zip`, or install from source. GitHub's automatic source-code ZIP is not the application. |

Report persistent problems in
[GitHub Issues](https://github.com/Jeffrey-Tool-Projects/Rigora/issues), including
the release version, Windows version, and the error text. Startup exceptions are
recorded in `%LOCALAPPDATA%\Rigora\startup.log`.

## 繁體中文說明
{: #traditional-chinese }

Windows 可攜版適用於 64 位元 Windows 10 1809 以上版本或 Windows 11，包含 Python 與核心 GUI 相依套件，
不需另行安裝 Python。顯示驅動程式仍須支援 OpenGL。

1. 開啟[最新 GitHub Release](https://github.com/Jeffrey-Tool-Projects/Rigora/releases/latest)。
2. 在 **Assets** 下載 `Rigora-windows-x64.zip` 與同一版本的 `SHA256SUMS.txt`。
3. 使用上方 PowerShell 指令計算 ZIP 的 SHA-256，確認與校驗檔一致。
4. 將整份 ZIP 解壓縮到可寫入的資料夾。
5. 開啟解壓後的 `Rigora` 資料夾，執行 `Rigora.exe`。

請保留 `Rigora.exe` 與 `_internal` 的相對位置，不要只移動 EXE，也不要在 ZIP
內直接執行。這是可攜式資料夾，不是安裝程式。

啟動後選擇 **File > Examples > Imeru**，即可播放內附角色的動作。也可以開啟自己
的 `.puppet`，或依上方範例在命令列傳入模型路徑。

程式未做數位簽章，Windows SmartScreen 可能顯示警告。請先核對官方來源、版本及
校驗碼，再決定是否執行；不要為此關閉防毒。校驗碼確認檔案完整性，不能取代數位簽章。

設定與快取預設存於 `%LOCALAPPDATA%\Rigora`。更新時先關閉程式，再將新版完整解壓
到新資料夾。模型仍存於你選擇的位置，請自行保留備份。
若啟動時發生例外，請查看 `%LOCALAPPDATA%\Rigora\startup.log`，回報問題時附上錯誤內容。

可攜版包含核心編輯器、Imeru 及影像、動畫、影片輸出，不包含攝影機追蹤、麥克風、
虛擬攝影機、NDI 或全域快捷鍵的選用套件。需要這些功能時，請使用
[原始碼安裝方式]({{ '/getting-started-zh-tw/' | relative_url }}#source-install)，
並安裝對應套件。

## Test builds

Maintainers can run the
[Windows release workflow](https://github.com/Jeffrey-Tool-Projects/Rigora/actions/workflows/windows-release.yml)
manually to produce a build artifact. Manual runs do not publish a GitHub
release. Tags matching `v*` trigger the release workflow for versioned assets.
Use the release assets for normal downloads rather than an unreviewed test build.
