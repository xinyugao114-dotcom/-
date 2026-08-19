#!/bin/bash
# 在 macOS 上打包 QuickTranslate（需在 Mac 上执行，无法跨平台交叉编译）
# 前置：已安装 Python3 + PyInstaller（python3 -m pip install pyinstaller）
set -e
cd "$(dirname "$0")/.."
python3 -m PyInstaller QuickTranslate.spec --noconfirm --clean
echo ""
echo "打包完成，产物位于 dist/QuickTranslate"
