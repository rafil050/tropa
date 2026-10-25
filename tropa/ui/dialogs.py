"""Диалоги: добавление ссылок, подписка, просмотр текста."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from . import theme as t


def _buttons(dialog: QDialog, ok_text: str = "Готово", cancel: bool = True) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addStretch(1)
    if cancel:
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(dialog.reject)
        row.addWidget(cancel_btn)
    ok = QPushButton(ok_text)
    ok.setProperty("kind", "primary")
    ok.setDefault(True)
    ok.clicked.connect(dialog.accept)
    row.addWidget(ok)
    dialog._ok_button = ok  # noqa: SLF001
    return row


class AddLinksDialog(QDialog):
    """Вставка ссылок на серверы или ссылки на подписку."""

    def __init__(self, parent=None, text: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Добавить серверы")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        title = QLabel("Добавить серверы")
        title.setProperty("kind", "h2")
        hint = QLabel(
            "Вставьте одну или несколько ссылок (vless://, vmess://, trojan://, ss://, socks://, hysteria2://) "
            "или ссылку на подписку (https://…). Подходит и текст в base64."
        )
        hint.setWordWrap(True)
        hint.setProperty("kind", "muted")
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("vless://…\nhttps://example.com/sub/…")
        self.editor.setMinimumHeight(170)
        mono = QFont()
        mono.setFamilies(t.MONO_FAMILIES)
        mono.setPointSize(9)
        self.editor.setFont(mono)
        self.editor.setPlainText(text)
        paste = QPushButton(t.icon("clipboard"), "  Вставить из буфера")
        paste.setProperty("kind", "ghost")
        paste.clicked.connect(lambda: self.editor.setPlainText(QGuiApplication.clipboard().text()))
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.editor)
        row = _buttons(self, "Добавить")
        row.insertWidget(0, paste)
        layout.addLayout(row)

    def text(self) -> str:
        return self.editor.toPlainText()


class SubscriptionDialog(QDialog):
    def __init__(self, parent=None, name: str = "", url: str = "", editing: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Подписка")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        title = QLabel("Изменить подписку" if editing else "Новая подписка")
        title.setProperty("kind", "h2")
        layout.addWidget(title)
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("Необязательно — возьмём из подписки")
        self.url = QLineEdit(url)
        self.url.setPlaceholderText("https://…")
        form.addRow("Название", self.name)
        form.addRow("Ссылка", self.url)
        layout.addLayout(form)
        layout.addLayout(_buttons(self, "Сохранить" if editing else "Добавить"))
        self.url.textChanged.connect(self._validate)
        self._validate()

    def _validate(self) -> None:
        url = self.url.text().strip().lower()
        self._ok_button.setEnabled(url.startswith(("http://", "https://")))

    def values(self) -> tuple[str, str]:
        return self.name.text().strip(), self.url.text().strip()


class TextDialog(QDialog):
    """Показ текста (конфиг, список ошибок) с кнопкой «Скопировать»."""

    def __init__(self, title: str, text: str, parent=None, mono: bool = True, intro: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setProperty("kind", "h2")
        layout.addWidget(heading)
        if intro:
            label = QLabel(intro)
            label.setWordWrap(True)
            label.setProperty("kind", "muted")
            layout.addWidget(label)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        if mono:
            font = QFont()
            font.setFamilies(t.MONO_FAMILIES)
            font.setPointSize(9)
            view.setFont(font)
        layout.addWidget(view, 1)
        row = QHBoxLayout()
        copy = QPushButton(t.icon("copy"), "  Скопировать")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(text))
        row.addWidget(copy)
        row.addStretch(1)
        close = QPushButton("Закрыть")
        close.setProperty("kind", "primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)
