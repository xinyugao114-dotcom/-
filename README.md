# 译随心翻 · QuickTranslate
一款跨平台（Windows / macOS）的划词翻译、截图与长截图工具。读外国文献、小说时，不必在「阅读」与「查词」之间来回切换 —— 选中任意文本、按住 `Alt` 即弹出极速翻译悬浮窗，随译随记、边阅读边学外语；点一下即可框选截图、钉图，或用滚轮滚出任意长度的长截图。

> 界面显示名称为「译随心翻」，程序/仓库英文名为 **QuickTranslate**。

## ✨ 功能

- **划词翻译** — 选中文本后按住 `Alt`，悬浮窗即时弹出翻译结果（中/英/日/韩等 15 种语言，自动识别源语言）。
- **极速并发翻译** — Bing / Google / MyMemory 三引擎并发竞速，取最快结果；内置离线英汉词库兜底。
- **翻译缓存** — 本地 SQLite 缓存，重复词条毫秒级返回。
- **截图 & 钉图** — 框选区域截图，一键复制、另存、或「钉」在桌面置顶（可缩放、调透明度、拖拽）。
- **长截图** — 选定区域后，滚动鼠标滚轮即可拼接出任意长度的网页/代码长图（OpenCV 模板匹配缝合）。
- **消蓝底** — 截图时自动抹去选中文本的蓝色高亮背景，还原干净白底。
- **系统托盘** — 常驻托盘，随时截图 / 暂停划词 / 退出。

## 📦 安装

### 方式一：下载压缩包（推荐，免安装）

直接点击下载对应系统的压缩包：

- **Windows**：点此下载 [QuickTranslate-Windows-x64.zip](https://github.com/xinyugao114-dotcom/-/releases/download/v1.0.0/QuickTranslate-Windows-x64.zip)（约 178 MB），解压后双击 `QuickTranslate.exe` 即可运行，已内置离线词典，无需安装 Python。
- **macOS / Linux**：点此下载 [QuickTranslate-macOS-Linux-Source.zip](https://github.com/xinyugao114-dotcom/-/releases/download/v1.0.0/QuickTranslate-macOS-Linux-Source.zip)（源码，约 0.16 MB），解压后需 Python 3.10+，按下方「源码运行」安装依赖后启动。

> 更多版本见 [Releases](https://github.com/xinyugao114-dotcom/-/releases) 页面。

### 方式二：源码运行

```bash
git clone https://github.com/xinyugao114-dotcom/-.git QuickTranslate
cd QuickTranslate
pip install -r requirements.txt
python main.py
```

> 离线词典文件 `stardict.csv`（约 232MB）**不包含在源码仓库中**。如需离线英汉词库，请自行将 `stardict.csv` 放到项目根目录；没有它时，工具仍可用在线引擎翻译，仅离线词库功能不可用。

## 🖥 使用

| 操作 | 快捷键 / 方式 |
| --- | --- |
| 划词翻译 | 选中文本后按住 `Alt` |
| 暂停 / 恢复划词 | 托盘菜单 →「暂停划词翻译」 |
| 截图 / 钉图 | 点击悬浮窗「截」按钮，或托盘「开启截图 / 钉图」 |
| 长截图 | 截图框选后点「长截图」，滚动鼠标滚轮，按 `Esc` 完成 |
| 关闭钉图 | 钉图卡片右上角「✕」，或右键「销毁钉图」 |

## 🔨 打包（仅二次开发需要）

> 普通用户**无需打包**，直接去上方「📦 安装」下载现成的压缩包即可。本节仅面向想自己从源码编译 EXE 的开发者。

### 前置准备

先在**项目根目录**（含 `main.py` 的文件夹）打开终端，执行：

```bash
pip install -r requirements.txt
pip install pyinstaller
py make_icon.py        # Windows 生成图标
python3 make_icon.py   # macOS 生成图标
```

### Windows（生成 `dist/QuickTranslate.exe`）

在**项目根目录**的终端（CMD 或 PowerShell）里运行：

```bat
build\build_win.bat
```

> 也可以直接在资源管理器里双击 `build\build_win.bat`，脚本会自动切到项目根目录执行。

### macOS（生成 `dist/QuickTranslate`，需在 Mac 上执行）

在**项目根目录**的终端里运行：

```bash
chmod +x build/build_mac.sh
./build/build_mac.sh
```

## ⚙️ macOS 授权说明

在 macOS 上首次运行，系统会要求授予以下权限，否则相应功能无法工作：

1. **辅助功能（Accessibility）** — 供 pynput 全局监听键盘/鼠标（划词、长截图滚轮）。
2. **屏幕录制（Screen Recording）** — 供 Qt 抓屏（截图、长截图）。

路径：`系统设置 → 隐私与安全性 → 辅助功能 / 屏幕录制`，勾选本程序。

## 📁 目录结构

```
QuickTranslate/
├── main.py              # 主程序（单文件）
├── make_icon.py         # 图标生成脚本
├── QuickTranslate.spec  # PyInstaller 打包脚本
├── requirements.txt     # 源码运行依赖
├── assets/              # 图标（icon.png / .ico / .icns）
├── build/               # 打包脚本（Windows / macOS）
└── dist/                # 打包产物（gitignore）
```

## ❓ FAQ

- **为什么离线词典要单独下载？** `stardict.csv` 约 232MB，超过 GitHub 单文件 100MB 上限，故不进源码仓库，仅在打包 EXE 时打入。
- **EXE 启动慢？** 单文件（onefile）模式每次启动会把词典解压到临时目录，首次运行还要建库，属正常现象。
- **离线词库范围？** 仅支持英 → 中单词查询；短语、句子及其它语言方向需联网。

## 📄 License

[MIT](./LICENSE) © 2026 QuickTranslate contributors
