"""Цвета, стили и иконки интерфейса."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

BG = "#111318"
SURFACE = "#161920"
CARD = "#1B1F27"
CARD_HOVER = "#222732"
INPUT = "#13161D"
BORDER = "#272C37"
BORDER_STRONG = "#343A48"
TEXT = "#E9ECF2"
MUTED = "#8C94A6"
FAINT = "#5B6375"
ACCENT = "#3DDC97"
ACCENT_SOFT = "#1E4D3A"
ON_ACCENT = "#07170F"
WARN = "#FFC857"
DANGER = "#FF6B6B"
INFO = "#6CB4FF"

PROTOCOL_COLORS = {
    "vless": "#3DDC97",
    "vmess": "#6CB4FF",
    "trojan": "#FF8A65",
    "shadowsocks": "#B49CFF",
    "socks": "#9AA4B5",
    "hysteria2": "#FFC857",
    "json": "#5ED3F3",
}

FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", "sans-serif"]
MONO_FAMILIES = ["Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono", "monospace"]


def ping_color(ms: int | None) -> str:
    if ms is None:
        return FAINT
    if ms < 0:
        return DANGER
    if ms < 300:
        return ACCENT
    if ms < 800:
        return WARN
    return "#FF9F5A"


# ---------------------------------------------------------------- иконки
# Простые контурные иконки 24×24, нарисованные для этого приложения.

ICONS = {
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    "bolt": '<path d="M13 3 5 13.5h6L10 21l8-10.5h-6z"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/>',
    "more": '<circle cx="5.5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/>'
            '<circle cx="18.5" cy="12" r="1.3" fill="currentColor"/>',
    "trash": '<path d="M4.5 7h15M10 11v6M14 11v6M6.5 7l1 12.5h9L17.5 7M9.5 7V4.5h5V7"/>',
    "copy": '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
    "folder": '<path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4.5l2 2.2H19a1.5 1.5 0 0 1 1.5 1.5v8.3A1.5 1.5 0 0 1 19 19.5H5A1.5 1.5 0 0 1 3.5 18z"/>',
    "download": '<path d="M12 4v11M7 10.5l5 5 5-5M5 19.5h14"/>',
    "clipboard": '<rect x="5.5" y="5" width="13" height="15.5" rx="2"/><path d="M9 5V3.8h6V5M9 11h6M9 15h4"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "edit": '<path d="M4.5 19.5h4l10-10-4-4-10 10z"/><path d="m13 7 4 4"/>',
    "code": '<path d="m8.5 8-4 4 4 4M15.5 8l4 4-4 4"/>',
    "sort": '<path d="M7 5v14M4 16l3 3 3-3M14 7h6M14 12h4.5M14 17h3"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "power": '<path d="M12 3.5v8"/><path d="M7 6.5a7 7 0 1 0 10 0"/>',
    "servers": '<rect x="4" y="4.5" width="16" height="6" rx="1.5"/><rect x="4" y="13.5" width="16" height="6" rx="1.5"/>'
               '<circle cx="8" cy="7.5" r=".9" fill="currentColor"/><circle cx="8" cy="16.5" r=".9" fill="currentColor"/>',
    "rss": '<path d="M5 5a14 14 0 0 1 14 14M5 11a8 8 0 0 1 8 8"/><circle cx="6" cy="18" r="1.4" fill="currentColor"/>',
    "terminal": '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="m7.5 9.5 3 2.5-3 2.5M12.5 15h4"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 3.5v2.2M12 18.3v2.2M20.5 12h-2.2M5.7 12H3.5M18 6l-1.6 1.6M7.6 16.4 6 18M18 18l-1.6-1.6M7.6 7.6 6 6"/>',
    "chevron-down": '<path d="m7 10 5 5 5-5"/>',
    "shield": '<path d="M12 3.5 5 6.5v5c0 4.3 3 7.6 7 9 4-1.4 7-4.7 7-9v-5z"/>',
}


@lru_cache(maxsize=256)
def _svg(name: str, color: str, stroke: float) -> bytes:
    body = ICONS[name].replace("currentColor", color)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
        f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    ).encode()


def pixmap(name: str, color: str = TEXT, size: int = 18, stroke: float = 1.8, dpr: float = 2.0) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(_svg(name, color, stroke)))
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size * dpr, size * dpr))
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str = TEXT, size: int = 18) -> QIcon:
    result = QIcon()
    result.addPixmap(pixmap(name, color, size), QIcon.Normal)
    result.addPixmap(pixmap(name, FAINT, size), QIcon.Disabled)
    return result


def chevron_file(path) -> str:
    """QSS не умеет инлайн-SVG, поэтому стрелку для выпадающих списков кладём во временный файл."""
    path.write_bytes(_svg("chevron-down", MUTED, 2.0))
    return str(path).replace("\\", "/")


def stylesheet(chevron_path: str) -> str:
    return f"""
