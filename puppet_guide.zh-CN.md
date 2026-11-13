# Puppet 指南 — 直播与动画制作

请在公开的 Rigora 源码 checkout 执行 `python -m pip install ".[gui]"`，再执行 `python -m rigora`。此处从源码安装，不依赖 PyPI 发布版本。本指南的编辑器也可在已安装 Rigora 的 Imervue Puppet 标签页使用。软件包示例由 `rigora.system.app_paths.examples_dir()` 定位；以下 `examples/` 路径指 Rigora 源码 checkout。

从"我想做 VTuber 风直播或短动画"走到"我已经在 OBS 上直播 / 我手上有一个 MP4 文件"的完整流程，用 Rigora 的 **Puppet** 标签完成。

两条路：

1. **直播** — 用鼠标 / 麦克风 / 摄像头驱动 puppet rig，把结果送进 OBS 推流或录制。
2. **动画制作** — 录一段 take、编辑动作时间轴、输出 GIF / MP4 / WebM。

两者共用同一个 rig 跟参数系统，差别只在输出端是直播虚拟镜头还是磁盘上的文件。

---

## 目录

- [快速开始](#快速开始)
- [从素材到完成的角色](#从素材到完成的角色)
- [Part 1 — OBS 直播整合](#part-1--obs-直播整合)
- [Part 2 — 制作动画](#part-2--制作动画)
- [Part 3 — 桌面角色](#part-3--桌面角色)
- [导入 rig](#导入-rig)
- [进阶功能](#进阶功能)
- [可选依赖](#可选依赖)
- [键盘快捷键](#键盘快捷键)
- [疑难排解](#疑难排解)

---

## 快速开始

1. 启动 Rigora（从源码跑就 `python -m rigora`）。
2. 点窗口顶端的 **Puppet** 标签。
3. **File > Examples > Imeru**（或工具栏的 **Examples ▾** 下拉）。内置的 rig — Rigora 的吉祥物 — 居中加载。
4. 在底部 **Motions** 停靠栏点 8 个动作中的任一个 — rig 立刻动起来。
5. 工具栏的 **Reset to rest** 按钮把 rig 拉回静止姿势。

这是基本款。下面解释怎么把这个 idle rig 变成直播或视频文件。

---

## 从素材到完成的角色

从分层插画到能直播、做动画、待在桌面上的角色，一条完整路径。每一步都链接到对应章节。

1. **导入。** **File > Import PSD…** 会先列出每个图层，以及导入无法保留的功能（蒙版、不支持的混合模式），确认前不会改动任何东西（[从 PSD](#从-psd)）。Cubism 模型走 **File > Import Cubism…**。
2. **检查 rig。** **Tools > Rig doctor…** 列出损坏的网格、权重与左右对称问题、缺少的标准绑定以及验证错误，应用前先预览每项修正（[Rig doctor 与部件模板](#rig-doctor-与部件模板)）。
3. **加入标准部件。** **Tools > Part templates…** 给你选的图元加上眨眼、嘴型、转头与摆动（[部件模板](#rig-doctor-与部件模板)）。
4. **细修。** 用 **Mesh** 菜单调整网格与权重（[编辑网格与权重](#编辑网格与权重)），在停靠栏整理变形器与参数分组（[整理变形器与参数](#整理变形器与参数)），用 **Tools > Physics chains…** 调头发与衣物（[物理](#物理)）。
5. **校准并表演。** 在 **Live > 输入设备与校准…** 选设备、调追踪，然后开始直播（[Part 1](#part-1--obs-直播整合)）。
6. **做动画。** 录 take、编辑关键帧、编排合成并导出（[Part 2](#part-2--制作动画)）。
7. **放到桌面。** 在 Desktop Pet 标签加载 rig 并给它一个脚本（[Part 3](#part-3--桌面角色)）。
8. **素材更新时。** **File > Update art from PSD…** 只换像素、保留绑定（[从 PSD 更新素材](#从-psd-更新素材)）。

每个会改动 rig 的步骤都是一个 **Edit > Undo** 步骤。

---

## Part 1 — OBS 直播整合

目标：在 OBS 上有一个 webcam 风窗口显示你的 puppet，被你的脸 / 麦克风 / 鼠标驱动，准备好放进直播。

### 1.1 输入端（什么驱动 rig）

Puppet 工具栏有 6 个实时输入 toggle（**Live** 菜单里也有同样 6 个），可以同时开（彼此不冲突、只要驱动不同参数）。

| Toggle | 驱动 | 可选依赖 |
|---|---|---|
| **Drag-track head** | `ParamAngleX/Y`、`ParamEyeBallX/Y` 跟着在 canvas 上移动的鼠标光标 | 无 |
| **Auto-blink** | `ParamEyeLOpen/ROpen` 每 ~4.5 秒眨一次眼 | 无 |
| **Mic lip-sync** | `ParamMouthOpenY` 跟着麦克风音量、`ParamMouthForm` 跟着元音音色 | `sounddevice` |
| **Webcam tracking** | 脸部 landmark 驱动头部 yaw/pitch/roll、眼睛开合、视线与嘴巴开合 | `opencv-python` + `mediapipe` |
| **Auto idle** | 呼吸循环 + 头 / 身体轻微 drift | 无 |
| **Idle motions** | 每 8 秒从 `Idle` 组随机播一个动作 | 无 |

典型脸部追踪 VTuber 设置：开 **Webcam tracking** + **Auto-blink** + **Mic lip-sync**。打开 *Webcam tracking* 时会弹出预览窗口，显示摄像头画面 + 检测到的 landmark — 用来确认 tracker 真的有看到你。

> **首次使用注意** — webcam tracking 需要 `mediapipe` 的 face-landmark 模型。Rigora 第一次启用会自动下载（~3.7 MB，从 Google Cloud Storage）到 `<Rigora data directory>/models/face_landmarker.task`，之后直接用缓存。

**Live > 输入设备与校准…** 选择摄像头与麦克风，并调整追踪如何带动 rig。设置存成具名的配置文件（例如每个房间或座位一份）：

- **灵敏度**、**死区**、**平滑** 作用于每个追踪参数。平滑在任何摄像头帧率下效果相同。
- **采集中立姿势（2 秒）** — 开着摄像头追踪、放松坐好后按下。Rigora 记下你静止时的姿势，作为每个参数的默认值，头稍微偏一点就不会被当成"看向别处"。
- **多久后回到中立** / **回归时长** — 脸离开画面时，rig 等这段时间后缓缓回到静止姿势，而不是停在表情中途。
- **麦克风增益**、**麦克风噪声门**、**口型同步平滑** 调整麦克风对嘴；噪声门让环境杂音不会让嘴巴抽动。

列出设备不会打开它们；只有 **Webcam tracking** 会打开摄像头。

多个输入驱动同一个参数时，同一时间只有一个来源控制它。优先级较高的来源立即接管；较低的来源要等当前控制者停止写入 0.25 秒（你拖过的滑块是 1 秒）。顺序：正在拖的滑块 → VTS 插件 → 播放中的动作 → 摄像头 → 麦克风 → 自动眨眼 → 鼠标 → 待机。所以播放中的动作会盖过摄像头，摄像头追踪眼睛时会停用自动眨眼。**Live > 输入来源…** 会列出每个参数当前由谁控制、上面叠了哪些表情。

**Output > VTS API** 是另一种输入：它在 `ws://127.0.0.1:8001`（仅限本机）开一个精简版 VTube Studio Public API 服务器，支持该协议的面部追踪程序连上后，可以列出 rig 的参数并写入数值。它只覆盖追踪程序需要的请求，不是完整的 VTube Studio API — 支持清单、token 规则与速率限制见 [VTS API 支持范围](docs/vts-api-support.md)（英文）。token 12 小时后过期、关闭 API 时失效，也可以在 **Output > 实时状态…** 立即撤销。

### 1.2 输出端（OBS 怎么看到 rig）

三条路。新手用 **A**，要 pixel-perfect alpha 合成用 **B**；**C** 完全不用设置。

#### Path A — Virtual Camera

Puppet canvas 变成 OBS"视频捕获设备"源列表里的一台 webcam。

```bash
pip install pyvirtualcam
```

加上平台对应的虚拟摄像头驱动：

- **Windows**：装 OBS Studio 26+，自带 *OBS Virtual Camera* 驱动。第一次打开 OBS、右下角点 **Start Virtual Camera** 注册驱动，之后 `pyvirtualcam` 才找得到。
- **macOS**：OBS for Mac 自带 system extension，首次运行会要求在"系统设置 → 隐私与安全性"启用。
- **Linux**：`sudo apt install v4l2loopback-dkms` 然后 `sudo modprobe v4l2loopback exclusive_caps=1 card_label="Rigora"`。

接线：

1. Puppet 标签打开 rig，工具栏 / **Output > Virtual camera** 打勾。状态栏会告诉你实际设备名（通常是 *OBS Virtual Camera*）。
2. OBS：**Sources > + > Video Capture Device**，下拉选步骤 1 打印的设备名。

**为什么背景是洋红色？**

虚拟摄像头走 DirectShow / AVFoundation / v4l2loopback，三个传输层**只有 RGB、没有 alpha 通道**。OBS 把进来的图像当不透明 RGB 处理，所以 Rigora 在角色以外填什么颜色，OBS 就显示什么颜色。挑 `#FF00FF` 是业界标准 chroma-key 色 — 几乎不会出现在自然肤色 / 发色 / 瞳色里，去背容差可以开很宽。

**OBS 端去背：**

1. *Video Capture Device* 源右键 → **Filters**
2. **Effect Filters → + → Color Key**
3. 设置：
   - **Key Color Type**：`Custom Color`
   - **Custom Color**：HEX `FF00FF`
   - **Similarity**：从 `80` 起跳，边缘有残留洋红色就拉到 `200–300`
   - **Smoothness**：`30–50`，边缘不会太硬
4. 关闭对话框 — 滤镜会跟着源，之后重启虚拟摄像头都自动套用

#### Path B — NDI（专业、真实 alpha）

NDI 在 LAN 上以 < 50 ms 延迟传 RGBA。不用色键 — alpha 通道整条传过去。

```bash
pip install ndi-python
```

加上：

1. 从 <https://ndi.video/tools/> 下载 **NDI Tools** — installer 包含 runtime DLL，`ndi-python` 会 link 进去。
2. OBS 端装 **obs-ndi** 插件：<https://github.com/obs-ndi/obs-ndi/releases>

接线：

1. Puppet 标签工具栏 / **Output > NDI output** 打勾。状态栏显示源名（默认 *Imervue Puppet*）。
2. OBS：**Sources > + > NDI Source**，下拉选步骤 1 的源名。

角色直接合成到 OBS 场景，零色键滤镜。Off-screen render 把角色外的区域填成完全透明。

**`ndi-python` Windows 编译前置**

`ndi-python` 只 ship source distribution，pip 拿到后从 C++ 编。Windows 上要：

- **Visual Studio Build Tools 2022** 勾"**使用 C++ 的桌面开发**"工作负载
- **CMake**（安装时勾 *Add to system PATH*）
- **NDI SDK**（跟 NDI Tools 不同，去 <https://ndi.video/for-developers/ndi-sdk/> 拿）装在默认 `C:\Program Files\NDI\NDI 6 SDK\`
- 环境变量 `NDI_SDK_DIR` 指向 SDK 安装路径

嫌麻烦就走 Path A。

#### Path C — Window Capture（零安装）

OBS **Sources > + > Window Capture** 可以直接抓 Rigora 窗口。没有虚拟摄像头驱动、没有 SDK。Trade-off：

- 抓整个 Rigora 窗口（含外壳），要加 OBS *Crop/Pad* filter 裁到只剩 puppet 区。
- Puppet 工作区的棋盘格背景也会跟着推。
- 受 Rigora 窗口大小限制。

只适合临时 demo。要正式直播用 A 或 B。

### 1.3 角色独立渲染路径

Virtual Camera 与 NDI 都用 off-screen framebuffer 重画，**不含棋盘格背景跟任何编辑器外壳**。Rigora 窗口里的工具栏 / 停靠栏 / 状态栏纯粹是给你编辑用的，推流只有角色 drawable 本身。输出长边上限 1080 px（避免 3503×7777 的 Cubism canvas 把 DirectShow 驱动搞挂）。

### 1.4 两段 take 之间重置

**Loop** 关闭时动作会停在最后一帧，**Pause** 会停在当前姿势，实时输入也会把参数留在最后写入的值。点工具栏 **Reset to rest**（或 **Edit > Reset to rest**）一键归零：

- Motion player 直接停（不走淡出）
- 所有实时输入 toggle 取消勾，**Record motion** 也会停止（录到的 take 会保留）
- Active expressions 清空
- Pose groups 还原第一个 member
- 物理链弹回静止姿势
- 参数值还原到 authored defaults

状态栏确认："*Rig reset to neutral pose.*"

### 1.5 实时状态与设备问题

**Output > 实时状态…** 显示每个输出与设备的运行情况：接收端看到的名称、分辨率、实际与目标帧率、掉帧数、连接状态与最近错误。VTS API 会显示已连接的插件数。

画面通过两帧的队列送往虚拟摄像头与 NDI。接收端比 rig 慢时，旧的帧会被丢弃并计数；编辑器本身不会等接收端。持续发送失败时输出会自动关闭，状态栏会说明原因。

Rigora 会自行处理常见的设备问题：

| 问题 | 会发生什么 |
|---|---|
| 摄像头被拔出或被其他程序占用 | 追踪会报告，并在 1、2、4、8、15 秒后重试，之后停下等你按 **重试设备** |
| 麦克风被拔出 | 对嘴会报告，并以相同方式重试 |
| 摄像头访问被拒绝 | 不自动重试；在系统设置允许摄像头访问后按 **重试设备** |
| 面部模型下载失败 | 不自动重试；检查网络后按 **重试设备** |
| 追踪中在校准对话框换摄像头 | 先释放旧摄像头，再启动新的 |
| 电脑睡眠 | 唤醒后重新启动一次追踪 |

关闭一个输入会停止它的采集线程并释放设备。

---

## Part 2 — 制作动画

目标：磁盘上有一个 `.mp4` / `.webm` / `.gif` / `.png` 文件。

### 2.1 从实时 take 录制动作

最简单的路径：用脸 / 麦克风 / 鼠标驱动 rig、实时录下参数值，Rigora 烘焙成一个之后可以播 / 循环 / 保存的 `Motion`。

1. 打开 rig。
2. 启用想驱动 rig 的实时输入（webcam / drag / blink / lip-sync / idle），或准备自己拖 **Parameters** 停靠栏的滑块。
3. **Output > Record motion**。对话框问你动作名称（默认 `user_motion`），确认后开始录制。
4. 表演 — 动脸 / 讲话 / 移动鼠标 — 持续多久都可以。
5. 再选一次 **Output > Record motion** 停止录制。
6. 新动作出现在 **Motions** 停靠栏。如果已有同名动作，Rigora 会问你：**替换它**、**两者都保留**（新 take 取带编号的名称）或 **舍弃新录制**。加入动作会重新加载 rig，参数、表情和物理都回到默认值，而且是一个 **Edit > Undo** 步骤。点它播放，或 **File > Save As…** 把它存进 `.puppet` 文件。

每个 take 会记住录制时间、采样率与当时开着的实时输入；替换动作时也会记下它替换了哪个 take。**Motions** 停靠栏的提示文字会显示这些信息。

录制速率 30 Hz。没变动的轨（整段都不变的参数）自动丢掉。每个保留的轨在每两个相邻采样之间产生一个 linear segment。录制器读取的是参数本身的值（滑块、动作、实时输入），所以表情叠加和物理输出不会录进 take。录出来的动作不属于任何组。

### 2.2 编辑录好的动作

**Motion Timeline** 对话框可以事后微调动作的关键点。

1. 在 **Motions** 停靠栏点击动作让播放器载入它，再选 **Edit > Edit motion…**。
2. 从 **Track** 列表选一个参数。图表显示该轨的关键点：X 轴是动作时长内的时间，Y 轴是该参数自己的范围（rig 没定义这个参数时为 −1 到 1）。
3. 拖动黄色的点来移动关键点的时间和数值。`cubic-bezier` segment 可以拖动紫色控制手柄来塑形。每个 segment 都画成两个关键点之间的直线。
4. **缓动** 会重塑当前显示轨道的每个 segment：选一种缓动曲线（例如 `ease-in-out-sine`），再按 **应用到此轨道**。关键点留在原位；`elastic` 和 `bounce` 会变成每个 segment 16 个 linear 关键点。**精简关键帧** 会在每条轨上删除与前后关键点连线相差在 **容差**（参数范围的百分比）以内的关键点 — 把 30 Hz 的 take 精简到真正重要的关键点，旁边的标签会显示精简前后的关键点数。对话框不能单独新增关键点。
5. 每次拖动都会更新内存中的动作，并把 canvas 重新摆到播放器当前的时间点。**File > Save As…** 才会把修改写进 `.puppet` 文件。

一次处理多个关键帧：

- 在空白处拖动可框选关键帧。参数很多时，**筛选轨道…** 可以缩小 **Track** 列表。
- **复制关键帧** 与 **粘贴到…** 把选中的关键帧复制到同一轨或另一轨的其他时间；**移动…** 平移它们的时间与数值；**缩放时间…** 拉长或压缩它们的间距。
- **吸附** 在拖动、移动与粘贴时把时间对齐到 1/30 秒、1/60 秒或 0.1 秒。
- **切线** 把选中关键帧的曲线设成 `linear`、`smooth`、`flat` 或 `stepped`。
- 动作有声音时，波形会画在关键帧后面，方便把嘴型关键帧对齐音节。

不会造成任何改变的操作（例如没有选中关键帧）会在图表下方说明，动作保持原样。对话框关闭后，每次编辑都能用 **Edit > Undo** 撤销。

### 2.3 手动 keyframe 编辑（不录 take）

Puppet 标签没有用来新建动作的 keyframe 编辑器。不靠实时表演也想做出动作：

1. 打开 **Output > Record motion**，自己拖 **Parameters** 停靠栏的滑块 — 滑块变化和其他实时输入一样会被录下。
2. 停止录制，再用 **Edit > Edit motion…** 调整关键点（见 2.2）。
3. 要精确的 keyframe，就直接手写 `.puppet` zip 里的 `motions/<name>.json`，并把名称加进 `puppet.json` 的 `motions`（见 [`FORMAT.md`](rigora/puppet/FORMAT.md)）。

每个滑块旁的 **Set key** 按钮是绑骨用的工具，不是动作 keyframe：它把每个变形器当前的 form 存成该参数在滑块当前值的 key。**Edit > Add Parameter** 会新增一个 `ParamN` 滑块（−1 到 1）供你打 key。

Parameter blends — 在两个以上参数构成的网格上给变形器 form 打 key，例如用 `ParamAngleX × ParamAngleY` 在 2D 网格上控制头部方向 — 从 `puppet.json` 的 `parameter_blends` 读取；Puppet 标签没有编辑它的界面。

### 2.4 输出

| 动作 | 输出 |
|---|---|
| **Output > Capture frame…** | 把当前 frame 存成透明背景的单张 PNG。适合做缩图 / 静态头像。 |
| **Output > Record…** | 先选 GIF / WebM / MP4 文件，接着用 `imageio` 以 30 fps 写入帧，直到你再次切换关闭；codec 由扩展名决定。工具栏按钮就是同一个 toggle。 |
| **Output > Export all motions…** | 选文件夹和容器格式（`.mp4`、`.gif` 或 `.webm`）；每个动作从头播放并录满它的时长，存成 `<motion-name>.<ext>`。适合批量产出反应 clip、idle loop 等。 |
| **Output > Export animation…** | 离线逐帧渲染一个动作或合成，不受屏幕刷新率影响。可选 PNG 序列、GIF、MP4 或 WebM，以及尺寸、帧率、时间范围、透明背景（PNG 与 WebM 保留 alpha），并先让物理预热，让头发在第一帧就已稳定。视频可以带动作的声音。导出会排进队列并显示每个任务的进度；取消或失败的导出不会留下半成品，按 **重试** 可以再跑一次。文件已存在时默认保留，除非你选择覆盖或改名。 |

录制用跟推流一样的**角色独立 off-screen render**，所以你不用事后 crop 掉外壳。GIF / WebM / MP4 的帧按文档长宽比缩进长边 1080 px，背景为白色（这些格式不带 alpha），每边取 16 的倍数。PNG 截取保留文档尺寸，长边上限 4096 px。

### 2.5 动作配音

一个动作可以携带 `sound_path` — 一个 WAV 文件的绝对路径。动作开始播放时声音跟着播放并与动作同步：拖动时间轴时声音跳到同一时间，循环动作每圈重新播放声音，播放与声音偏差超过 80 毫秒时动作会跟着声音的时钟走。**Pause** 和 **Stop** 会停止声音。把 Cubism `.model3.json` 叠加到已打开的 rig（见*导入 rig*）时，会从动作条目的 `Sound` 字段填入；**Live > 从音频文件对嘴…** 则会围绕一个 WAV 建立新动作：嘴巴（`ParamMouthOpenY`）随它的音量张开，而这个 WAV 就是动作的声音。选项可以设置关键帧速率、嘴巴比声音提前多少（默认 40 毫秒，看起来最同步），以及让字与字之间闭嘴的静音门。其他动作仍要编辑 `.puppet` zip 内的 `motions/<name>.json` — Puppet 标签没有设置它的字段。WAV 文件本身不会存进 `.puppet`。**验证** 会列出声音文件不存在的动作，**File > 重新链接声音…** 会在你选的文件夹里按文件名查找，并以一个可撤销的步骤更新路径。

如果没装 `PySide6.QtMultimedia`，音频优雅停用，动作的视觉轨仍然会播。

### 2.6 用合成编排动作

合成把几个动作放在同一条时间轴上一起播放 — 例如身体挥手的同时脸在笑 — 而不必修改动作本身。打开 **Edit > 合成…**：

1. **新建** 创建一个合成，设置 **时长（秒）**。按 F2 改名。
2. 加入图层。图层是 **override**（按强度替换下层设置的值）或 **additive**（把自己的动作叠加上去）。每个图层可设权重或静音。
3. 选一个图层并加入片段：选动作、开始时间、可选的动作内偏移与长度、循环、淡入淡出、权重与静音。同一图层内，淡入中的片段会与前一个片段交叉淡化。
4. **预览** 在 canvas 上播放合成，不会修改 rig。问题（缺少的动作、重复的图层名称、负的时间）会列在表格下方，修正前对话框不会保存。
5. **OK** 以一个可撤销步骤保存合成。**保存并烘焙为动作** 会另外把选中的合成加成普通动作，可以编辑、让 hit area 播放，或给不支持合成的程序使用。

**Output > Export animation…** 也可以选合成。合成会存进 `.puppet` 文件（见 [`FORMAT.md`](rigora/puppet/FORMAT.md#composition)）。

---

## Part 3 — 桌面角色

**Desktop Pet** 标签把 rig 放到桌面上。它的 **角色** 标签可以同时运行多个角色，每个都有自己的 rig、脚本与设置；停止其中一个不影响其他角色，布局会记住谁在哪里运行。脚本可以包含行为规则 — 点击、拖放、热键、音乐节拍与计时，搭配条件、冷却与优先级 — 脚本编辑器会在执行前检查并预览。屏幕被拔出、缩放改变或电脑唤醒时，角色会回到看得见的位置；没有动静时以 15 fps 重绘，隐藏时停止重绘。可选的本机 LLM 可以生成新台词，但它的回复只能触发角色自己的动作与表情。

[桌面角色指南](docs/desktop-companions.md)（英文）涵盖以上所有内容与完整的事件、动作列表；[示例](examples/README.md)（英文）附有现成的行为脚本。

---

## 导入 rig

### 从 PNG

**File > Import PNG…** 先询问网格的格子大小（默认 64 px；越小网格越密），再对图像跑 `auto_mesh`：

- 用正方形格子铺满图像，完全透明的格子全部丢掉
- 预先设置 Cubism 标准参数目录（`ParamAngleX/Y/Z`、`ParamEyeLOpen/ROpen`、`ParamMouthOpenY`、`ParamBreath` …）
- 产生单一 drawable、还没有变形器的 rig — 从 **Edit** 菜单加入变形器

适合：快速 prototype、单张无分层的角色图。

### 从 PSD

**File > Import PSD…** 把每个可见、非空的图层变成独立 drawable — 一个裁到图层不透明范围的四边形，按图层顺序叠放 — 每个图层组变成一个 Part。接着预先设置标准参数目录，再按图层名称自动绑骨：

- 名称含左右和开闭状态的眼睛图层（`eye_l_open`、`EyeRClose` …）跟着 `ParamEyeLOpen` / `ParamEyeROpen` 淡入淡出，所以 Auto-blink 会切换它们
- 嘴巴图层（`mouth_open`、`mouth_close`、`mouth_a` … `mouth_o`）跟着 `ParamMouthOpenY` 和 `ParamMouthForm` 淡入淡出，所以 Mic lip-sync 会切换它们
- `head` / `face` 图层共用一个以 `ParamAngleZ` 打 key（±15°）的旋转变形器
- `hair` / `bang` / `fringe` 图层共用一个 warp 变形器，外加一条从 `ParamAngleX` 到 `ParamHairFront` 的物理链；warp 以 `ParamHairFront` 打 key，发尾会左右摆动

其他图层（身体、手臂、衣服）不会加任何变形器。

适合：美术提供的多图层角色文件。

导入前会先打开 **导入预览**：列出每个图层的顺序（上层在前）、组、状态、drawable id、尺寸、位置、不透明度、混合、蒙版与剪贴，以及与 PSD 的所有差异，分为“阻止导入”“影响结果”“说明”三级。按取消不会改动当前文档。PSD 功能对应如下：

| PSD 功能 | 导入后 |
| --- | --- |
| 图层组、嵌套组 | Part、子 Part；隐藏组与组不透明度会保留 |
| 正常／正片叠底／线性减淡（添加） | `normal`／`multiply`／`additive` |
| 其他混合模式 | 按 `normal` 绘制（列入差异） |
| 剪贴蒙版 | 对基底图层网格设 `clip_mask` — 用的是它的 alpha 外框，不是逐像素（列入差异） |
| 图层蒙版、矢量蒙版、填充不透明度、图层样式、调整图层 | 不应用（列入差异） |
| 文字、智能对象、填充图层 | 以文件内存储的像素导入（列入差异） |
| 隐藏或空白图层、剪贴到隐藏基底的图层 | 跳过（列入差异） |
| 名称含 `A-Z a-z 0-9 _ -` 以外字符或重复 | 以清理后的唯一 id 存储（列入差异） |

### 从 PSD 更新素材

**File > Update art from PSD…** 把重新导出的 PSD 套到当前 rig，无需重新绑定。每个 drawable 按相同 id（全新导入时由图层名称生成的 id）对应图层；对话框逐行显示变更、当前与新的范围、问题及操作：

- **替换像素，保留网格**（有变更时的默认）：保留顶点、骨骼权重、morph、变形器与动作，只替换现有网格下的像素。新图层比网格大时会标示“新素材超出网格范围”。
- **重建网格**：按新素材建立新的四边形；该 drawable 的骨骼权重与顶点 morph 会丢弃，数量显示在状态栏。
- **添加图元**（新图层）：插在 PSD 中下方图层的正上方，并加入所属组的 Part。
- **保留／隐藏**：用于 PSD 中已没有的 drawable。

位置相同、一个消失一个新增的组合会标为“可能是重命名的图层”，默认不添加。画布尺寸与 rig 不同时会阻止更新。UV 不是简单矩形或共用贴图的 drawable 只能重建或跳过。整次更新是一个 Undo 步骤。

### 重新链接贴图

打开缺少贴图的文件时，状态栏会提示。**File > Relink textures…** 列出缺失或无法读取的贴图、使用它的 drawable 与预期尺寸。*搜索文件夹…* 会查找同名文件（任意图像格式）；*选择图像…* 可手动指定。图像沿用现有 UV，尺寸不同时会拉伸到网格上并注明。重新链接是一个 Undo 步骤。

### 从 Cubism `.moc3`

**File > Import Cubism…** 会先显示导入模式说明（勾选 *Don't show this again* 以后就跳过）。它同时接受 `.moc3` 和对应的 `.model3.json` manifest — 不论选哪个、只要工作区还没开 rig，导入器都会跑完整 sample-and-reconstruct 转换：

1. 通过 Cubism Native SDK 加载 `.moc3`（用户自备 — 把 SDK 解压到 `<cwd>/sdk/` 或设 `CUBISM_CORE_DLL` 环境变量指向 DLL）。直接选 `.moc3` 也可以，只要旁边有同名 `.model3.json`，工作区会自动定位到 manifest。
2. 把每个 Cubism 参数从 min 扫到 max，记录每个 drawable 的形变顶点。
3. 同时抓取参数驱动的 *visibility* 切换 — 比耶 / 捂脸 / 哭等手势切换都能完整保留。
4. 把 `.model3.json` bundle 里既有的 motion / expression / physics / hit-area / display-name 全部 fold 进 puppet。bundle 的 `motions/` 文件夹里、manifest 没列到的动作会归入 `Idle` 组。

转换好的 rig 会在 canvas 上打开；用 **File > Save As…** 写成自包含的 `.puppet` zip，不需要附 Cubism SDK 就能散布（SDK 永不打包 — Live2D 的 Free Material License 规定）。

> **叠加到既有 rig**：如果已经开了一个 `.puppet`，此时选 `.model3.json` 会把它的 JSON 部分叠加到当前文档上：名称或 id 还不存在的 motions、expressions、physics、hit areas、pose groups，再加上 display names — 适合把 Cubism 动作库嫁接到自己手绘的 PSD rig。`.moc3` 路径始终新建文档；要往既有 rig 加动作，请选 `.model3.json` 或单独的 `.motion3.json` / `.exp3.json` / `.physics3.json` / `.pose3.json` / `.cdi3.json`。

选 `.moc3` 或 `.model3.json` 时会先打开 **Cubism 导入预览**。它只读 JSON 文件、不加载 Cubism SDK，逐项列出引用文件是否存在，以及差异：runtime 不支持的动作曲线（`PartOpacity`、`Model`）、缺失的声音、user data、完整转换不读取的 pose 组、keyform 采样近似；合并时另列因同名而跳过的动作或表情、找不到对应 drawable 的 hit area，以及 rig 没有的参数。缺 `.moc3`、缺 Cubism Core 库，或缺少会让合并中止的附属文件时，**导入**按钮会停用。

---

## 进阶功能

### 参数

每个会动的值都是 *parameter*，有 min、max、default。参数的每个 `key` 存的是某个参数值下的变形器 form；runtime 在当前值两侧的两个 key 之间线性插值，超出首尾就保持端点 key。Cubism 标准 id 参考 `rigora/puppet/standard_params.py`。

### 变形器

- **Rotation** — 锚点 + 角度，作用于变形器自己 `drawables` 列表里的 drawable。`parent` 只决定顺序：父节点先于子节点执行，但父节点的旋转只移动它自己列出的 drawable，子节点的锚点也不会跟着父节点动。要让 body lean 带着 head + arms 一起动，就把它们也列进身体的变形器。
- **Warp** — 覆盖在 `bounds` 矩形上的 `rows × cols` 双线性网格；范围内的顶点跟着网格走，范围外的不动。用于脸颊挤压、衣服褶皱、头发摆动。
- **Bone rotation** — `bone_rotation` 变形器（骨骼 id + 锚点 + 角度）给带有 `bone_weights` 的 drawable 做蒙皮：每个顶点按权重混合各骨骼的旋转。骨骼之间同样不会继承旋转。
- **Vertex morphs** — Cubism 式每 drawable 的 delta 数组，在参数默认值跟极值之间做线性混合。`.moc3` 转换器产生这个。

### Pose groups

互斥的 drawable 可见度。同时只显示组里一个成员：在 **Pose** 停靠栏挑要显示的成员，其他成员隐藏。用于武器切换、嘴型变体、costume 切换。默认显示组里的第一个成员；成员本身的 `visible` 标志不起作用。

### 物理

Verlet pendulum 链用于头发 / 衣物 / 缎带。*输入参数*（例如 `ParamAngleX`）让链锚点横向移动；重力 + 阻尼 + per-particle 弹簧把链拉回静止；尖端横向位移映射回 *输出参数*（例如 `ParamHairFront`），限制在 −1…1。静止时输出等于输入，所以输入一变化，链就会延迟跟上并甩过头，看起来就是摆动。

Puppet 标签显示中且 rig 有物理链时，canvas 用自己的时钟每秒推进约 60 次，所以输入停下后链还会继续摆。物理链的输出会覆盖滑块、动作或表情在该参数上的值。**Reset to rest** 会把所有链弹回静止。

物理链来自 Cubism 导入（`.physics3.json`）、PSD 自动绑骨的头发规则、部件模板，或 **Tools > Physics chains…**。这个对话框可以编辑输入与输出参数、粒子数、长度、刚性、阻尼与重力，并能保存、重用预设。它会警告无法运作的链（缺少参数、输出同时是输入）以及会让输出饱和的设置；每次修改都是一个 Undo 步骤。物理链存在 `.puppet` 文件里的 `physics.json`。

### 编辑网格与权重

打开 **Mesh > Edit mesh** 之后：

- 点顶点选中，**Shift**＋点加入选中，在空白处拖动可框选（按住 **Shift** 加入选中）；
- 拖动已选的顶点会移动整组选中；
- **Lock selected vertices** 让这些顶点在拖动其他顶点时保持不动，**Unlock all vertices** 解除；
- **Show weights…** 以颜色显示某根骨骼的权重；**Smooth weights**、**Normalize weights** 与 **Mirror weights left → right** 编辑选中顶点的骨骼权重；
- **Mirror selected vertices** 与 **Delete selected vertices…** 会改变网格；删除前会列出受影响的三角形、权重与 morph。

每次编辑都是一个 Undo 步骤。

### 整理变形器与参数

**Bones** 停靠栏把变形器显示成树状。可以按名称搜索，把一行拖到另一行上改变父级（拖到空白处则脱离父级），用 **Up** / **Down** 移动顺序，**Lock** 让变形器不能被改父级或改顺序，**Hide** 把它从列表隐藏（**Show hidden** 会再显示）。出现父级循环时会警告并列出相关的变形器。

**Parameters** 停靠栏把滑块分成 Head、Eyes、Mouth、Body、Hair 与 Other 分组，**Filter parameters…** 可缩小列表。每个滑块的 **⋯** 菜单有 **Edit range…**（会让已有 key、blend key 或表情值落到范围外的范围会被拒绝）与 **Preview key forms**（逐一预览该参数的 key）。**Reset all** 把所有滑块还原成默认值。

### Rig doctor 与部件模板

**Tools > Rig doctor…** 检查 rig，并按类别整理结果：网格问题（零面积或损坏的三角形、重复或未使用的顶点）、加总不等于 1 的骨骼权重、缺少镜像对应的左右图元、自动绑骨会加上的标准绑定（例如头部倾斜、头发摆动），以及 **Validate** 会报告的所有问题。选中项目可预览每项修正，再一起应用成一个 Undo 步骤。命令行可用 `rigora rig-doctor` 执行相同检查。

**Tools > Part templates…** 为你选的图元加上现成绑定：**眨眼**、**嘴型**、**转头**（已有头部倾斜时会沿用，不会再叠一层）与 **摆动**。对话框会列出每个模板要建立的内容，并在与已有绑定重叠时警告。

### 表情

参数覆写堆栈，叠在滑块 / 动作值上。模式：`additive`（最终 = base + value）、`multiply`（最终 = base × value）、`overwrite`（最终 = value）。从 **Expressions** 停靠栏切换；启用中的表情按开启顺序应用。

用于瞬时情绪：*smile*、*surprised*、*angry*。内置的 Imeru rig 带 7 个表情（`smile` / `happy` / `surprised` / `sad` / `angry` / `blush` / `sleepy`）。

### Hit areas

命名的点击区域。hit area 的范围是它所列 drawable 在当前（已变形）位置的外框；在范围内按左键（**Edit mesh** 关闭时）会执行它的动作。它的 `motion` 指定动作组 — 从该组随机播一个动作（`TapHead` 会挑一个 `TapHead` 动作）；没有动作属于该组时，播放同名的动作。它的 `expression` 会切换该表情（点 body → 切换 `surprised`）。范围重叠时，含最前面 drawable 的那个胜出。

内置的 Imeru rig 定义了两个：点她的头（`Head`）播放 `TapHead` 动作，点她的身体（`Body`）播放 `TapBody` 动作。用 **File > Import Cubism…** 转换的 rig 会带入模型的 `HitAreas`，但只有范围、没有动作；在 `puppet.json` 的 `hit_areas` 列表里给它们加上 `motion` 或 `expression` 才会有反应。Puppet 标签没有 hit area 编辑器。

---

## 可选依赖

Puppet 标签的核心（渲染、参数系统、动作播放、PNG / PSD / Cubism 导入）跑在默认 `requirements.txt` 上。更重的依赖用 `try / except` 包起来，缺了也不会坏其他功能。

| 功能 | 可选依赖 | 安装 |
|---|---|---|
| Webcam 脸部追踪 | `opencv-python` + `mediapipe` | `pip install opencv-python mediapipe` |
| 麦克风对嘴 | `sounddevice` | `pip install sounddevice` |
| 虚拟摄像头输出 | `pyvirtualcam` + 平台驱动 | `pip install pyvirtualcam`，见上面 Path A |
| NDI 输出 | `ndi-python` + NDI runtime + NDI SDK（编译时用） | 见上面 Path B |
| Cubism `.moc3` 导入 | 用户自备 Cubism Native SDK DLL | <https://www.live2d.com/sdk/about/> |
| 动作音频播放 | `PySide6.QtMultimedia` | 通常跟着 PySide6；缺的话从平台的 QtMultimedia 包补 |
| 导出 GIF／MP4／WebM 动画 | `imageio` ＋ `imageio-ffmpeg`（在 `gui` extra 中） | `pip install "rigora[gui]"`；PNG 序列两者都不需要 |
| VTS API 输入 | `PySide6.QtWebSockets` | 随 PySide6 提供 |
| 桌面角色全局热键 | `pynput` | `pip install "rigora[hotkeys]"` |
| 桌面角色音乐节奏 | `sounddevice` 与 WASAPI loopback 设备（Windows） | `pip install "rigora[lipsync]"` |
| 桌面角色 LLM 对话 | 本机 [Ollama](https://ollama.com) 服务器（或提供相同 API 的 HTTPS 端点） | 另行安装；Rigora 不会下载任何东西 |

切换一个缺少 Python 包的功能时，会打开该包的安装程序，装好后自动开启功能。包已安装但设备或 runtime 失败（没有麦克风、没有虚拟摄像头驱动、没有 NDI runtime）时，toggle 会自动取消勾，状态栏会说明原因。**File > Install dependencies…** 可以一次装齐所有 Python 可选包；Cubism SDK 跟 NDI runtime 因为授权需要手动装。

---

## 键盘快捷键

| 按键 | 动作 |
|---|---|
| **Ctrl+S** | 保存（第一次会询问文件名） |
| **Ctrl+Z** / **Ctrl+Shift+Z** | 撤销／重做上一个 rig 编辑 |
| **F2** | 重命名选中的合成（合成对话框） |
| **Shift**＋点击或拖动 | 加入顶点选中（Edit mesh） |

其他命令都在菜单与工具栏上。Canvas 接受这些鼠标操作：

| 操作 | 动作 |
|---|---|
| **中键拖动** | 平移 |
| **鼠标滚轮** | 缩放（以光标为中心）；**Tools > Fit to Window** 重新适应窗口 |
| **左键** | 触发光标下的 hit area；**Edit mesh** 开启时选中光标 8 px 内的顶点（最前面的 drawable 优先），在空白处则开始框选 |
| **左键拖动** | **Edit mesh** 开启时移动选中的顶点（锁定的顶点不动） |
| **右键** | 清除 bone 选取 overlay |

---

## 疑难排解

### "Webcam tracking 开了什么都没发生"

预览窗口会弹出显示摄像头画面；如果画面里没有脸，没有参数会被驱动。预览窗口的状态栏显示 *"No face in frame"*。移到镜头前或改善光线。

如果预览是黑的：摄像头被其他 app 占用、或 OS 拒绝了摄像头存取。macOS 首次使用会要求权限 — 检查"系统设置 → 隐私与安全性 → 摄像头"。

### "摄像头追踪一直说摄像头中断"

摄像头停止传送画面 — 通常是被拔出或被其他程序占用。Rigora 会在 1、2、4、8、15 秒后重试，之后停下来等待；**Output > 实时状态…** 会显示倒数，**重试设备** 会立即再试。如果访问被拒绝，请先在系统隐私设置允许摄像头。面部模型下载失败不会自动重试：检查网络后按 **重试设备**。

### "追踪程序送来的值没有作用"

打开 **Live > 输入来源…**：这个参数多半由其他来源控制。正在拖的滑块、播放中的动作与其他插件都比 VTS 插件优先。每秒发送超过 120 个请求的插件会收到错误 6000；被其他插件占用的参数会返回错误 454。见 [VTS API 支持范围](docs/vts-api-support.md)。

### "导出动画说缺少能力"

PNG 序列需要有 OpenGL 的桌面会话；GIF 需要 `imageio`；MP4 与 WebM 需要 `imageio-ffmpeg`。在命令行上会是退出码 4、错误代码 `capability_missing`。取消或失败的导出绝不会留下半成品。

### "OBS 看到洋红色背景"

设计使然 — 见上面 Path A。在 OBS 的 *Video Capture Device* 源加 Color Key filter、`Custom Color = #FF00FF`。

### "ndi-python 安装失败、找不到 cmake"

`ndi-python` 从源码编。装 CMake、Visual Studio C++ Build Tools、NDI SDK — 见 Path B 前置。不需要 NDI 的话用 Path A。

### "动作播完 rig 卡在最后一个姿势"

Motions 停靠栏的 **Loop** 关闭时，播到结尾的动作会停在最后一帧，**Pause** 也会停在当前姿势。**Stop** 会按动作的淡出时间（动作没设置时为 0.5 秒）把动作的参数缓缓带回默认值。工具栏的 **Reset to rest** 一次把所有参数、表情、pose group 和物理链还原。

### "桌面角色的脚本没有加载"

行为规则有问题的脚本会整份被拒绝，角色会继续使用原来的脚本。打开 **Edit script… > Behaviors** 并按 **Check**：每个问题都会标出位置，例如 `rules[2].do[0]: unknown action 'shout'`。

### Cubism 转换器把相机显示成"多一只手"

转换来的 Cubism rig 上的比耶 / 拍照 / 捂脸手势是用 Cubism 动态可见度旗标驱动的。转换器把这些切换存成 `opacity_keys` 曲线，所以每个道具只在对应参数拉起时出现。如果转换出来的 `.puppet` 一直显示这些道具，说明它的 drawable 缺少这些曲线 — 从 **File > Import Cubism…** 重新转换并保存结果。

---

## 文件格式参考

`.puppet` 是 zip 容器、含 JSON manifest 跟 PNG 纹理。完整规格见 [`rigora/puppet/FORMAT.md`](rigora/puppet/FORMAT.md)。

内置 demo rig：[`examples/puppet/imeru.puppet`](examples/puppet/imeru.puppet)，由 `examples/puppet/imeru/build.py` 重新生成（见 [`examples/puppet/README.md`](examples/puppet/README.md)）。
