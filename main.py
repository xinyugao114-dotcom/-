import socket
import urllib.request
import threading
import os
os.environ["QT_LOGGING_RULES"] = "qt.qpa.window=false"

import sys

# 打包模式下显式指定 Qt 插件路径
if getattr(sys, 'frozen', False):
    _bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    _qt_plugins = os.path.join(_bundle_dir, 'PyQt6', 'Qt6', 'plugins')
    if os.path.isdir(_qt_plugins):
        os.environ['QT_PLUGIN_PATH'] = _qt_plugins
        os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(_qt_plugins, 'platforms')

import time
import re
import shutil
import subprocess
import ctypes
if sys.platform == "win32":
    import ctypes.wintypes
import sqlite3
import csv
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QGraphicsDropShadowEffect, QMessageBox, QSystemTrayIcon, QMenu, QWidgetAction,
    QFileDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QThread, QEvent, QPoint, QRect, QTimer
from PyQt6.QtGui import QFont, QColor, QAction, QActionGroup, QIcon, QPixmap, QPainter, QPen, QImage
import pyperclip
import pyautogui
from pynput import keyboard
from pynput import mouse
from pynput.keyboard import Key, Controller as KeyboardController
from deep_translator import GoogleTranslator, MyMemoryTranslator

CURRENT_VERSION = "6.0.0"  # GitHub 开源 OpenCV 长截图缝合+全功能版
APP_NAME = "QuickTranslate"

kb_controller = KeyboardController()
TRANSLATE_CACHE = {}
IS_ONLINE = True
global_pinned_windows = []
_snip_overlay_instance = None

_TRANSLATOR_POOL = ThreadPoolExecutor(max_workers=3)
_CHINESE_RE = re.compile(r'[一-龥]')

# 导入 NumPy 与 OpenCV (用于长截图拼接与蓝底消除)
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

def remove_blue_selection_bg(pixmap: QPixmap) -> QPixmap:
    """GitHub 开源算法：基于 NumPy 矩阵分析，3毫秒抹去图片中的文本蓝底高亮并还原纯白"""
    if not HAS_NUMPY:
        return pixmap
    try:
        qimg = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        w, h = qimg.width(), qimg.height()
        
        ptr = qimg.bits()
        ptr.setsize(h * w * 4)
        arr = np.frombuffer(ptr, np.uint8).reshape((h, w, 4))  # BGRA 格式
        
        b, g, r, a = arr[:,:,0], arr[:,:,1], arr[:,:,2], arr[:,:,3]
        
        # 精准匹配 Windows / Chrome / Edge 选中文本蓝色背景特征 (Blue 高，Red 低)
        blue_mask = (b > 150) & (r < 115) & (g < 165)
        
        # 将蓝色背景替换为纯白色 [255, 255, 255, 255]
        arr[blue_mask] = [255, 255, 255, 255]
        
        res_img = QImage(arr.data, w, h, w * 4, QImage.Format.Format_ARGB32)
        return QPixmap.fromImage(res_img)
    except Exception:
        return pixmap

# ==================== GitHub 开源长截图缝合引擎 ====================
class ImageStitcher:
    """基于 OpenCV 模板匹配 (Template Matching) 的动态滚动长截图图像缝合算法"""
    def __init__(self, first_bgra_arr):
        self.canvas = first_bgra_arr.copy()
        self.last_frame = first_bgra_arr.copy()

    def add_frame(self, new_bgra_arr):
        if not HAS_OPENCV or not HAS_NUMPY:
            return False

        try:
            h, w = self.last_frame.shape[:2]
            if h < 30 or w < 30:
                return False

            # 转为灰度加速匹配
            gray_last = cv2.cvtColor(self.last_frame, cv2.COLOR_BGRA2GRAY)
            gray_new = cv2.cvtColor(new_bgra_arr, cv2.COLOR_BGRA2GRAY)

            # 取上一帧底部 K 行作为重叠区模板
            k = max(60, int(h * 0.2))
            template = gray_last[h - k:, :]

            # 在当前帧中搜索该模板的位置
            res = cv2.matchTemplate(gray_new, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            # 匹配置信度阈值
            if max_val < 0.70:
                return False

            match_y = max_loc[1]
            # 滚动位移 = 帧高 - 模板高 - 匹配到的起始行
            shift_y = h - k - match_y
            if shift_y < 4:
                return False

            # 只拼接当前帧底部新露出的像素条
            new_strip = new_bgra_arr[h - shift_y:, :, :]
            self.canvas = np.vstack((self.canvas, new_strip))
            self.last_frame = new_bgra_arr.copy()
            return True
        except Exception:
            return False

    def get_result_pixmap(self):
        h, w, c = self.canvas.shape
        qimg = QImage(self.canvas.data, w, h, w * c, QImage.Format.Format_ARGB32)
        return QPixmap.fromImage(qimg)

# ==================== 0. 语言配置（15 种流行语言） ====================
LANGUAGES = [
    ("zh-CN", "中文",             "中",   "ZH"),
    ("en",    "English",          "英",   "EN"),
    ("ja",    "日本語",            "日",   "JA"),
    ("ko",    "한국어",            "韩",   "KO"),
    ("fr",    "Français",         "法",   "FR"),
    ("de",    "Deutsch",          "德",   "DE"),
    ("es",    "Español",          "西",   "ES"),
    ("ru",    "Русский",          "俄",   "RU"),
    ("pt",    "Português",        "葡",   "PT"),
    ("it",    "Italiano",         "意",   "IT"),
    ("ar",    "العربية",          "阿",   "AR"),
    ("hi",    "हिन्दी",            "印",   "HI"),
    ("th",    "ไทย",              "泰",   "TH"),
    ("vi",    "Tiếng Việt",       "越",   "VI"),
    ("id",    "Bahasa Indonesia", "印尼", "ID"),
]
LANG_SHORT = {code: short for code, _, short, _ in LANGUAGES}
LANG_NAME = {code: name for code, name, _, _ in LANGUAGES}
DEFAULT_TARGET = "en"

BING_CODE = {code: ("zh-Hans" if code == "zh-CN" else code) for code, _, _, _ in LANGUAGES}

MYMEMORY_CODE = {
    "zh-CN": "zh-CN", "en": "en-GB", "ja": "ja-JP", "ko": "ko-KR",
    "fr": "fr-FR", "de": "de-DE", "es": "es-ES", "ru": "ru-RU",
    "pt": "pt-PT", "it": "it-IT", "ar": "ar-SA", "hi": "hi-IN",
    "th": "th-TH", "vi": "vi-VN", "id": "id-ID",
}

# ==================== 背景颜色配置 (70% 透明度) ====================
DEFAULT_BG = "#1C1E24"
BG_COLORS = [
    ("暗夜黑", "#1C1E24"), ("石墨灰", "#455A64"), ("藏青",   "#16324F"), ("靛蓝",   "#3949AB"),
    ("天蓝",   "#039BE5"), ("青碧",   "#00897B"), ("翠绿",   "#43A047"), ("草木绿", "#7CB342"),
    ("柠檬黄", "#FDD835"), ("琥珀",   "#FFB300"), ("橙红",   "#F4511E"), ("中国红", "#C62828"),
    ("玫红",   "#D81B60"), ("樱花粉", "#F48FB1"), ("紫罗兰", "#8E24AA"), ("薰衣草", "#9575CD"),
    ("咖啡",   "#6D4C41"), ("米白",   "#F5F0E1"), ("浅灰",   "#E0E0E0"), ("纯白",   "#FFFFFF"),
]
BG_OPACITY = 0.7

def _hex_to_rgb(hex_color: str):
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

def _is_light_color(hex_color: str) -> bool:
    r, g, b = _hex_to_rgb(hex_color)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) > 150