* {{ outline: none; }}
QWidget {{ color: {TEXT}; font-size: 13px; }}
QMainWindow, QWidget#central, QStackedWidget, QWidget#page {{ background: {BG}; }}
QWidget#sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QDialog, QMessageBox {{ background: {SURFACE}; }}
QLabel {{ background: transparent; }}
QLabel[kind="h1"] {{ font-size: 20px; font-weight: 700; }}
QLabel[kind="h2"] {{ font-size: 15px; font-weight: 650; }}
QLabel[kind="muted"] {{ color: {MUTED}; }}
QLabel[kind="faint"] {{ color: {FAINT}; font-size: 12px; }}
QLabel[kind="section"] {{ color: {MUTED}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
QLabel[kind="brand"] {{ font-size: 18px; font-weight: 800; letter-spacing: .5px; }}

QFrame[kind="card"] {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame[kind="banner"] {{ background: #2A2416; border: 1px solid #4A3E1E; border-radius: 10px; }}
QFrame[kind="line"] {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}

QPushButton {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 14px; font-weight: 600;
}}
QPushButton:hover {{ background: {CARD_HOVER}; border-color: {BORDER_STRONG}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {FAINT}; background: {SURFACE}; }}
QPushButton[kind="primary"] {{ background: {ACCENT}; color: {ON_ACCENT}; border: 1px solid {ACCENT}; }}
QPushButton[kind="primary"]:hover {{ background: #5BE6AA; }}
QPushButton[kind="primary"]:disabled {{ background: {ACCENT_SOFT}; color: {MUTED}; border-color: {ACCENT_SOFT}; }}
QPushButton[kind="ghost"] {{ background: transparent; border: 1px solid transparent; color: {MUTED}; padding: 6px 8px; }}
QPushButton[kind="ghost"]:hover {{ background: {CARD_HOVER}; color: {TEXT}; }}
QPushButton[kind="danger"] {{ color: {DANGER}; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}

QPushButton#nav {{
    background: transparent; border: none; border-radius: 9px;
    padding: 8px 14px; color: {MUTED}; font-weight: 650; text-align: left;
}}
QPushButton#nav:hover {{ color: {TEXT}; background: {CARD}; }}
QPushButton#nav:checked {{ color: {TEXT}; background: {CARD_HOVER}; }}

QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: {INPUT}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 6px 10px; selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: {FAINT}; }}
QPlainTextEdit {{ padding: 6px 8px; }}
QSpinBox {{ padding-left: 10px; min-height: 20px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QComboBox {{ padding-right: 28px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{chevron_path}"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{
    background: {CARD}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 4px;
    selection-background-color: {CARD_HOVER}; selection-color: {TEXT};
}}

QMenu {{ background: {CARD}; border: 1px solid {BORDER_STRONG}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {CARD_HOVER}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::icon {{ padding-left: 8px; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}

QListView, QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2B303B; border-radius: 4px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: #3A4150; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QScrollBar:horizontal {{ height: 0; }}

QProgressBar {{ background: {INPUT}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QProgressBar[kind="warn"]::chunk {{ background: {WARN}; }}
QProgressBar[kind="danger"]::chunk {{ background: {DANGER}; }}

QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; padding: 6px 8px; border-radius: 6px; }}
"""


def color(value: str, alpha: int = 255) -> QColor:
    c = QColor(value)
    c.setAlpha(alpha)
    return c


ICON_SIZE = QSize(16, 16)
