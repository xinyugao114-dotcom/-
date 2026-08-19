# -*- coding: utf-8 -*-
"""生成 QuickTranslate 应用图标（icon.png / icon.ico / icon.icns）。

复用 main.py 里 make_app_icon() 的绘制逻辑：蓝色圆角方块 + 白色「译」。
用 PyQt6 的 QPainter 渲染保证 CJK 字形可靠（走系统字体），再用 Pillow 转
Windows 多尺寸 .ico 与 macOS 的 .icns。

用法：
    py make_icon.py
"""
import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication

SIZE = 512
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def render_pixmap(size: int) -> QPixmap:
    _app = QApplication.instance() or QApplication(sys.argv)
    font_family = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei"

    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = max(1, size // 16)
    radius = max(2, size // 8)
    painter.setBrush(QColor(13, 110, 253))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(margin, margin, size - 2 * margin, size - 2 * margin, radius, radius)

    painter.setPen(QColor(255, 255, 255))
    painter.setFont(QFont(font_family, int(size * 0.44), QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "译")
    painter.end()
    return pixmap


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    png_path = os.path.join(OUT_DIR, "icon.png")
    render_pixmap(SIZE).save(png_path, "PNG")

    from PIL import Image

    img = Image.open(png_path).convert("RGBA")

    ico_path = os.path.join(OUT_DIR, "icon.ico")
    img.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    icns_path = os.path.join(OUT_DIR, "icon.icns")
    try:
        img.save(icns_path, format="ICNS")
    except Exception as e:  # Pillow 的 ICNS 写入对不同版本要求不一，失败不阻塞
        print(f"ICNS 转换跳过：{e}")

    print(f"OK -> {png_path}")
    print(f"OK -> {ico_path}")
    print(f"OK -> {icns_path}")


if __name__ == "__main__":
    main()