_JA_RE = re.compile(r'[぀-ヿ]')
_KO_RE = re.compile(r'[가-힯]')
_AR_RE = re.compile(r'[؀-ۿ]')
_RU_RE = re.compile(r'[Ѐ-ӿ]')
_TH_RE = re.compile(r'[฀-๿]')
_HI_RE = re.compile(r'[ऀ-ॿ]')
_VI_RE = re.compile(r'[ĂăÂâĐđÊêÔôƠơƯư]')

@lru_cache(maxsize=2048)
def detect_lang(text: str) -> str:
    if _JA_RE.search(text): return "ja"
    if _KO_RE.search(text): return "ko"
    if _AR_RE.search(text): return "ar"
    if _TH_RE.search(text): return "th"
    if _HI_RE.search(text): return "hi"
    if _RU_RE.search(text): return "ru"
    if _VI_RE.search(text): return "vi"
    if _CHINESE_RE.search(text): return "zh-CN"
    return "en"

_TRANSLATOR_SESSION = requests.Session()
_TRANSLATOR_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Accept": "*/*",
})

_BING_TOKEN_CACHE = {"ig": None, "iid": None, "key": None, "token": None, "expires": 0.0}
_BING_TOKEN_LOCK = threading.Lock()

def _get_bing_token(force_refresh: bool = False):
    now = time.time()
    with _BING_TOKEN_LOCK:
        if (not force_refresh and _BING_TOKEN_CACHE["token"]
                and now < _BING_TOKEN_CACHE["expires"]):
            return (_BING_TOKEN_CACHE["ig"], _BING_TOKEN_CACHE["iid"],
                    _BING_TOKEN_CACHE["key"], _BING_TOKEN_CACHE["token"])
        try:
            resp = _TRANSLATOR_SESSION.get("https://cn.bing.com/translator", timeout=(2, 4))
            html = resp.text
            ig = re.search(r'IG:"([0-9A-F]+)"', html)
            iid = re.search(r'data-iid="(translator\.\d+)"', html)
            tok = re.search(r'params_AbusePreventionHelper\s*=\s*\[(\d+),"([^"]+)",\d+\]', html)
            if ig and iid and tok:
                _BING_TOKEN_CACHE.update({
                    "ig": ig.group(1), "iid": iid.group(1),
                    "key": tok.group(1), "token": tok.group(2),
                    "expires": now + 1800,
                })
                return (ig.group(1), iid.group(1), tok.group(1), tok.group(2))
        except Exception:
            pass
        return None

def check_internet(timeout=1.5):
    for host in [("223.5.5.5", 53), ("114.114.114.114", 53), ("8.8.8.8", 53)]:
        try:
            socket.create_connection(host, timeout=timeout)
            return True
        except OSError:
            continue
    return False

def check_network_services(timeout=2.0):
    if check_internet(timeout=1.0):
        return True
    
    urls = ["https://www.baidu.com", "https://cn.bing.com"]
    for url in urls:
        try:
            req = urllib.request.Request(url, method="GET")
            req.add_header("User-Agent", "Mozilla/5.0")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            continue
    return False

# ==================== 1. 智能离线数据库 ====================
def _app_data_dir(exe_dir: str) -> str:
    """跨平台应用数据目录：Windows 用 %LOCALAPPDATA%，macOS 用 ~/Library/Application Support。"""
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_NAME)
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA", exe_dir), APP_NAME)
    return os.path.join(os.path.expanduser("~"), ".local", "share", APP_NAME)

class LocalSQLiteDict:
    def __init__(self):
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            if hasattr(sys, '_MEIPASS'):
                self.resource_dir = sys._MEIPASS
                self.data_dir = _app_data_dir(exe_dir)
                os.makedirs(self.data_dir, exist_ok=True)
            else:
                self.resource_dir = exe_dir
                self.data_dir = exe_dir
        else:
            self.resource_dir = os.path.dirname(os.path.abspath(__file__))
            self.data_dir = self.resource_dir

        self.db_path = os.path.join(self.data_dir, "stardict.db")

        csv_candidates = [
            os.path.join(self.data_dir, "stardict.csv"),
            os.path.join(self.resource_dir, "stardict.csv"),
            os.path.join(self.resource_dir, "_internal", "stardict.csv"),
        ]
        if getattr(sys, 'frozen', False):
            csv_candidates.append(os.path.join(os.path.dirname(sys.executable), "stardict.csv"))
        self.csv_path = None
        for p in csv_candidates:
            if os.path.exists(p):
                self.csv_path = p
                break
        if not self.csv_path:
            self.csv_path = os.path.join(self.data_dir, "stardict.csv")

        self.conn = None
        self.init_database()

    def _apply_query_pragmas(self, conn):
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA mmap_size=268435456")
        except Exception:
            pass

    def init_database(self):
        if os.path.exists(self.db_path):
            try:
                self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
                self._apply_query_pragmas(self.conn)
                self.init_cache_table()
                return
            except Exception:
                pass

        if os.path.exists(self.csv_path):
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute('CREATE TABLE IF NOT EXISTS stardict (word TEXT PRIMARY KEY, phonetic TEXT, translation TEXT)')

                with open(self.csv_path, 'r', encoding='utf-8', errors='ignore') as f:
                    reader = csv.DictReader(f)
                    batch = []
                    for row in reader:
                        w = row.get('word', '').strip().lower()
                        p = row.get('phonetic', '')
                        t = row.get('translation', '')
                        if w: batch.append((w, p, t))
                        if len(batch) >= 20000:
                            cursor.executemany('INSERT OR REPLACE INTO stardict VALUES (?,?,?)', batch)
                            batch = []
                    if batch:
                        cursor.executemany('INSERT OR REPLACE INTO stardict VALUES (?,?,?)', batch)

                conn.commit()
                conn.close()
                self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
                self._apply_query_pragmas(self.conn)
                self.init_cache_table()
            except Exception as e:
                print(f"数据库转换提示: {e}")

    def init_cache_table(self):
        if not self.conn: return
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS translate_cache (
                    cache_key TEXT PRIMARY KEY,
                    result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            self.conn.commit()
        except Exception:
            pass

    def get_setting(self, key: str, default=None):
        if not self.conn: return default
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ? LIMIT 1", (key,))
            row = cursor.fetchone()
            return row[0] if row else default
        except Exception:
            return default

    def set_setting(self, key: str, value: str):
        if not self.conn: return
        try:
            cursor = self.conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
            self.conn.commit()
        except Exception:
            pass

    def query_cache(self, cache_key: str):
        if not self.conn: return None
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT result FROM translate_cache WHERE cache_key = ? LIMIT 1", (cache_key,))
            row = cursor.fetchone()
            if row and row[0]: return row[0]
        except Exception:
            pass
        return None

    def save_cache(self, cache_key: str, result: str):
        if not self.conn: return
        try:
            cursor = self.conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO translate_cache (cache_key, result) VALUES (?, ?)', (cache_key, result))
            self.conn.commit()
        except Exception:
            pass

    def query(self, word: str):
        if not self.conn: return None
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT translation, phonetic FROM stardict WHERE word = ? LIMIT 1", (word.lower().strip(),))
            row = cursor.fetchone()
            if row and row[0]:
                translation, phonetic = row[0], row[1]
                phonetic_str = f"[{phonetic}] " if phonetic else ""
                clean_trans = translation.replace('\n', '； ')
                return f"{phonetic_str}{clean_trans}"
        except Exception:
            pass
        return None

    def fuzzy_query(self, word: str):
        if not self.conn: return None
        try:
            cursor = self.conn.cursor()
            like_pattern = f"%{word.lower().strip()}%"
            cursor.execute("SELECT translation, phonetic FROM stardict WHERE word LIKE ? LIMIT 1", (like_pattern,))
            row = cursor.fetchone()
            if row and row[0]:
                translation, phonetic = row[0], row[1]
                phonetic_str = f"[{phonetic}] " if phonetic else ""
                clean_trans = translation.replace('\n', '； ')
                return f"≈ {phonetic_str}{clean_trans}"
        except Exception:
            pass
        return None

sqlite_service = LocalSQLiteDict()

# ==================== 2. Windows 原生 C API 取词与消蓝 ====================
VK_CONTROL = 0x11
VK_C = 0x43
VK_ESCAPE = 0x1B
VK_LEFT = 0x25
KEYEVENTF_KEYUP = 0x0002

def fast_copy():
    if sys.platform == "win32":
        user32 = ctypes.windll.user32
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_C, 0, 0, 0)
        user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    elif sys.platform == "darwin":
        pyautogui.hotkey("command", "c")
    else:
        pyautogui.hotkey("ctrl", "c")

def force_deselect_text():
    try:
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            pt = ctypes.wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            hwnd = user32.WindowFromPoint(pt)
            if hwnd:
                root_hwnd = user32.GetAncestor(hwnd, 2)
                if root_hwnd:
                    user32.SetForegroundWindow(root_hwnd)
                    time.sleep(0.06)

            user32.keybd_event(VK_ESCAPE, 0, 0, 0)
            user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(VK_LEFT, 0, 0, 0)
            user32.keybd_event(VK_LEFT, 0, KEYEVENTF_KEYUP, 0)
        else:
            pyautogui.press("esc")
            time.sleep(0.03)
            pyautogui.press("left")
    except Exception:
        pass

class GlobalSignals(QObject):
    text_selected = pyqtSignal(str, int, int)
    hide_signal = pyqtSignal()

signals = GlobalSignals()

# ==================== 钉图悬浮窗口 ====================
class PinnedImageWindow(QWidget):
    def __init__(self, pixmap, pos):
        super().__init__()
        self.orig_pixmap = pixmap
        self.current_scale = 1.0
        self.is_dragging = False
        self.drag_offset = QPoint()
        self.init_ui(pos)

    def init_ui(self, pos):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        saved_bg = (sqlite_service.get_setting("bg_color", DEFAULT_BG) or "").strip()
        bg_color = saved_bg if re.fullmatch(r'#[0-9A-Fa-f]{6}', saved_bg) else DEFAULT_BG

        r, g, b = _hex_to_rgb(bg_color)
        light = _is_light_color(bg_color)

        border = "rgba(0, 0, 0, 0.22)" if light else "rgba(255, 255, 255, 0.22)"
        close_color = "#1F1F1F" if light else "#A0A0A0"
        close_hover = "#E53935" if light else "#FF5252"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.container = QWidget(self)
        self.container.setStyleSheet(f"""
            QWidget {{
                background-color: rgba({r}, {g}, {b}, {BG_OPACITY});
                border-radius: 8px;
                border: 1px solid {border};
            }}
        """)
        c_layout = QVBoxLayout(self.container)
        c_layout.setContentsMargins(3, 3, 3, 3)
        c_layout.setSpacing(2)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.addStretch()
        close_btn = QPushButton("✕", self.container)
        close_btn.setFixedSize(16, 16)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {close_color};
                border: none;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                color: {close_hover};
            }}
        """)
        close_btn.clicked.connect(self.close)
        top_bar.addWidget(close_btn)
        c_layout.addLayout(top_bar)

        self.img_label = QLabel(self.container)
        self.img_label.setPixmap(self.orig_pixmap)
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c_layout.addWidget(self.img_label)

        layout.addWidget(self.container)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 140))
        shadow.setOffset(0, 2)
        self.container.setGraphicsEffect(shadow)

        self.move(pos)
        self.resize(self.sizeHint())

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            op = self.windowOpacity()
            if delta > 0:
                op = min(1.0, op + 0.08)
            else:
                op = max(0.2, op - 0.08)
            self.setWindowOpacity(op)
        else:
            delta = event.angleDelta().y()
            if delta > 0:
                self.current_scale = min(3.0, self.current_scale + 0.1)
            else:
                self.current_scale = max(0.2, self.current_scale - 0.1)
            
            new_w = int(self.orig_pixmap.width() * self.current_scale)
            new_h = int(self.orig_pixmap.height() * self.current_scale)
            scaled_pixmap = self.orig_pixmap.scaled(
                new_w, new_h, 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            )
            self.img_label.setPixmap(scaled_pixmap)
            self.img_label.adjustSize()
            self.container.adjustSize()
            self.adjustSize()
            self.resize(self.sizeHint())

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(28, 30, 36, 0.98);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item { padding: 5px 20px; border-radius: 4px; }
            QMenu::item:selected { background-color: rgba(13, 110, 253, 0.6); }
        """)
        copy_act = menu.addAction("复制图片")
        save_act = menu.addAction("另存为...")
        menu.addSeparator()
        close_act = menu.addAction("销毁钉图")

        action = menu.exec(event.globalPos())
        if action == copy_act:
            QApplication.clipboard().setImage(self.orig_pixmap.toImage())
        elif action == save_act:
            file_path, _ = QFileDialog.getSaveFileName(
                self, "另存为截图", "Screenshot.png", "PNG Image (*.png);;JPEG Image (*.jpg)"
            )
            if file_path:
                self.orig_pixmap.save(file_path)
        elif action == close_act:
            self.close()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.is_dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.is_dragging = False

# ==================== 全屏截图遮罩与长截图工具栏 ====================
class SnippingOverlay(QWidget):
    _scroll_pending = pyqtSignal()
    _long_finish = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

        screen = QApplication.primaryScreen()
        self.dpr = screen.devicePixelRatio()
        raw_pixmap = screen.grabWindow(0)
        self.full_screen_pixmap = remove_blue_selection_bg(raw_pixmap)
        self.setGeometry(screen.geometry())

        self.start_point = QPoint()
        self.end_point = QPoint()
        self.is_selecting = False
        self.selected_rect = QRect()

        # 长截图缝合相关状态
        self.is_long_snapping = False
        self.stitcher = None
        self._finish_bar = None
        self._finish_btn = None
        self._mouse_listener = None
        self._key_listener = None
        self._capturing = False
        self._last_capture_ts = 0.0

        # 全局滚轮：滚动时节流抓帧，停止后补最后一帧（跨线程信号 -> 主线程定时器）
        self._scroll_pending.connect(self._on_scroll_pending)
        self._long_finish.connect(self.finish_long_snip)
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(150)  # 滚动停止 150ms 后补抓最后一帧
        self._debounce_timer.timeout.connect(self._capture_and_stitch)

        # 截图工具栏
        self.toolbar = QWidget(self)
        self.toolbar.setStyleSheet("""
            QWidget {
                background-color: rgba(28, 30, 36, 0.95);
                border-radius: 6px;
                border: 1px solid rgba(255, 255, 255, 0.25);
            }
            QPushButton {
                background: transparent;
                color: #FFFFFF;
                border: none;
                padding: 5px 10px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(13, 110, 253, 0.7);
                border-radius: 4px;
            }
        """)
        tb_layout = QHBoxLayout(self.toolbar)
        tb_layout.setContentsMargins(6, 4, 6, 4)

        save_btn = QPushButton("另存为", self.toolbar)
        save_btn.clicked.connect(self.save_as)
        tb_layout.addWidget(save_btn)

        pin_btn = QPushButton("钉图", self.toolbar)
        pin_btn.clicked.connect(self.pin_image)
        tb_layout.addWidget(pin_btn)

        # 新增：长截图缝合按钮
        self.long_btn = QPushButton("长截图", self.toolbar)
        self.long_btn.clicked.connect(self.start_long_snip)
        tb_layout.addWidget(self.long_btn)

        copy_btn = QPushButton("复制", self.toolbar)
        copy_btn.clicked.connect(self.copy_and_close)
        tb_layout.addWidget(copy_btn)

        self.toolbar.hide()

    def closeEvent(self, event):
        global _snip_overlay_instance
        self._stop_long_listeners()
        self._debounce_timer.stop()
        if self._finish_bar is not None:
            self._finish_bar.close()
            self._finish_bar = None
        _snip_overlay_instance = None
        super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if not self.selected_rect.isEmpty() or self.toolbar.isVisible():
                self.selected_rect = QRect()
                self.start_point = QPoint()
                self.end_point = QPoint()
                self.is_selecting = False
                self.toolbar.hide()
                self.update()
            else:
                self.close()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if self.is_long_snapping:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_point = event.position().toPoint()
            self.end_point = self.start_point
            self.selected_rect = QRect(self.start_point, self.end_point).normalized()
            self.is_selecting = True
            self.toolbar.hide()
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_selecting and not self.is_long_snapping:
            self.end_point = event.position().toPoint()
            self.selected_rect = QRect(self.start_point, self.end_point).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.is_selecting:
            self.is_selecting = False
            self.selected_rect = QRect(self.start_point, self.end_point).normalized()
            if self.selected_rect.width() > 10 and self.selected_rect.height() > 10:
                self.show_toolbar()
            self.update()

    def show_toolbar(self):
        tb_size = self.toolbar.sizeHint()
        tb_x = self.selected_rect.right() - tb_size.width()
        tb_y = self.selected_rect.bottom() + 8

        screen_geo = self.geometry()
        if tb_y + tb_size.height() > screen_geo.bottom():
            tb_y = self.selected_rect.top() - tb_size.height() - 8
        if tb_x < screen_geo.left():
            tb_x = screen_geo.left() + 8

        self.toolbar.move(tb_x, tb_y)
        self.toolbar.show()

    def get_cropped_bgra(self, pixmap):
        src_rect = QRect(
            int(self.selected_rect.x() * self.dpr),
            int(self.selected_rect.y() * self.dpr),
            int(self.selected_rect.width() * self.dpr),
            int(self.selected_rect.height() * self.dpr)
        )
        cropped = pixmap.copy(src_rect)
        qimg = cropped.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        w, h = qimg.width(), qimg.height()
        ptr = qimg.bits()
        ptr.setsize(h * w * 4)
        return np.frombuffer(ptr, np.uint8).reshape((h, w, 4)).copy()

    def start_long_snip(self):
        """开启长截图：隐藏遮罩，用全局滚轮监听触发抓帧"""
        if not HAS_OPENCV or not HAS_NUMPY:
            QMessageBox.warning(self, "提示", "长截图功能需要安装 opencv-python，请运行 pip install opencv-python numpy 后使用！")
            return

        self.is_long_snapping = True
        self.toolbar.hide()

        # 准备拼接第一帧
        first_bgra = self.get_cropped_bgra(self.full_screen_pixmap)
        self.stitcher = ImageStitcher(first_bgra)

        # 隐藏遮罩窗口，让滚轮事件落到被截取的页面上
        self.hide()

        # 显示悬浮“完成”按钮
        self._show_finish_bar()

        # 启动全局滚轮 / 键盘监听
        self._start_long_listeners()

    def _show_finish_bar(self):
        """长截图期间显示一个不遮挡内容的悬浮完成按钮"""
        if self._finish_bar is None:
            self._finish_bar = QWidget()
            self._finish_bar.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool
            )
            self._finish_bar.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self._finish_bar.setStyleSheet("""
                QPushButton {
                    background-color: rgba(13, 110, 253, 0.92);
                    color: #FFFFFF;
                    border: none;
                    border-radius: 14px;
                    padding: 7px 18px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(13, 110, 253, 1.0);
                }
            """)
            layout = QHBoxLayout(self._finish_bar)
            layout.setContentsMargins(0, 0, 0, 0)
            self._finish_btn = QPushButton("完成长截图 (Esc)", self._finish_bar)
            self._finish_btn.clicked.connect(self.finish_long_snip)
            layout.addWidget(self._finish_btn)
            self._finish_bar.adjustSize()

        screen = QApplication.primaryScreen()
        geo = screen.geometry()
        self._finish_bar.move(geo.left() + (geo.width() - self._finish_bar.width()) // 2, geo.top() + 16)
        self._finish_bar.show()
        self._finish_bar.raise_()

    def _start_long_listeners(self):
        self._stop_long_listeners()
        self._mouse_listener = mouse.Listener(on_scroll=self._on_global_scroll)
        self._mouse_listener.start()
        self._key_listener = keyboard.Listener(on_press=self._on_long_key_press)
        self._key_listener.start()

    def _stop_long_listeners(self):
        for attr in ('_mouse_listener', '_key_listener'):
            listener = getattr(self, attr, None)
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    pass
                setattr(self, attr, None)

    def _on_global_scroll(self, _x, _y, _dx, _dy):
        """全局滚轮回调（pynput 线程）：触发去抖抓帧"""
        if self.is_long_snapping:
            self._scroll_pending.emit()

    def _on_long_key_press(self, key):
        """全局按键回调（pynput 线程）：Esc / Enter 完成长截图"""
        if key in (Key.esc, Key.enter) and self.is_long_snapping:
            self._long_finish.emit()

    def _on_scroll_pending(self):
        """主线程：滚动时节流抓帧，并在停止后补最后一帧"""
        if time.monotonic() - self._last_capture_ts >= 0.10:
            self._capture_and_stitch()
        self._debounce_timer.start()

    def _finish_bar_overlaps_region(self):
        """完成按钮是否与选区重叠（重叠时才需要在抓帧前隐藏）"""
        if self._finish_bar is None:
            return False
        g = self._finish_bar.geometry()
        return self.selected_rect.intersects(QRect(g.x(), g.y(), g.width(), g.height()))

    def _capture_and_stitch(self):
        """主线程：抓取选区并尝试缝合（节流 + 去抖后调用）"""
        if not self.is_long_snapping or not self.stitcher or self._capturing:
            return
        self._capturing = True
        self._last_capture_ts = time.monotonic()
        try:
            # 完成按钮若与选区重叠，抓帧前临时隐藏，避免被截进画面
            need_hide = (self._finish_bar is not None and self._finish_bar.isVisible()
                         and self._finish_bar_overlaps_region())
            if need_hide:
                self._finish_bar.hide()
                QApplication.processEvents()
                time.sleep(0.03)

            screen = QApplication.primaryScreen()
            cur_screen_pixmap = remove_blue_selection_bg(screen.grabWindow(0))
            cur_bgra = self.get_cropped_bgra(cur_screen_pixmap)
            self.stitcher.add_frame(cur_bgra)

            if need_hide and self._finish_bar is not None:
                self._finish_bar.show()
                self._finish_bar.raise_()
        except Exception:
            pass
        finally:
            self._capturing = False

    def finish_long_snip(self):
        """长截图完成：停止监听，生成长图并置顶钉图"""
        self._stop_long_listeners()
        self._debounce_timer.stop()
        if self._finish_bar is not None:
            self._finish_bar.hide()

        if not self.is_long_snapping:
            self.close()
            return

        self.is_long_snapping = False

        if self.stitcher:
            result_pixmap = self.stitcher.get_result_pixmap()
            result_pixmap.setDevicePixelRatio(self.dpr)  # 按逻辑尺寸显示，避免放大成全屏
            self.auto_save_to_screenshots(result_pixmap)
            QApplication.clipboard().setImage(result_pixmap.toImage())

            # 自动生成钉图卡片置顶在桌面上
            pinned_win = PinnedImageWindow(result_pixmap, self.selected_rect.topLeft())
            global_pinned_windows.append(pinned_win)
            pinned_win.show()

        self.close()

    def get_cropped_pixmap(self):
        src_rect = QRect(
            int(self.selected_rect.x() * self.dpr),
            int(self.selected_rect.y() * self.dpr),
            int(self.selected_rect.width() * self.dpr),
            int(self.selected_rect.height() * self.dpr)
        )
        cropped = self.full_screen_pixmap.copy(src_rect)
        cropped.setDevicePixelRatio(self.dpr)
        return cropped

    def auto_save_to_screenshots(self, pixmap):
        try:
            screenshots_dir = os.path.join(os.path.expanduser('~'), 'Pictures', 'Screenshots')
            os.makedirs(screenshots_dir, exist_ok=True)
            filename = f"Screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
            full_path = os.path.join(screenshots_dir, filename)
            pixmap.save(full_path, "PNG")
        except Exception:
            pass

    def copy_and_close(self):
        pixmap = self.get_cropped_pixmap()
        QApplication.clipboard().setImage(pixmap.toImage())
        self.auto_save_to_screenshots(pixmap)
        self.close()

    def save_as(self):
        pixmap = self.get_cropped_pixmap()
        file_path, _ = QFileDialog.getSaveFileName(
            self, "另存为截图", "Screenshot.png", "PNG Image (*.png);;JPEG Image (*.jpg)"
        )
        if file_path:
            pixmap.save(file_path)
            QApplication.clipboard().setImage(pixmap.toImage())
            self.close()

    def pin_image(self):
        pixmap = self.get_cropped_pixmap()
        self.auto_save_to_screenshots(pixmap)
        QApplication.clipboard().setImage(pixmap.toImage())

        pinned_win = PinnedImageWindow(pixmap, self.selected_rect.topLeft())
        global_pinned_windows.append(pinned_win)
        pinned_win.show()
        self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        
        if not self.is_long_snapping:
            painter.drawPixmap(0, 0, self.full_screen_pixmap)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

            if self.selected_rect.isEmpty():
                painter.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
                painter.setPen(QColor(255, 255, 255))
                tip = "【截图模式】按住鼠标左键框选 | 松开弹出工具栏 | 按 ESC 取消选区/退出"
                painter.drawText(QRect(0, 24, self.width(), 30), Qt.AlignmentFlag.AlignCenter, tip)

            if not self.selected_rect.isEmpty() and self.selected_rect.isValid():
                painter.drawPixmap(self.selected_rect, self.full_screen_pixmap, self.selected_rect)

                pen = QPen(QColor(13, 110, 253), 2)
                painter.setPen(pen)
                painter.drawRect(self.selected_rect)

                w = self.selected_rect.width()
                h = self.selected_rect.height()
                size_text = f" {w} × {h} "
                
                painter.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
                txt_x = self.selected_rect.left()
                txt_y = max(10, self.selected_rect.top() - 22)
                
                fm = painter.fontMetrics()
                txt_w = fm.horizontalAdvance(size_text) + 8
                txt_h = 20
                
                painter.fillRect(QRect(txt_x, txt_y, txt_w, txt_h), QColor(28, 30, 36, 220))
                painter.setPen(QColor(138, 180, 248))
                painter.drawText(QRect(txt_x, txt_y, txt_w, txt_h), Qt.AlignmentFlag.AlignCenter, size_text)

# ==================== 3. 极速并发翻译线程 ====================
class FastTranslateWorker(QThread):
    finished_signal = pyqtSignal(str, str, str, float, str)

    def __init__(self, text: str, target_lang: str = DEFAULT_TARGET):
        super().__init__()
        self.text = text
        self.target_lang = target_lang

    def _emit(self, src: str, tgt: str, result: str, t0: float, origin: str):
        self.finished_signal.emit(src, tgt, result, time.perf_counter() - t0, origin)

    def run(self):
        global IS_ONLINE
        t0 = time.perf_counter()
        clean_text = self.text.strip().lower()
        _cache = TRANSLATE_CACHE

        src_lang = detect_lang(self.text)
        tgt_lang = self.target_lang
        if src_lang == tgt_lang:
            tgt_lang = "zh-CN" if tgt_lang != "zh-CN" else "en"

        cache_key = f"{tgt_lang}:{clean_text}"

        if cache_key in _cache:
            self._emit(src_lang, tgt_lang, _cache[cache_key], t0, "缓存")
            return

        cached_res = sqlite_service.query_cache(cache_key)
        if cached_res:
            _cache[cache_key] = cached_res
            self._emit(src_lang, tgt_lang, cached_res, t0, "缓存")
            return

        if tgt_lang == "zh-CN":
            db_res = sqlite_service.query(clean_text)
            if db_res:
                _cache[cache_key] = db_res
                sqlite_service.save_cache(cache_key, db_res)
                self._emit(src_lang, tgt_lang, db_res, t0, "离线词库")
                return

        translated_result = self._fetch_online(src_lang, tgt_lang)
        
        if (translated_result and translated_result.strip().lower() == clean_text
                and tgt_lang != "zh-CN"):
            tgt_lang = "zh-CN"
            cache_key = f"{tgt_lang}:{clean_text}"
            if cache_key in _cache:
                self._emit(src_lang, tgt_lang, _cache[cache_key], t0, "缓存")
                return
            translated_result = self._fetch_online(src_lang, tgt_lang)

        if translated_result:
            IS_ONLINE = True
            _cache[cache_key] = translated_result
            sqlite_service.save_cache(cache_key, translated_result)
            self._emit(src_lang, tgt_lang, translated_result, t0, "在线")
            return

        if tgt_lang == "zh-CN":
            fuzzy_res = sqlite_service.fuzzy_query(clean_text)
            if fuzzy_res:
                _cache[cache_key] = fuzzy_res
                self._emit(src_lang, tgt_lang, fuzzy_res, t0, "离线词库")
                return

        IS_ONLINE = check_network_services(timeout=1.5)
        if not IS_ONLINE:
            final_msg = "【离线模式】未找到该词条的本地翻译。\n提示：离线词库仅支持英➔中单词查询，其余语言方向需联网使用。"
        else:
            final_msg = "网络请求失败，且离线词库未收录该词条。请稍后重试。"

        self._emit(src_lang, tgt_lang, final_msg, t0, "失败")

    def _fetch_online(self, src_lang, tgt_lang):
        text = self.text
        session = _TRANSLATOR_SESSION

        def fetch_bing():
            bing_tgt = BING_CODE.get(tgt_lang, "en")
            for attempt in range(2):
                creds = _get_bing_token(force_refresh=(attempt > 0))
                if not creds: return None
                ig, iid, key, token = creds
                try:
                    url = f"https://cn.bing.com/ttranslatev3?isVertical=1&IG={ig}&IID={iid}.1"
                    resp = session.post(url, data={
                        "fromLang": "auto-detect", "text": text,
                        "to": bing_tgt, "token": token, "key": key,
                    }, timeout=(2, 4))
                    if resp.status_code != 200: return None
                    data = resp.json()
                    if isinstance(data, dict): continue
                    if data and data[0].get("translations"):
                        res = data[0]["translations"][0].get("text", "")
                        if res and res.strip(): return res
                    return None
                except Exception:
                    return None
            return None

        def fetch_google():
            try:
                return GoogleTranslator(source='auto', target=tgt_lang).translate(text)
            except Exception:
                return None

        def fetch_mymemory():
            try:
                mm_src = MYMEMORY_CODE.get(src_lang)
                mm_tgt = MYMEMORY_CODE.get(tgt_lang)
                if not mm_src or not mm_tgt: return None
                return MyMemoryTranslator(source=mm_src, target=mm_tgt).translate(text)
            except Exception:
                return None

        translated_result = None
        futures = [
            _TRANSLATOR_POOL.submit(fetch_bing),
            _TRANSLATOR_POOL.submit(fetch_google),
            _TRANSLATOR_POOL.submit(fetch_mymemory)
        ]
        try:
            for future in as_completed(futures, timeout=4.5):
                try:
                    res = future.result()
                    if res and len(res.strip()) > 0 and "INVALID SOURCE LANGUAGE" not in res:
                        translated_result = res
                        break
                except Exception:
                    continue
        except Exception:
            pass

        return translated_result

# ==================== 4. 强力拖拽与对角拉伸容器 ====================
class DraggableResizableContainer(QWidget):
    def __init__(self, parent_win):
        super().__init__(parent_win)
        self.parent_win = parent_win
        self.is_dragging = False
        self.is_resizing = False
        self.resize_margin = 12
        self.drag_position = QPoint()
        self.resize_start_pos = QPoint()
        self.resize_start_size = None
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            rect = self.rect()

            if (rect.right() - pos.x() <= self.resize_margin and
                rect.bottom() - pos.y() <= self.resize_margin):
                self.is_resizing = True
                self.resize_start_pos = event.globalPosition().toPoint()
                self.resize_start_size = self.parent_win.size()
            else:
                self.is_dragging = True
                self.drag_position = event.globalPosition().toPoint() - self.parent_win.frameGeometry().topLeft()
                self.parent_win.is_manually_moved = True
            event.accept()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        rect = self.rect()

        if (rect.right() - pos.x() <= self.resize_margin and
            rect.bottom() - pos.y() <= self.resize_margin):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

        if self.is_resizing and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self.resize_start_pos
            new_w = max(160, self.resize_start_size.width() + delta.x())
            new_h = max(70, self.resize_start_size.height() + delta.y())
            self.parent_win.resize(new_w, new_h)
            self.parent_win.is_manually_moved = True
            event.accept()
        elif self.is_dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.parent_win.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.is_dragging = False
        self.is_resizing = False
        self.setCursor(Qt.CursorShape.ArrowCursor)

# ==================== 5. 悬浮窗类 ====================
class FloatingWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.current_worker = None
        self.last_x = 0
        self.last_y = 0
        self.is_manually_moved = False
        self._menu_open = False
        self._last_text = None
        self._last_pos = None

        saved = sqlite_service.get_setting("target_lang", DEFAULT_TARGET)
        self.target_lang = saved if saved in LANG_SHORT else DEFAULT_TARGET

        saved_bg = (sqlite_service.get_setting("bg_color", DEFAULT_BG) or "").strip()
        self.bg_color = saved_bg if re.fullmatch(r'#[0-9A-Fa-f]{6}', saved_bg) else DEFAULT_BG
        self._last_html_text = None
        self._last_is_loading = False
        self.init_ui()

    def init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(180, 65)
        self.setWindowIcon(make_app_icon(32))

        self.container = DraggableResizableContainer(self)
        self.container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(3)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(5)

        self.lang_btn = QPushButton(self._pair_text("自"), self.container)
        self.lang_btn.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        self.lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_btn.setStyleSheet("""
            QPushButton {
                color: #D3E3FD;
                background-color: rgba(138, 180, 248, 0.16);
                border: 1px solid rgba(138, 180, 248, 0.35);
                border-radius: 9px;
                padding: 2px 8px;
            }
            QPushButton:hover {
                background-color: rgba(138, 180, 248, 0.30);
                color: #FFFFFF;
            }
            QPushButton:pressed {
                background-color: rgba(138, 180, 248, 0.42);
            }
        """)
        self.lang_btn.setToolTip("点击切换目标语言")
        self.lang_btn.clicked.connect(self.show_language_menu)
        title_row.addWidget(self.lang_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self.color_btn = QPushButton("▾", self.container)
        self.color_btn.setFont(QFont("Microsoft YaHei", 8))
        self.color_btn.setFixedSize(32, 20)
        self.color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color_btn.setToolTip("点击切换背景颜色")
        self.color_btn.clicked.connect(self.show_color_menu)
        title_row.addWidget(self.color_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self.snip_btn = QPushButton("截", self.container)
        self.snip_btn.setFont(QFont("Microsoft YaHei", 8))
        self.snip_btn.setFixedSize(28, 20)
        self.snip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.snip_btn.setToolTip("点击进入截图 / 钉图模式")
        self.snip_btn.clicked.connect(self.switch_to_screenshot_mode)
        title_row.addWidget(self.snip_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self.time_label = QLabel("", self.container)
        self.time_label.setFont(QFont("Microsoft YaHei", 8))
        self.time_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_row.addStretch(1)
        title_row.addWidget(self.time_label, 0, Qt.AlignmentFlag.AlignRight)

        layout.addLayout(title_row)

        self.label = QLabel(self.container)
        self.label.setFont(QFont("Microsoft YaHei", 10))
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setWordWrap(True)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.label)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.addWidget(self.container)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(14)
        shadow.setColor(QColor(0, 0, 0, 140))
        shadow.setOffset(0, 3)
        self.container.setGraphicsEffect(shadow)

        self._apply_bg_style()

    def switch_to_screenshot_mode(self):
        self.hide()
        QApplication.processEvents()
        time.sleep(0.18)
        force_deselect_text()
        time.sleep(0.10)
        launch_snipping()

    def _pair_text(self, src_short: str) -> str:
        return f"[ {src_short} ➔ {LANG_SHORT[self.target_lang]} ▾ ]"

    def show_language_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(28, 30, 36, 0.98);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 8px;
                padding: 6px;
            }
            QMenu::item { padding: 6px 26px 6px 18px; border-radius: 5px; }
            QMenu::item:selected { background-color: rgba(13, 110, 253, 0.55); }
            QMenu::item:checked { font-weight: bold; color: #8AB4F8; }
            QMenu::item:disabled { color: rgba(255, 255, 255, 0.4); }
        """)
        header = menu.addAction("选择目标语言（源语言自动识别）")
        header.setEnabled(False)
        menu.addSeparator()

        group = QActionGroup(menu)
        group.setExclusive(True)
        for code, name, short, _ in LANGUAGES:
            act = menu.addAction(f"{name}   {short}")
            act.setCheckable(True)
            act.setChecked(code == self.target_lang)
            act.setData(code)
            group.addAction(act)

        self._menu_open = True
        chosen = menu.exec(self.lang_btn.mapToGlobal(QPoint(0, self.lang_btn.height() + 4)))
        self._menu_open = False
        self.activateWindow()

        if chosen:
            self.set_target_language(chosen.data())

    def _apply_bg_style(self):
        r, g, b = _hex_to_rgb(self.bg_color)
        light = _is_light_color(self.bg_color)

        self._text_color = "#1F1F1F" if light else "#FFFFFF"
        self._loading_color = "rgba(0, 0, 0, 0.50)" if light else "#A0A0A0"
        subtext = "rgba(0, 0, 0, 0.45)" if light else "rgba(255, 255, 255, 0.45)"
        border = "rgba(0, 0, 0, 0.18)" if light else "rgba(255, 255, 255, 0.18)"
        sw_border = "rgba(0, 0, 0, 0.40)" if light else "rgba(255, 255, 255, 0.35)"
        sw_hover = "rgba(0, 0, 0, 0.70)" if light else "rgba(255, 255, 255, 0.70)"

        self.container.setStyleSheet(f"""
            QWidget {{
                background-color: rgba({r}, {g}, {b}, {BG_OPACITY});
                border-radius: 10px;
                border: 1px solid {border};
            }}
        """)
        self.time_label.setStyleSheet(f"color: {subtext}; background: transparent; border: none;")
        
        btn_style = f"""
            QPushButton {{
                color: {self._text_color};
                background-color: rgba({r}, {g}, {b}, {BG_OPACITY});
                border: 1px solid {sw_border};
                border-radius: 9px;
            }}
            QPushButton:hover {{
                border: 1px solid {sw_hover};
            }}
        """
        self.color_btn.setStyleSheet(btn_style)
        self.snip_btn.setStyleSheet(btn_style)

    def show_color_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(28, 30, 36, 0.98);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 8px;
                padding: 6px;
            }
            QMenu::item { padding: 6px 26px 6px 18px; border-radius: 5px; }
            QMenu::item:selected { background-color: rgba(13, 110, 253, 0.55); }
            QMenu::item:disabled { color: rgba(255, 255, 255, 0.4); }
        """)
        header = menu.addAction("选择背景颜色（70% 不透明度）")
        header.setEnabled(False)
        menu.addSeparator()

        grid_widget = QWidget(menu)
        grid_widget.setStyleSheet("background: transparent;")
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setSpacing(6)

        for idx, (name, hexcode) in enumerate(BG_COLORS):
            btn = QPushButton(grid_widget)
            btn.setFixedSize(30, 30)
            btn.setToolTip(name)
            r, g, b = _hex_to_rgb(hexcode)
            checked = hexcode.upper() == self.bg_color.upper()
            border = "2px solid #8AB4F8" if checked else "1px solid rgba(255, 255, 255, 0.30)"
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba({r}, {g}, {b}, {BG_OPACITY});
                    border: {border};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    border: 2px solid #8AB4F8;
                }}
            """)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, h=hexcode: self._on_color_chosen(menu, h))
            grid.addWidget(btn, idx // 4, idx % 4)

        grid_action = QWidgetAction(menu)
        grid_action.setDefaultWidget(grid_widget)
        menu.addAction(grid_action)

        self._menu_open = True
        menu.exec(self.color_btn.mapToGlobal(QPoint(0, self.color_btn.height() + 4)))
        self._menu_open = False
        self.activateWindow()

    def _on_color_chosen(self, menu, hexcode):
        menu.close()
        self.set_bg_color(hexcode)

    def set_bg_color(self, hexcode: str):
        if hexcode == self.bg_color: return
        self.bg_color = hexcode
        sqlite_service.set_setting("bg_color", hexcode)
        self._apply_bg_style()
        if self.isVisible() and self._last_html_text is not None:
            self.set_content_html(self._last_html_text, self._last_is_loading)

    def set_target_language(self, code: str):
        if code not in LANG_SHORT or code == self.target_lang: return
        self.target_lang = code
        sqlite_service.set_setting("target_lang", code)
        self.lang_btn.setText(self._pair_text("自"))
        if self.isVisible() and self._last_text:
            self.show_at(self._last_text, self.last_x, self.last_y, force=True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        new_max_w = max(130, self.container.width() - 20)
        self.label.setMaximumWidth(new_max_w)

    def adjust_position_safety(self, x: int, y: int):
        if self.is_manually_moved: return

        self.label.adjustSize()
        self.container.adjustSize()
        self.adjustSize()

        win_w = self.frameGeometry().width()
        win_h = self.frameGeometry().height()

        screen = QApplication.screenAt(QPoint(x, y))
        if not screen: screen = QApplication.primaryScreen()
        screen_geo = screen.availableGeometry()

        target_x = x + 12
        target_y = y + 12

        if target_x + win_w > screen_geo.right():
            target_x = x - win_w - 12
        if target_y + win_h > screen_geo.bottom():
            target_y = y - win_h - 12

        target_x = max(screen_geo.left(), min(target_x, screen_geo.right() - win_w))
        target_y = max(screen_geo.top(), min(target_y, screen_geo.bottom() - win_h))

        self.move(target_x, target_y)

    def set_content_html(self, content_text: str, is_loading: bool = False):
        self._last_html_text = content_text
        self._last_is_loading = is_loading
        text_color = self._loading_color if is_loading else self._text_color

        html_code = f"""
        <div style='color: {text_color}; font-size: 13px; font-weight: 500; line-height: 1.4;'>
            {content_text}
        </div>
        """
        self.label.setText(html_code)
        self.adjust_position_safety(self.last_x, self.last_y)

    def show_at(self, text: str, x: int, y: int, force: bool = False):
        if not force and self._last_text == text and self._last_pos == (x, y) and self.isVisible():
            return
        self._last_text = text
        self._last_pos = (x, y)

        self.last_x = x
        self.last_y = y
        self.is_manually_moved = False
        self.time_label.setText("")
        self.lang_btn.setText(self._pair_text("自"))
        self.set_content_html("查询中...", is_loading=True)
        self.show()
        self.activateWindow()

        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.terminate()

        self.current_worker = FastTranslateWorker(text, self.target_lang)
        self.current_worker.finished_signal.connect(self.update_result)
        self.current_worker.start()

    def update_result(self, src: str, tgt: str, result: str, elapsed: float, origin: str):
        self.lang_btn.setText(f"[ {LANG_SHORT.get(src, src)} ➔ {LANG_SHORT.get(tgt, tgt)} ▾ ]")
        if elapsed < 0.001:
            t_str = "<1 ms"
        elif elapsed < 1:
            t_str = f"{elapsed * 1000:.0f} ms"
        else:
            t_str = f"{elapsed:.2f} s"
        self.time_label.setText(f"{t_str} · {origin}")
        self.set_content_html(result)

    def changeEvent(self, event):
        if (event.type() == QEvent.Type.ActivationChange
                and not self.isActiveWindow() and not self._menu_open):
            self.hide()
        super().changeEvent(event)

# ==================== 6. 纯键盘 Alt 极速控制器 ====================
class PureAltController:
    def __init__(self, window_ref):
        self.window = window_ref
        self.enabled = True
        self.last_press_time = 0

    def on_key_press(self, key):
        if not self.enabled: return

        if key in (Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr):
            now = time.time()
            if now - self.last_press_time < 0.15: return
            self.last_press_time = now

            if self.window.isVisible():
                signals.hide_signal.emit()
            else:
                self.execute_capture()

    def execute_capture(self):
        kb_controller.release(Key.alt)
        kb_controller.release(Key.alt_l)
        kb_controller.release(Key.alt_r)

        x, y = pyautogui.position()

        try:
            old_clip = pyperclip.paste()
        except Exception:
            old_clip = ""

        fast_copy()
        
        selected_text = ""
        for _ in range(10):
            time.sleep(0.003)
            try:
                selected_text = pyperclip.paste().strip()
                if selected_text != old_clip:
                    break
            except Exception:
                pass

        if selected_text == old_clip:
            selected_text = ""

        try:
            pyperclip.copy(old_clip)
        except Exception:
            pass

        if selected_text and 1 <= len(selected_text) <= 500:
            signals.text_selected.emit(selected_text, int(x), int(y))

# ==================== 7. 系统托盘图标 ====================
def launch_snipping():
    global _snip_overlay_instance
    if _snip_overlay_instance is not None:
        try:
            _snip_overlay_instance.close()
        except Exception:
            pass
        _snip_overlay_instance = None

    _snip_overlay_instance = SnippingOverlay()
    _snip_overlay_instance.show()
    _snip_overlay_instance.raise_()
    _snip_overlay_instance.activateWindow()

def make_app_icon(size: int = 32) -> QIcon:
    """纯程序绘制应用图标（蓝色圆角方块 + 白色「译」），运行时零文件依赖。"""
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
    painter.setFont(QFont(font_family, max(8, int(size * 0.44)), QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "译")
    painter.end()
    return QIcon(pixmap)

def create_tray_icon(app, controller):
    tray = QSystemTrayIcon()

    tray.setIcon(make_app_icon(32))
    tray.setToolTip(f"划词翻译与截图工具 v{CURRENT_VERSION}")

    menu = QMenu()

    snip_action = QAction("开启截图 / 钉图", app)
    
    def _tray_launch_snip():
        time.sleep(0.18)
        force_deselect_text()
        time.sleep(0.10)
        launch_snipping()

    snip_action.triggered.connect(_tray_launch_snip)
    menu.addAction(snip_action)
    menu.addSeparator()

    toggle_action = QAction("暂停划词翻译", app)
    toggle_action.setCheckable(True)

    def toggle():
        controller.enabled = not toggle_action.isChecked()

    toggle_action.triggered.connect(toggle)

    quit_action = QAction("退出程序", app)
    quit_action.triggered.connect(app.quit)

    menu.addAction(toggle_action)
    menu.addSeparator()
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    tray.show()
    return tray

# ==================== 8. 自动替换与自启 ====================
def check_first_run_install():
    if sys.platform != "win32":
        return
    try:
        current_pid = os.getpid()
        appdata_dir = os.environ.get('LOCALAPPDATA', os.environ.get('APPDATA', ''))
        install_dir = os.path.join(appdata_dir, APP_NAME)
        os.makedirs(install_dir, exist_ok=True)

        version_file = os.path.join(install_dir, 'version.txt')
        startup_dir = os.path.join(os.environ.get('APPDATA', ''), r'Microsoft\Windows\Start Menu\Programs\Startup')
        target_exe_in_startup = os.path.join(startup_dir, f"{APP_NAME}.exe")
        target_exe_in_install = os.path.join(install_dir, f"{APP_NAME}.exe")

        old_version = ""
        if os.path.exists(version_file):
            try:
                with open(version_file, 'r', encoding='utf-8') as f:
                    old_version = f.read().strip()
            except Exception:
                old_version = ""

        if old_version != CURRENT_VERSION:
            subprocess.run(
                f'taskkill /F /FI "PID ne {current_pid}" /IM "{APP_NAME}.exe"',
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            time.sleep(0.1)

            if os.path.exists(target_exe_in_startup):
                try: os.remove(target_exe_in_startup)
                except Exception: pass

            is_onefile = getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')
            if is_onefile:
                current_exe = sys.argv[0]
                shutil.copy(current_exe, target_exe_in_install)
                shutil.copy(current_exe, target_exe_in_startup)

            with open(version_file, 'w', encoding='utf-8') as f:
                f.write(CURRENT_VERSION)

            msg = QMessageBox()
            msg.setWindowTitle("划词翻译 - 升级成功")
            msg.setText(f"划词翻译 (v{CURRENT_VERSION}) 升级成功！\n\n- 集成 GitHub 开源长截图缝合算法 (基于 OpenCV 模板匹配)\n- 支持向下滚动鼠标进行任意长度网页/代码的长截图\n- 自动将长截图生成钉图卡片置顶贴在桌面上")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.exec()
    except Exception:
        pass

def network_monitor_loop():
    global IS_ONLINE
    while True:
        IS_ONLINE = check_network_services(timeout=2.0)
        time.sleep(30)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(make_app_icon(64))

    IS_ONLINE = check_network_services(timeout=2.0)
    print(f">>> 网络状态: {'在线' if IS_ONLINE else '离线'}")

    if IS_ONLINE:
        threading.Thread(target=_get_bing_token, daemon=True).start()

    monitor_thread = threading.Thread(target=network_monitor_loop, daemon=True)
    monitor_thread.start()

    check_first_run_install()

    window = FloatingWindow()
    signals.text_selected.connect(window.show_at)
    signals.hide_signal.connect(window.hide)

    controller = PureAltController(window)

    kb_listener = keyboard.Listener(on_press=controller.on_key_press)
    kb_listener.start()

    tray = create_tray_icon(app, controller)

    def _cleanup():
        _TRANSLATOR_POOL.shutdown(wait=False)
    app.aboutToQuit.connect(_cleanup)

    sys.exit(app.exec())