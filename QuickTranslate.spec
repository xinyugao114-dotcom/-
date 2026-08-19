# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 单文件（onefile）打包脚本
# 用法（在项目根目录执行）：
#   Windows:  py -m PyInstaller QuickTranslate.spec
#   macOS:    python3 -m PyInstaller QuickTranslate.spec
import os
import sys

APP_NAME = "QuickTranslate"

icon_path = "assets/icon.icns" if sys.platform == "darwin" else "assets/icon.ico"
icon_arg = icon_path if os.path.exists(icon_path) else None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    # 232MB 离线词典打进 EXE（作为 release 产物；源码仓库用 .gitignore 排除）
    datas=[("stardict.csv", ".")],
    hiddenimports=[
        # deep_translator 为惰性导入，需显式声明以免被打包器遗漏
        "deep_translator",
        "deep_translator.google",
        "deep_translator.mymemory",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 静态分析会误跟随 try/import 星导入，把整条数据科学栈拽进来，这里显式剔除
        "torch",
        "torchvision",
        "torchaudio",
        "pandas",
        "scipy",
        "matplotlib",
        "sqlalchemy",
        "sklearn",
        "IPython",
        "jupyter",
        "notebook",
        "jinja2",
        # 去掉未用到的 Qt 模块，缩小体积
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtQml",
        "PyQt6.QtQuick",
        "PyQt6.QtQuickWidgets",
        "PyQt6.QtMultimedia",
        "PyQt6.QtMultimediaWidgets",
        "PyQt6.QtBluetooth",
        "PyQt6.QtDBus",
        "PyQt6.QtDesigner",
        "PyQt6.QtHelp",
        "PyQt6.QtLocation",
        "PyQt6.QtNetwork",
        "PyQt6.QtNfc",
        "PyQt6.QtOpenGL",
        "PyQt6.QtPositioning",
        "PyQt6.QtPrintSupport",
        "PyQt6.QtRemoteObjects",
        "PyQt6.QtSensors",
        "PyQt6.QtSerialPort",
        "PyQt6.QtSql",
        "PyQt6.QtSvg",
        "PyQt6.QtTest",
        "PyQt6.QtTextToSpeech",
        "PyQt6.QtXml",
        "PyQt6.Qt3DCore",
        "PyQt6.QtCharts",
        "PyQt6.QtDataVisualization",
        "PyQt6.QtPdf",
        "PyQt6.QtPdfWidgets",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_arg,
)
