"""Собственные виджеты: кнопка подключения, переключатель, список серверов, уведомления."""

from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import (
    QAbstractListModel, QEasingCurve, QModelIndex, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
    Property, QVariantAnimation,
)
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QAbstractButton, QGraphicsOpacityEffect, QLabel, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget,
)

from ..models import Profile
from . import theme as t


# ---------------------------------------------------------------- большая кнопка подключения

class ConnectButton(QAbstractButton):
    """Круглая кнопка питания. Состояния: off, connecting, on."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(188, 188)
        self._state = "off"
        self._angle = 0.0
        self._pulse = 0.0
        self._hover = False
        self._spin = QTimer(self, interval=16)
        self._spin.timeout.connect(self._tick)
        self._breath = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=2600, loopCount=-1)
        self._breath.setEasingCurve(QEasingCurve.InOutSine)
        self._breath.valueChanged.connect(self._on_breath)
        self.setAccessibleName("Подключение")

    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        self._state = state
        if state == "connecting":
            self._spin.start()
        else:
            self._spin.stop()
        if state == "on":
            self._breath.start()
        else:
            self._breath.stop()
            self._pulse = 0.0
        self.setToolTip({"off": "Подключиться", "connecting": "Подключение…", "on": "Отключиться"}.get(state, ""))
        self.update()

    def _tick(self):
        self._angle = (self._angle + 5) % 360
        self.update()

    def _on_breath(self, value):
        self._pulse = math.sin(value * math.pi)
        self.update()

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(188, 188)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        center = QPointF(w / 2, w / 2)
        radius = w / 2 - 22

        accent = QColor(t.ACCENT)
        warn = QColor(t.WARN)

        # мягкое свечение
        if self._state in ("on", "connecting"):
            glow_color = accent if self._state == "on" else warn
            gradient = QRadialGradient(center, w / 2)
            alpha = int(70 + 50 * self._pulse) if self._state == "on" else 45
            gradient.setColorAt(0.55, t.color(glow_color.name(), alpha))
            gradient.setColorAt(1.0, t.color(glow_color.name(), 0))
            p.setPen(Qt.NoPen)
            p.setBrush(gradient)
            p.drawEllipse(center, w / 2, w / 2)

        # внутренний круг
        if self._state == "on":
            fill = QColor("#163A2B")
        elif self._state == "connecting":
            fill = QColor("#2A2618")
        else:
            fill = QColor("#1E222B" if not self._hover else "#232834")
        if self.isDown():
            fill = fill.darker(115)
        p.setBrush(fill)
        p.setPen(Qt.NoPen)
        p.drawEllipse(center, radius, radius)

        # кольцо
        ring_rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        base_pen = QPen(QColor("#2C313D" if not self._hover else "#353B49"), 6)
        p.setPen(base_pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(ring_rect)
        if self._state == "on":
            p.setPen(QPen(accent, 6, Qt.SolidLine, Qt.RoundCap))
            p.drawEllipse(ring_rect)
        elif self._state == "connecting":
            p.setPen(QPen(warn, 6, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(ring_rect, int(-self._angle * 16), int(100 * 16))

        # значок питания
        icon_color = {"on": accent, "connecting": warn}.get(self._state, QColor(t.MUTED if not self._hover else t.TEXT))
        pen = QPen(icon_color, 6, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        r = radius * 0.40
        arc_rect = QRectF(center.x() - r, center.y() - r + 4, r * 2, r * 2)
        p.drawArc(arc_rect, 120 * 16, 300 * 16)  # дуга с разрывом сверху
        p.drawLine(QPointF(center.x(), center.y() - r - 6), QPointF(center.x(), center.y() + 2))
        p.end()


# ---------------------------------------------------------------- переключатель

class Toggle(QAbstractButton):
    def __init__(self, parent=None, checked: bool = False):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 22)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self, duration=140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def get_knob(self) -> float:
        return self._pos

    def set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    knob = Property(float, get_knob, set_knob)

    def setChecked(self, checked: bool) -> None:  # noqa: N802 — без анимации при программной установке
        blocked = self.signalsBlocked()
        super().setChecked(checked)
        if blocked:
            self._pos = 1.0 if checked else 0.0
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(40, 22)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track_off, track_on = QColor("#2C313D"), QColor(t.ACCENT)
        track = QColor(
            int(track_off.red() + (track_on.red() - track_off.red()) * self._pos),
            int(track_off.green() + (track_on.green() - track_off.green()) * self._pos),
            int(track_off.blue() + (track_on.blue() - track_off.blue()) * self._pos),
        )
        if not self.isEnabled():
            track.setAlpha(90)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        knob_x = 3 + self._pos * 18
        p.setBrush(QColor("#F4F6FA") if self.isEnabled() else QColor("#7A8090"))
        p.drawEllipse(QRectF(knob_x, 3, 16, 16))
        p.end()


# ---------------------------------------------------------------- модель списка серверов

ProfileRole = Qt.UserRole + 1


class ServerListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[Profile] = []
        self._rows: dict[str, int] = {}

    def set_profiles(self, profiles: list[Profile]) -> None:
        self.beginResetModel()
        self._items = list(profiles)
        self._rows = {p.id: i for i, p in enumerate(self._items)}
        self.endResetModel()

    def profiles(self) -> list[Profile]:
        return list(self._items)

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        profile = self._items[index.row()]
        if role == Qt.DisplayRole:
            return profile.title()
        if role == ProfileRole:
            return profile
        if role == Qt.ToolTipRole:
            return f"{profile.title()}\n{profile.protocol_title()} · {profile.summary()}"
        return None

    def row_of(self, profile_id: str) -> int:
        return self._rows.get(profile_id, -1)

    def refresh_row(self, profile_id: str) -> None:
        row = self.row_of(profile_id)
        if row >= 0:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx)

    def refresh_all(self) -> None:
        if self._items:
            self.dataChanged.emit(self.index(0), self.index(len(self._items) - 1))


class ServerDelegate(QStyledItemDelegate):
    """Рисует сервер карточкой: протокол, название, детали, задержка."""

    HEIGHT = 62

    def __init__(self, state: Callable[[], dict], parent=None):
        super().__init__(parent)
        self._state = state  # {'active': id, 'connected': bool, 'testing': set, 'subs': {id: name}}

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), self.HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        profile: Profile = index.data(ProfileRole)
        if profile is None:
            return
        state = self._state()
        is_active = profile.id == state.get("active")
        is_selected = bool(option.state & QStyle.State_Selected)
        is_hover = bool(option.state & QStyle.State_MouseOver)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(option.rect).adjusted(2, 3, -6, -3)

        background = QColor(t.CARD)
        if is_selected:
            background = QColor("#242A36")
        elif is_hover:
            background = QColor(t.CARD_HOVER)
        border = QColor(t.ACCENT if is_active else (t.BORDER_STRONG if is_selected else t.BORDER))
        painter.setPen(QPen(border, 1.4 if is_active else 1.0))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 10, 10)

        if is_active:
            bar = QPainterPath()
            bar.addRoundedRect(QRectF(rect.left() + 1, rect.top() + 12, 3, rect.height() - 24), 1.5, 1.5)
            painter.fillPath(bar, QColor(t.ACCENT))

        # бейдж протокола
        proto_color = QColor(t.PROTOCOL_COLORS.get(profile.protocol, t.MUTED))
        badge_font = QFont(option.font)
        badge_font.setPixelSize(10)
        badge_font.setBold(True)
        painter.setFont(badge_font)
        label = profile.protocol_title().upper()
        if label == "SHADOWSOCKS":
            label = "SS"
        if label == "HYSTERIA2":
            label = "HY2"
        badge = QRectF(rect.left() + 14, rect.center().y() - 11, 52, 22)
        painter.setPen(Qt.NoPen)
        painter.setBrush(t.color(proto_color.name(), 38))
        painter.drawRoundedRect(badge, 6, 6)
        painter.setPen(proto_color)
        painter.drawText(badge, Qt.AlignCenter, label)

        # задержка справа
        ping_font = QFont(option.font)
        ping_font.setPixelSize(12)
        ping_font.setBold(True)
        painter.setFont(ping_font)
        if profile.id in state.get("testing", set()):
            ping_text, ping_col = "…", t.MUTED
        elif profile.ping is None:
            ping_text, ping_col = "—", t.FAINT
        elif profile.ping < 0:
            ping_text, ping_col = "нет ответа", t.DANGER
        else:
            ping_text, ping_col = f"{profile.ping} мс", t.ping_color(profile.ping)
        ping_w = QFontMetrics(ping_font).horizontalAdvance(ping_text) + 24  # запас: шрифты Windows шире расчёта
        ping_rect = QRectF(rect.right() - 16 - ping_w, rect.top(), ping_w, rect.height())
        painter.setPen(QColor(ping_col))
        painter.drawText(ping_rect, Qt.AlignVCenter | Qt.AlignRight, ping_text)

        # название и детали
        text_left = badge.right() + 14
        text_width = ping_rect.left() - text_left - 12
        name_font = QFont(option.font)
        name_font.setPixelSize(13)
        name_font.setWeight(QFont.DemiBold)
        painter.setFont(name_font)
        painter.setPen(QColor(t.TEXT))
        name = QFontMetrics(name_font).elidedText(profile.title(), Qt.ElideRight, int(text_width))
        painter.drawText(QRectF(text_left, rect.top() + 11, text_width, 20), Qt.AlignLeft | Qt.AlignVCenter, name)

        details = profile.summary()
        sub_name = state.get("subs", {}).get(profile.sub_id)
        if sub_name and state.get("show_group"):
            details = f"{sub_name} · {details}"
        if is_active and state.get("connected"):
            details = "● подключено · " + details
        small = QFont(option.font)
        small.setPixelSize(11)
        painter.setFont(small)
        painter.setPen(QColor(t.ACCENT if (is_active and state.get("connected")) else t.MUTED))
        details = QFontMetrics(small).elidedText(details, Qt.ElideRight, int(text_width))
        painter.drawText(QRectF(text_left, rect.top() + 31, text_width, 18), Qt.AlignLeft | Qt.AlignVCenter, details)
        painter.restore()


# ---------------------------------------------------------------- всплывающее уведомление

class Toast(QLabel):
    COLORS = {"info": t.INFO, "ok": t.ACCENT, "error": t.DANGER, "warn": t.WARN}

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignCenter)
        self.setMaximumWidth(520)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self, duration=220)
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self._hide)
        self.hide()

    def show_message(self, text: str, kind: str = "info", ms: int = 3500) -> None:
        accent = self.COLORS.get(kind, t.INFO)
        self.setStyleSheet(
            f"QLabel {{ background: {t.CARD}; color: {t.TEXT}; border: 1px solid {accent};"
            f" border-left: 4px solid {accent}; border-radius: 10px; padding: 10px 16px; font-weight: 600; }}"
        )
        self.setText(text)
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity() if self.isVisible() else 0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(ms)

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.setFixedWidth(min(520, max(260, self.sizeHint().width())))
        self.adjustSize()
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - 24
        self.move(max(12, x), max(12, y))

    def _hide(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._after_fade)
        self._fade.start()

    def _after_fade(self) -> None:
        try:
            self._fade.finished.disconnect(self._after_fade)
        except (RuntimeError, TypeError):
            pass
        if self._effect.opacity() < 0.05:
            self.hide()

    def reposition(self) -> None:
        if self.isVisible():
            self._place()


def brush(color: str) -> QBrush:
    return QBrush(QColor(color))
