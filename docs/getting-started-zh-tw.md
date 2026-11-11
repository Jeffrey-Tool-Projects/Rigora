---
title: 繁體中文入門
description: 使用 Windows 可攜版或從原始碼安裝，開啟 Rigora 並播放內附 Imeru 的動畫。
permalink: /getting-started-zh-tw/
lang: zh-Hant
---

## Windows 免安裝版

64 位元 Windows 10／11 可使用包含 Python 的可攜版。下載並完整解壓縮
`Rigora-windows-x64.zip`，再執行 `Rigora` 資料夾內的 `Rigora.exe`。
請保留旁邊的 `_internal` 資料夾，不要只移動 EXE。

官方下載連結、校驗碼、未簽章提醒及選用功能限制，請見
[Windows 使用說明]({{ '/windows/' | relative_url }}#traditional-chinese)。
需要開發環境、選用套件或其他平台時，請依下方步驟從原始碼安裝。

## 從原始碼安裝
{: #source-install }

準備 Python 3.11 以上版本與 Git。編輯器需要可使用 OpenGL 的桌面環境。
以下指令從公開原始碼安裝，不依賴 PyPI 發行版本。

在 Windows PowerShell 執行：

```powershell
git clone https://github.com/Jeffrey-Tool-Projects/Rigora.git
cd Rigora
python -m venv .venv
.venv\Scripts\python.exe -m pip install ".[gui]"
.venv\Scripts\python.exe -m rigora
```

macOS 或 Linux 請以 `python3 -m venv .venv` 建立環境，並將後兩行的
`.venv\Scripts\python.exe` 改為 `.venv/bin/python`。

安裝與啟動都使用同一個環境的 Python。IDE 的專案解譯器也應指向該路徑。

## 播放第一段動畫

1. 在編輯器開啟 **File > Examples > Imeru**。
2. 在下方 **Motions** 面板選擇一段動作。
3. 調整 **Parameters** 面板的參數，觀察角色變化。
4. 選擇 **Reset to rest** 回到預設姿勢。
5. 修改內附範例前，使用 **Save As** 另存工作副本。

啟動時也可以直接指定模型：

```powershell
.venv\Scripts\python.exe -m rigora path/to/model.puppet
```

## 加入攝影機或麥克風

在專案根目錄安裝所需的選用套件：

```powershell
.venv\Scripts\python.exe -m pip install ".[gui,webcam,lipsync]"
```

首次使用攝影機追蹤會下載臉部特徵模型。裝置是否可用仍取決於作業系統權限。
虛擬攝影機、NDI 與全域快捷鍵的套件請見[功能參考]({{ '/reference/' | relative_url }}#optional-features)。

## 遇到問題時

- 找不到 `rigora`：在專案根目錄重新執行安裝指令，確認安裝與啟動使用同一個 Python。
- 找不到 `PySide6` 或 `OpenGL`：確認已安裝 `.[gui]`。
- 視窗或畫布無法顯示：檢查桌面環境與顯示驅動程式；`offscreen` 測試模式不能代替原生 OpenGL。
- 攝影機或麥克風無法使用：確認選用套件已安裝，並檢查作業系統的裝置權限。

接著閱讀[完整繁體中文 Puppet 指南](https://github.com/Jeffrey-Tool-Projects/Rigora/blob/main/puppet_guide.zh-TW.md)，
了解直播、動畫輸出、匯入與快捷鍵。較長的指南也包含嵌入 Imervue 時的介面說明。
