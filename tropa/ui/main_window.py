"""Главное окно Tropa."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEvent, QItemSelectionModel, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFontMetrics, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QFormLayout, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListView, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QProgressDialog,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QStackedLayout, QStackedWidget, QSystemTrayIcon, QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, APP_VERSION, core, winutil
from ..links import looks_like_subscription, parse_many, share_link
from ..models import PING_FAILED, ROUTING_MODES, Profile, Subscription
from ..netutil import describe_error, tcp_ping, url_delay
from ..paths import IS_WINDOWS, data_dir, resource_path
from ..storage import Store
from ..subscriptions import SubscriptionError, apply_result, fetch, human_bytes
from ..xray_config import ConfigError, build_config
from . import theme as t
from .controller import ConnectionController
from .dialogs import AddLinksDialog, SubscriptionDialog, TextDialog
from .widgets import ConnectButton, ProfileRole, ServerDelegate, ServerListModel, Toast, Toggle
from .workers import TaskRunner


class ElidedLabel(QLabel):
    """Подпись, которая обрезает длинный текст многоточием, а не растягивает окно."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = max(10, self.width())
        super().setText(QFontMetrics(self.font()).elidedText(self._full, Qt.ElideRight, width))
        self.setToolTip(self._full if self.text() != self._full else "")


def _label(text: str = "", kind: str = "", wrap: bool = False) -> QLabel:
    label = QLabel(text)
    if kind:
        label.setProperty("kind", kind)
    label.setWordWrap(wrap)
    return label


def _button(text: str = "", icon_name: str = "", kind: str = "", color: str | None = None) -> QPushButton:
    button = QPushButton(text)
    if icon_name:
        icon_color = color or (t.ON_ACCENT if kind == "primary" else t.TEXT)
        button.setIcon(t.icon(icon_name, icon_color))
        button.setIconSize(QSize(16, 16))
    if kind:
        button.setProperty("kind", kind)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _ago(timestamp: float) -> str:
    if not timestamp:
        return "ещё не обновлялась"
    minutes = int((time.time() - timestamp) // 60)
    if minutes < 1:
        return "обновлена только что"
    if minutes < 60:
        return f"обновлена {minutes} мин назад"
    hours = minutes // 60
    if hours < 24:
        return f"обновлена {hours} ч назад"
    return f"обновлена {time.strftime('%d.%m.%Y', time.localtime(timestamp))}"


class MainWindow(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.tasks = TaskRunner(self)
        self.ctrl = ConnectionController(self)
        self.testing: set[str] = set()
        self.ping_cancel: threading.Event | None = None
        self.current_delay: int | None = None
        self._quitting = False
        self._core_version: str | None = None

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(resource_path("icon.svg"))))
        self.resize(1040, 680)
        self.setMinimumSize(900, 600)

        self.reconnect_timer = QTimer(self, singleShot=True, interval=450)
        self.reconnect_timer.timeout.connect(self._reconnect_now)
        self.uptime_timer = QTimer(self, interval=1000)
        self.uptime_timer.timeout.connect(self._update_uptime)
        self.save_timer = QTimer(self, singleShot=True, interval=400)
        self.save_timer.timeout.connect(self._save)

        self._build_ui()
        self._build_tray()
        self.toast = Toast(self.centralWidget())

        self.ctrl.stateChanged.connect(self._on_state)
        self.ctrl.logLine.connect(self._append_log)
        self.ctrl.failed.connect(self._on_failed)

        self.refresh_all()
        self._refresh_core_status()
        QTimer.singleShot(0, self._startup)

    # ================================================================ построение интерфейса

    def _build_ui(self) -> None:
        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(24, 18, 24, 16)
        column.setSpacing(14)

        nav = QHBoxLayout()
        nav.setSpacing(4)
        self.nav_group = QButtonGroup(self)
        self.stack = QStackedWidget()
        pages = [
            ("Серверы", "servers", self._build_servers_page()),
            ("Подписки", "rss", self._build_subscriptions_page()),
            ("Логи", "terminal", self._build_logs_page()),
            ("Настройки", "settings", self._build_settings_page()),
        ]
        for index, (title, icon_name, page) in enumerate(pages):
            button = QPushButton(f"  {title}", objectName="nav")
            button.setIcon(t.icon(icon_name, t.MUTED))
            button.setIconSize(QSize(16, 16))
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            self.nav_group.addButton(button, index)
            nav.addWidget(button)
            self.stack.addWidget(page)
        self.nav_group.button(0).setChecked(True)
        self.nav_group.idClicked.connect(self.stack.setCurrentIndex)
        nav.addStretch(1)
        column.addLayout(nav)
        column.addWidget(self.stack, 1)
        root.addWidget(content, 1)

        QShortcut(QKeySequence.Paste, self, activated=self._paste_shortcut)
        delete = QShortcut(QKeySequence.Delete, self.server_list, activated=self.delete_selected)
        delete.setContext(Qt.WidgetShortcut)

    # ---------------------------------------------------------------- боковая панель

    def _build_sidebar(self) -> QWidget:
        side = QWidget(objectName="sidebar")
        side.setFixedWidth(296)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(0)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(QIcon(str(resource_path("icon.svg"))).pixmap(30, 30))
        brand.addWidget(logo)
        brand.addWidget(_label(APP_NAME, "brand"))
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addStretch(2)

        self.connect_button = ConnectButton()
        self.connect_button.clicked.connect(self.toggle_connection)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.connect_button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addSpacing(6)

        self.status_label = _label("Не подключено", "h2")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        layout.addSpacing(2)
        self.uptime_label = _label("Нажмите, чтобы подключиться", "muted")
        self.uptime_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.uptime_label)
        layout.addSpacing(22)

        card = QFrame()
        card.setProperty("kind", "card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(3)
        card_layout.addWidget(_label("СЕРВЕР", "section"))
        card_layout.addSpacing(4)
        self.side_name = ElidedLabel("Сервер не выбран")
        self.side_name.setStyleSheet("font-weight: 650; font-size: 14px;")
        card_layout.addWidget(self.side_name)
        self.side_details = ElidedLabel("")
        self.side_details.setProperty("kind", "muted")
        card_layout.addWidget(self.side_details)
        self.side_delay = _label("", "faint", wrap=True)
        card_layout.addWidget(self.side_delay)
        layout.addWidget(card)
        layout.addSpacing(16)

        layout.addWidget(_label("МАРШРУТИЗАЦИЯ", "section"))
        layout.addSpacing(8)
        self.mode_combo = QComboBox()
        for key, title in ROUTING_MODES.items():
            self.mode_combo.addItem(title, key)
        self.mode_combo.setItemData(0, "Весь трафик идёт через сервер", Qt.ToolTipRole)
        self.mode_combo.setItemData(1, "Сайты в зоне .ru/.рф и российские IP открываются напрямую", Qt.ToolTipRole)
        self.mode_combo.setItemData(2, "Через сервер идут только сайты из списка в настройках", Qt.ToolTipRole)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo)
        layout.addSpacing(14)

        proxy_row = QHBoxLayout()
        proxy_text = QVBoxLayout()
        proxy_text.setSpacing(0)
        proxy_text.addWidget(_label("Системный прокси"))
        proxy_hint = _label("браузеры и программы Windows", "faint")
        proxy_text.addWidget(proxy_hint)
        proxy_row.addLayout(proxy_text)
        proxy_row.addStretch(1)
        self.sysproxy_toggle = Toggle()
        self.sysproxy_toggle.toggled.connect(self._on_sysproxy_toggled)
        proxy_row.addWidget(self.sysproxy_toggle)
        layout.addLayout(proxy_row)
        layout.addStretch(3)

        self.ports_label = _label("", "faint")
        self.ports_label.setAlignment(Qt.AlignCenter)
        self.ports_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.ports_label)
        return side

    # ---------------------------------------------------------------- серверы

    def _build_servers_page(self) -> QWidget:
        page = QWidget(objectName="page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(_label("Серверы", "h1"))
        self.servers_count = _label("", "muted")
        header.addSpacing(6)
        header.addWidget(self.servers_count, 0, Qt.AlignBottom)
        header.addStretch(1)

        self.ping_button = _button("Проверить", "bolt")
        ping_menu = QMenu(self)
        ping_menu.addAction(t.icon("bolt"), "Реальная задержка (через ядро)", lambda: self.run_ping("real"))
        ping_menu.addAction(t.icon("refresh"), "Быстрый TCP-пинг", lambda: self.run_ping("tcp"))
        ping_menu.addSeparator()
        ping_menu.addAction(t.icon("sort"), "Сортировать по задержке", self.sort_by_ping)
        self.ping_button.setMenu(ping_menu)
        header.addWidget(self.ping_button)

        self.add_button = _button("Добавить", "plus", "primary")
        add_menu = QMenu(self)
        add_menu.addAction(t.icon("clipboard"), "Из буфера обмена\tCtrl+V", self.import_from_clipboard)
        add_menu.addAction(t.icon("link"), "Вставить ссылки…", self.open_add_dialog)
        add_menu.addAction(t.icon("rss"), "Добавить подписку…", self.open_subscription_dialog)
        self.add_button.setMenu(add_menu)
        header.addWidget(self.add_button)
        layout.addLayout(header)

        self.core_banner = QFrame()
        self.core_banner.setProperty("kind", "banner")
        banner_layout = QHBoxLayout(self.core_banner)
        banner_layout.setContentsMargins(14, 10, 10, 10)
        banner_text = _label("Ядро Xray ещё не скачано — без него подключиться не получится. "
                             "Это около 15 МБ с GitHub.", wrap=True)
        banner_layout.addWidget(banner_text, 1)
        banner_button = _button("Скачать ядро", "download", "primary")
        banner_button.clicked.connect(lambda: self.download_core())
        banner_layout.addWidget(banner_button)
        layout.addWidget(self.core_banner)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по названию или адресу")
        self.search.addAction(t.icon("search", t.MUTED), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self.refresh_servers())
        filters.addWidget(self.search, 3)
        self.group_combo = QComboBox()
        self.group_combo.setMinimumWidth(220)
        self.group_combo.currentIndexChanged.connect(lambda _: self.refresh_servers(keep_groups=True))
        filters.addWidget(self.group_combo, 2)
        layout.addLayout(filters)

        self.ping_progress = QWidget()
        progress_row = QHBoxLayout(self.ping_progress)
        progress_row.setContentsMargins(0, 0, 0, 0)
        self.ping_progress_label = _label("", "muted")
        self.ping_progress_bar = QProgressBar()
        self.ping_progress_bar.setTextVisible(False)
        cancel = _button("Остановить", kind="ghost")
        cancel.clicked.connect(self.cancel_ping)
        progress_row.addWidget(self.ping_progress_label)
        progress_row.addWidget(self.ping_progress_bar, 1)
        progress_row.addWidget(cancel)
        self.ping_progress.hide()
        layout.addWidget(self.ping_progress)

        holder = QWidget()
        self.servers_stack = QStackedLayout(holder)
        self.model = ServerListModel(self)
        self.server_list = QListView()
        self.server_list.setModel(self.model)
        self.server_list.setItemDelegate(ServerDelegate(self._delegate_state, self.server_list))
        self.server_list.setMouseTracking(True)
        self.server_list.setUniformItemSizes(True)
        self.server_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.server_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.server_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.server_list.customContextMenuRequested.connect(self._server_menu)
        self.server_list.clicked.connect(self._on_server_clicked)
        self.server_list.doubleClicked.connect(self._on_server_double_clicked)
        self.server_list.activated.connect(self._on_server_double_clicked)
        self.servers_stack.addWidget(self.server_list)

        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch(1)
        icon_label = QLabel()
        icon_label.setPixmap(t.pixmap("servers", t.FAINT, 44, 1.5))
        icon_label.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(icon_label)
        empty_layout.addSpacing(10)
        self.empty_title = _label("Серверов пока нет", "h2")
        self.empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        self.empty_hint = _label(
            "Скопируйте ссылку на сервер или подписку, которую дал провайдер,\n"
            "и нажмите «Из буфера обмена» или Ctrl+V.", "muted")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_hint)
        empty_layout.addSpacing(14)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        from_clip = _button("Из буфера обмена", "clipboard", "primary")
        from_clip.clicked.connect(self.import_from_clipboard)
        add_sub = _button("Добавить подписку", "rss")
        add_sub.clicked.connect(self.open_subscription_dialog)
        buttons.addWidget(from_clip)
        buttons.addWidget(add_sub)
        buttons.addStretch(1)
        self.empty_buttons = QWidget()
        self.empty_buttons.setLayout(buttons)
        empty_layout.addWidget(self.empty_buttons)
        empty_layout.addStretch(2)
        self.servers_stack.addWidget(empty)
        layout.addWidget(holder, 1)
        return page

    # ---------------------------------------------------------------- подписки

    def _build_subscriptions_page(self) -> QWidget:
        page = QWidget(objectName="page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(_label("Подписки", "h1"))
        header.addStretch(1)
        update_all = _button("Обновить все", "refresh")
        update_all.clicked.connect(lambda: self.update_all_subscriptions())
        header.addWidget(update_all)
        add = _button("Подписка", "plus", "primary")
        add.clicked.connect(self.open_subscription_dialog)
        header.addWidget(add)
        layout.addLayout(header)
        hint = _label("Подписка — это ссылка от провайдера, по которой Tropa сама загружает и обновляет список серверов.",
                      "muted", wrap=True)
        layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.subs_container = QWidget()
        self.subs_layout = QVBoxLayout(self.subs_container)
        self.subs_layout.setContentsMargins(0, 4, 6, 4)
        self.subs_layout.setSpacing(10)
        scroll.setWidget(self.subs_container)
        layout.addWidget(scroll, 1)
        return page

    def _subscription_card(self, sub: Subscription) -> QFrame:
        card = QFrame()
        card.setProperty("kind", "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 12, 14)
        layout.setSpacing(6)

        top = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        name = ElidedLabel(sub.title())
        name.setStyleSheet("font-weight: 650; font-size: 14px;")
        title_col.addWidget(name)
        url = ElidedLabel(sub.url)
        url.setProperty("kind", "faint")
        title_col.addWidget(url)
        top.addLayout(title_col, 1)

        refresh = _button("Обновить", "refresh")
        refresh.clicked.connect(lambda: self.update_subscription(sub.id))
        top.addWidget(refresh, 0, Qt.AlignTop)
        more = _button("", "more", "ghost")
        more.setFixedWidth(36)
        menu = QMenu(more)
        menu.addAction(t.icon("edit"), "Изменить", lambda: self.edit_subscription(sub.id))
        menu.addAction(t.icon("copy"), "Скопировать ссылку", lambda: self._copy(sub.url, "Ссылка подписки скопирована"))
        if sub.support_url:
            menu.addAction(t.icon("link"), "Поддержка провайдера",
                           lambda: QDesktopServices.openUrl(QUrl(sub.support_url)))
        menu.addSeparator()
        menu.addAction(t.icon("trash", t.DANGER), "Удалить", lambda: self.delete_subscription(sub.id))
        more.setMenu(menu)
        top.addWidget(more, 0, Qt.AlignTop)
        layout.addLayout(top)

        count = sum(1 for p in self.store.profiles if p.sub_id == sub.id)
        meta = [f"{count} серв." if count else "нет серверов", _ago(sub.updated_at)]
        if sub.expire:
            left_days = int((sub.expire - time.time()) // 86400)
            date = time.strftime("%d.%m.%Y", time.localtime(sub.expire))
            meta.append(f"до {date}" + (f" ({left_days} дн.)" if 0 <= left_days <= 30 else "") if left_days >= 0
                        else f"истекла {date}")
        meta_label = _label(" · ".join(meta), "muted")
        layout.addWidget(meta_label)

        if sub.total:
            used = sub.upload + sub.download
            ratio = min(1.0, used / sub.total) if sub.total else 0
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(int(ratio * 1000))
            bar.setTextVisible(False)
            if ratio > 0.9:
                bar.setProperty("kind", "danger")
            elif ratio > 0.75:
                bar.setProperty("kind", "warn")
            layout.addSpacing(4)
            layout.addWidget(bar)
            layout.addWidget(_label(f"Использовано {human_bytes(used)} из {human_bytes(sub.total)}", "faint"))
        elif sub.upload or sub.download:
            layout.addWidget(_label(f"Использовано {human_bytes(sub.upload + sub.download)} (без лимита)", "faint"))

        if sub.announce:
            announce = _label(sub.announce, wrap=True)
            announce.setStyleSheet(f"color: {t.INFO};")
            layout.addWidget(announce)
        if sub.last_error:
            error = _label(f"Последнее обновление не удалось: {sub.last_error}", wrap=True)
            error.setStyleSheet(f"color: {t.DANGER};")
            layout.addWidget(error)
        return card

    # ---------------------------------------------------------------- логи

    def _build_logs_page(self) -> QWidget:
        page = QWidget(objectName="page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(_label("Логи", "h1"))
        header.addStretch(1)
        copy = _button("Скопировать", "copy")
        copy.clicked.connect(lambda: self._copy(self.log_view.toPlainText(), "Логи скопированы"))
        clear = _button("Очистить", "trash")
        clear.clicked.connect(lambda: self.log_view.clear())
        header.addWidget(copy)
        header.addWidget(clear)
        layout.addLayout(header)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(4000)
        self.log_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        font = self.log_view.font()
        font.setFamilies(t.MONO_FAMILIES)
        font.setPointSize(9)
        self.log_view.setFont(font)
        self.log_view.setPlaceholderText("Здесь появятся сообщения ядра Xray после подключения.")
        layout.addWidget(self.log_view, 1)
        return page

    # ---------------------------------------------------------------- настройки

    def _build_settings_page(self) -> QWidget:
        page = QWidget(objectName="page")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(12)
        outer.addWidget(_label("Настройки", "h1"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 8, 12)
        layout.setSpacing(8)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        s = self.store.settings

        def section(title: str) -> QFormLayout:
            layout.addSpacing(10)
            layout.addWidget(_label(title.upper(), "section"))
            card = QFrame()
            card.setProperty("kind", "card")
            form = QFormLayout(card)
            form.setContentsMargins(16, 14, 16, 14)
            form.setHorizontalSpacing(18)
            form.setVerticalSpacing(12)
            form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
            layout.addWidget(card)
            return form

        def toggle_row(form: QFormLayout, title: str, hint: str, value: bool, handler) -> Toggle:
            text = QVBoxLayout()
            text.setSpacing(1)
            text.addWidget(_label(title))
            if hint:
                text.addWidget(_label(hint, "faint", wrap=True))
            row = QHBoxLayout()
            row.addLayout(text, 1)
            toggle = Toggle(checked=value)
            toggle.toggled.connect(handler)
            row.addWidget(toggle, 0, Qt.AlignVCenter)
            form.addRow(row)
            return toggle

        def port_box(value: int) -> QSpinBox:
            box = QSpinBox()
            box.setButtonSymbols(QSpinBox.NoButtons)
            box.setRange(1, 65535)
            box.setValue(value)
            box.setMaximumWidth(120)
            return box

        # подключение
        form = section("Подключение")
        self.socks_box = port_box(s.socks_port)
        self.http_box = port_box(s.http_port)
        self.socks_box.editingFinished.connect(lambda: self._set_setting("socks_port", self.socks_box.value(), True))
        self.http_box.editingFinished.connect(lambda: self._set_setting("http_port", self.http_box.value(), True))
        form.addRow("Порт SOCKS5", self.socks_box)
        form.addRow("Порт HTTP", self.http_box)
        self.dns_edit = QLineEdit(s.dns)
        self.dns_edit.setPlaceholderText("localhost, 1.1.1.1")
        self.dns_edit.setToolTip("DNS для решения, куда направлять трафик. localhost — системный DNS.")
        self.dns_edit.editingFinished.connect(lambda: self._set_setting("dns", self.dns_edit.text().strip(), True))
        form.addRow("DNS для маршрутизации", self.dns_edit)
        toggle_row(form, "Разрешить подключения из локальной сети",
                   "Телефон или ТВ в той же сети смогут использовать прокси этого компьютера",
                   s.allow_lan, lambda v: self._set_setting("allow_lan", v, True))

        # маршрутизация
        form = section("Маршрутизация")
        toggle_row(form, "Блокировать рекламу", "Список доменов рекламы и трекеров из базы geosite",
                   s.block_ads, lambda v: self._set_setting("block_ads", v, True))
        self.proxy_list_edit = QPlainTextEdit(s.proxy_list)
        self.proxy_list_edit.setFixedHeight(92)
        self.proxy_list_edit.setPlaceholderText("youtube.com\ngeosite:instagram")
        self.direct_list_edit = QPlainTextEdit(s.direct_list)
        self.direct_list_edit.setFixedHeight(92)
        self.direct_list_edit.setPlaceholderText("mybank.ru\n192.168.0.0/16")
        form.addRow(self._field_label(
            "Всегда через прокси",
            "По одному на строку: домен, IP или подсеть, geosite:… или geoip:…. "
            "В режиме «Только мой список» через прокси идёт только это."))
        form.addRow(self.proxy_list_edit)
        form.addRow(self._field_label("Всегда напрямую", "Сайты и адреса, которые должны открываться без прокси."))
        form.addRow(self.direct_list_edit)
        apply_row = QHBoxLayout()
        apply_lists = _button("Применить списки", "check")
        apply_lists.clicked.connect(self._apply_lists)
        apply_row.addWidget(apply_lists)
        apply_row.addStretch(1)
        form.addRow(apply_row)

        # подписки
        form = section("Подписки")
        toggle_row(form, "Обновлять при запуске", "", s.sub_update_on_start,
                   lambda v: self._set_setting("sub_update_on_start", v))
        toggle_row(form, "Загружать через прокси", "Если подписка не открывается напрямую (только при подключении)",
                   s.sub_via_proxy, lambda v: self._set_setting("sub_via_proxy", v))
        self.ua_edit = QLineEdit(s.sub_user_agent)
        self.ua_edit.setToolTip("Некоторые панели отдают разный формат в зависимости от User-Agent")
        self.ua_edit.editingFinished.connect(
            lambda: self._set_setting("sub_user_agent", self.ua_edit.text().strip() or "Tropa/1.0"))
        form.addRow("User-Agent", self.ua_edit)
        self.timeout_box = QSpinBox()
        self.timeout_box.setButtonSymbols(QSpinBox.NoButtons)
        self.timeout_box.setRange(3, 120)
        self.timeout_box.setSuffix(" с")
        self.timeout_box.setValue(s.sub_timeout)
        self.timeout_box.setMaximumWidth(120)
        self.timeout_box.editingFinished.connect(lambda: self._set_setting("sub_timeout", self.timeout_box.value()))
        form.addRow("Тайм-аут загрузки", self.timeout_box)

        # приложение
        form = section("Приложение")
        toggle_row(form, "Сворачивать в трей при закрытии", "Крестик прячет окно, подключение продолжает работать",
                   s.tray_on_close, lambda v: self._set_setting("tray_on_close", v))
        toggle_row(form, "Подключаться при запуске", "", s.connect_on_start,
                   lambda v: self._set_setting("connect_on_start", v))
        autostart = toggle_row(form, "Запускать вместе с Windows", "", s.autostart, self._on_autostart)
        autostart.setEnabled(IS_WINDOWS)
        self.level_combo = QComboBox()
        for key, title in (("warning", "Предупреждения"), ("info", "Подробно"), ("debug", "Отладка"),
                           ("error", "Только ошибки")):
            self.level_combo.addItem(title, key)
        self.level_combo.setCurrentIndex(max(0, self.level_combo.findData(s.log_level)))
        self.level_combo.currentIndexChanged.connect(
            lambda _: self._set_setting("log_level", self.level_combo.currentData(), True))
        self.level_combo.setMaximumWidth(220)
        form.addRow("Логи ядра", self.level_combo)
        self.test_url_edit = QLineEdit(s.test_url)
        self.test_url_edit.editingFinished.connect(
            lambda: self._set_setting("test_url", self.test_url_edit.text().strip() or "https://www.gstatic.com/generate_204"))
        form.addRow("Адрес для проверки задержки", self.test_url_edit)

        # ядро
        form = section("Ядро Xray")
        self.core_label = _label("…")
        core_buttons = QHBoxLayout()
        self.core_update_button = _button("Проверить обновление", "refresh")
        self.core_update_button.clicked.connect(self.check_core_update)
        core_folder = _button("Открыть папку", "folder")
        core_folder.clicked.connect(lambda: self._open_folder(core.find_binary().parent if core.find_binary()
                                                              else data_dir() / "core"))
        core_buttons.addWidget(self.core_update_button)
        core_buttons.addWidget(core_folder)
        core_buttons.addStretch(1)
        form.addRow("Версия", self.core_label)
        form.addRow("", core_buttons)

        # о программе
        layout.addSpacing(10)
        layout.addWidget(_label("О ПРОГРАММЕ", "section"))
        about = QFrame()
        about.setProperty("kind", "card")
        about_layout = QVBoxLayout(about)
        about_layout.setContentsMargins(16, 14, 16, 14)
        about_layout.addWidget(_label(f"{APP_NAME} {APP_VERSION}", "h2"))
        about_layout.addWidget(_label(
            "Клиент для собственных прокси-серверов. Сетевую часть выполняет открытое ядро Xray-core "
            "(лицензия MPL-2.0), которое скачивается с официальной страницы проекта на GitHub. "
            "Tropa не продаёт серверы и не собирает данные — всё хранится на этом компьютере.",
            "muted", wrap=True))
        data_button = _button("Папка с данными", "folder")
        data_button.clicked.connect(lambda: self._open_folder(data_dir()))
        row = QHBoxLayout()
        row.addWidget(data_button)
        row.addStretch(1)
        about_layout.addLayout(row)
        layout.addWidget(about)
        layout.addStretch(1)
        return page

    def _field_label(self, title: str, hint: str) -> QWidget:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(_label(title))
        column.addWidget(_label(hint, "faint", wrap=True))
        return box

    # ---------------------------------------------------------------- трей

    def _build_tray(self) -> None:
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.icon_on = QIcon(str(resource_path("icon.svg")))
        self.icon_off = QIcon(str(resource_path("icon_off.svg")))
        self.tray = QSystemTrayIcon(self.icon_off, self)
        menu = QMenu()
        self.tray_status = QAction("Не подключено", menu, enabled=False)
        self.tray_toggle = QAction("Подключить", menu, triggered=self.toggle_connection)
        menu.addAction(self.tray_status)
        menu.addSeparator()
        menu.addAction(self.tray_toggle)
        menu.addAction(QAction("Открыть Tropa", menu, triggered=self.show_window))
        menu.addSeparator()
        menu.addAction(QAction("Выход", menu, triggered=self.quit_app))
        self.tray.setContextMenu(menu)
        self.tray.setToolTip(APP_NAME)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        self._tray_menu = menu

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window()

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ================================================================ обновление интерфейса

    def refresh_all(self) -> None:
        s = self.store.settings
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(s.routing_mode)))
        self.mode_combo.blockSignals(False)
        self.sysproxy_toggle.blockSignals(True)
        self.sysproxy_toggle.setChecked(s.system_proxy)
        self.sysproxy_toggle.blockSignals(False)
        self._update_ports_label()
        self.refresh_servers()
        self.refresh_subscriptions()
        self.refresh_sidebar()

    def _update_ports_label(self) -> None:
        s = self.store.settings
        host = "0.0.0.0" if s.allow_lan else "127.0.0.1"
        self.ports_label.setText(f"SOCKS5 {host}:{s.socks_port}\nHTTP {host}:{s.http_port}")

    def _visible_profiles(self) -> list[Profile]:
        group = self.group_combo.currentData()
        query = self.search.text().strip().lower()
        result = []
        for p in self.store.profiles:
            if group == "__manual__" and p.sub_id:
                continue
            if group not in (None, "__all__", "__manual__") and p.sub_id != group:
                continue
            if query and query not in f"{p.title()} {p.protocol_title()} {p.summary()}".lower():
                continue
            result.append(p)
        return result

    def _refresh_groups(self) -> None:
        current = self.group_combo.currentData() or "__all__"
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItem(f"Все серверы ({len(self.store.profiles)})", "__all__")
        manual = sum(1 for p in self.store.profiles if not p.sub_id)
        if manual:
            self.group_combo.addItem(f"Добавлены вручную ({manual})", "__manual__")
        for sub in self.store.subscriptions:
            count = sum(1 for p in self.store.profiles if p.sub_id == sub.id)
            self.group_combo.addItem(f"{sub.title()} ({count})", sub.id)
        index = self.group_combo.findData(current)
        self.group_combo.setCurrentIndex(index if index >= 0 else 0)
        self.group_combo.blockSignals(False)

    def refresh_servers(self, keep_groups: bool = False) -> None:
        if not keep_groups:
            self._refresh_groups()
        selected_ids = {i.data(ProfileRole).id for i in self.server_list.selectionModel().selectedIndexes()} \
            if self.server_list.selectionModel() else set()
        profiles = self._visible_profiles()
        self.model.set_profiles(profiles)
        for profile_id in selected_ids:
            row = self.model.row_of(profile_id)
            if row >= 0:
                self.server_list.selectionModel().select(self.model.index(row), QItemSelectionModel.Select)
        total = len(self.store.profiles)
        self.servers_count.setText(f"{len(profiles)} из {total}" if len(profiles) != total else (str(total) if total else ""))
        has_any = bool(self.store.profiles)
        if profiles:
            self.servers_stack.setCurrentIndex(0)
        else:
            self.servers_stack.setCurrentIndex(1)
            if has_any:
                self.empty_title.setText("Ничего не найдено")
                self.empty_hint.setText("Попробуйте изменить поиск или выбрать другую группу.")
                self.empty_buttons.hide()
            else:
                self.empty_title.setText("Серверов пока нет")
                self.empty_hint.setText("Скопируйте ссылку на сервер или подписку, которую дал провайдер,\n"
                                        "и нажмите «Из буфера обмена» или Ctrl+V.")
                self.empty_buttons.show()

    def refresh_subscriptions(self) -> None:
        while self.subs_layout.count():
            item = self.subs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.store.subscriptions:
            empty = _label("Подписок пока нет. Нажмите «Подписка» и вставьте ссылку от провайдера.", "muted", wrap=True)
            empty.setAlignment(Qt.AlignCenter)
            empty.setMinimumHeight(120)
            self.subs_layout.addWidget(empty)
        for sub in self.store.subscriptions:
            self.subs_layout.addWidget(self._subscription_card(sub))
        self.subs_layout.addStretch(1)

    def refresh_sidebar(self) -> None:
        profile = self.ctrl.profile if self.ctrl.is_running() and self.ctrl.profile else self.store.selected()
        if profile is None:
            self.side_name.setText("Сервер не выбран")
            self.side_details.setText("Выберите сервер в списке справа")
        else:
            self.side_name.setText(profile.title())
            self.side_details.setText(f"{profile.protocol_title()} · {profile.summary()}")
        if self.ctrl.state == "on":
            if self.current_delay is None:
                self.side_delay.setText("Проверяю соединение…")
                self.side_delay.setStyleSheet(f"color: {t.MUTED};")
            elif self.current_delay < 0:
                self.side_delay.setText("Сервер не отвечает. Попробуйте другой")
                self.side_delay.setStyleSheet(f"color: {t.DANGER};")
            else:
                self.side_delay.setText(f"Задержка {self.current_delay} мс")
                self.side_delay.setStyleSheet(f"color: {t.ping_color(self.current_delay)};")
            self.side_delay.show()
        else:
            self.side_delay.hide()

    def _delegate_state(self) -> dict:
        group = self.group_combo.currentData()
        return {
            "active": self.ctrl.profile.id if self.ctrl.is_running() and self.ctrl.profile else self.store.selected_id,
            "connected": self.ctrl.state == "on",
            "testing": self.testing,
            "subs": {s.id: s.title() for s in self.store.subscriptions},
            "show_group": group in (None, "__all__"),
        }

    # ================================================================ подключение

    def _startup(self) -> None:
        s = self.store.settings
        # если прошлый запуск завершился аварийно, системный прокси мог остаться включённым
        try:
            if winutil.system_proxy_points_to(s.http_port):
                winutil.disable_system_proxy(s.http_port)
                self._log("Выключен системный прокси, оставшийся от прошлого запуска")
        except OSError:
            pass
        if s.sub_update_on_start and self.store.subscriptions:
            self.update_all_subscriptions(silent=True, then_connect=s.connect_on_start)
        elif s.connect_on_start and self.store.selected() and core.find_binary():
            self.connect_selected()

    def toggle_connection(self) -> None:
        if self.ctrl.is_running():
            self.ctrl.stop()
        else:
            self.connect_selected()

    def connect_selected(self) -> None:
        profile = self.store.selected()
        if profile is None:
            visible = self.model.profiles() or self.store.profiles
            if not visible:
                self.toast.show_message("Сначала добавьте сервер — ссылку или подписку", "warn")
                return
            profile = visible[0]
            self.store.selected_id = profile.id
            self._schedule_save()
        if core.find_binary() is None:
            answer = QMessageBox.question(
                self, "Нужно ядро Xray",
                "Для подключения нужно ядро Xray (около 15 МБ). Скачать его сейчас с GitHub?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                self.download_core(then_connect=True)
            return
        self.current_delay = None
        self.ctrl.start(profile, self.store.settings)
        self.refresh_sidebar()

    def _reconnect_now(self) -> None:
        if self.ctrl.is_running():
            self.connect_selected()

    def schedule_reconnect(self) -> None:
        if self.ctrl.is_running():
            self.reconnect_timer.start()

    def _on_state(self, state: str) -> None:
        self.connect_button.set_state(state)
        texts = {
            "off": ("Не подключено", t.TEXT, "Нажмите, чтобы подключиться"),
            "connecting": ("Подключение…", t.WARN, "Запускаю ядро Xray"),
            "on": ("Подключено", t.ACCENT, "00:00:00"),
        }
        title, col, sub = texts[state]
        self.status_label.setText(title)
        self.status_label.setStyleSheet(f"color: {col};")
        self.uptime_label.setText(sub)
        if state == "on":
            self.uptime_timer.start()
            self.current_delay = None
            self._check_current_delay()
        else:
            self.uptime_timer.stop()
        if self.tray:
            self.tray.setIcon(self.icon_on if state == "on" else self.icon_off)
            self.tray_status.setText(title + (f": {self.ctrl.profile.title()}" if state == "on" and self.ctrl.profile else ""))
            self.tray_toggle.setText("Отключить" if state in ("on", "connecting") else "Подключить")
            self.tray.setToolTip(f"{APP_NAME} — {title.lower()}")
        self.model.refresh_all()
        self.refresh_sidebar()

    def _update_uptime(self) -> None:
        if not self.ctrl.connected_at:
            return
        seconds = int(time.time() - self.ctrl.connected_at)
        self.uptime_label.setText(f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}")

    def _check_current_delay(self) -> None:
        port, url = self.store.settings.http_port, self.store.settings.test_url
        profile_id = self.ctrl.profile.id if self.ctrl.profile else ""

        def done(ms: int) -> None:
            if self.ctrl.state != "on":
                return
            self.current_delay = ms
            profile = self.store.profile(profile_id)
            if profile is not None:
                profile.ping = ms
                self.model.refresh_row(profile_id)
            self.refresh_sidebar()

        self.tasks.run(url_delay, port, url, on_done=done)

    def _on_failed(self, message: str) -> None:
        self._log(message)
        self.toast.show_message(message, "error", 6500)
        if self.tray and not self.isVisible():
            self.tray.showMessage(APP_NAME, message, QSystemTrayIcon.Warning, 5000)

    # ================================================================ серверы: действия

    def _on_server_clicked(self, index) -> None:
        if QApplication.keyboardModifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
            return
        profile: Profile = index.data(ProfileRole)
        if profile is None or profile.id == self.store.selected_id:
            return
        self.store.selected_id = profile.id
        self._schedule_save()
        self.model.refresh_all()
        self.refresh_sidebar()
        self.schedule_reconnect()

    def _on_server_double_clicked(self, index) -> None:
        profile: Profile = index.data(ProfileRole)
        if profile is None:
            return
        self.reconnect_timer.stop()
        self.store.selected_id = profile.id
        self._schedule_save()
        if not (self.ctrl.is_running() and self.ctrl.profile and self.ctrl.profile.id == profile.id):
            self.connect_selected()
        self.model.refresh_all()

    def _selected_profiles(self) -> list[Profile]:
        indexes = sorted(self.server_list.selectionModel().selectedIndexes(), key=lambda i: i.row())
        return [i.data(ProfileRole) for i in indexes if i.data(ProfileRole) is not None]

    def _server_menu(self, pos) -> None:
        index = self.server_list.indexAt(pos)
        if index.isValid() and not self.server_list.selectionModel().isSelected(index):
            self.server_list.selectionModel().select(index, QItemSelectionModel.ClearAndSelect)
        selected = self._selected_profiles()
        if not selected:
            return
        menu = QMenu(self)
        if len(selected) == 1:
            p = selected[0]
            menu.addAction(t.icon("power", t.ACCENT), "Подключиться", lambda: self._on_server_double_clicked(index))
            menu.addAction(t.icon("edit"), "Переименовать", lambda: self.rename_profile(p))
            menu.addAction(t.icon("copy"), "Скопировать ссылку", lambda: self._copy(share_link(p), "Ссылка скопирована"))
            menu.addAction(t.icon("code"), "Показать конфиг Xray", lambda: self.show_config(p))
        else:
            menu.addAction(t.icon("copy"), f"Скопировать ссылки ({len(selected)})",
                           lambda: self._copy("\n".join(share_link(x) for x in selected), "Ссылки скопированы"))
        menu.addAction(t.icon("bolt"), "Проверить задержку", lambda: self.run_ping("real", selected))
        menu.addSeparator()
        label = "Удалить" if len(selected) == 1 else f"Удалить ({len(selected)})"
        menu.addAction(t.icon("trash", t.DANGER), label, self.delete_selected)
        menu.exec(self.server_list.viewport().mapToGlobal(pos))

    def rename_profile(self, profile: Profile) -> None:
        name, ok = QInputDialog.getText(self, "Переименовать", "Новое название:", text=profile.title())
        if ok and name.strip():
            profile.name = name.strip()
            self._schedule_save()
            self.model.refresh_row(profile.id)
            self.refresh_sidebar()

    def show_config(self, profile: Profile) -> None:
        try:
            config, warnings = build_config(profile, self.store.settings)
        except (ConfigError, ValueError) as exc:
            self.toast.show_message(f"Конфиг не собирается: {exc}", "error")
            return
        intro = "Так этот сервер будет передан ядру Xray."
        if warnings:
            intro += "\n⚠ " + "\n⚠ ".join(warnings)
        TextDialog(f"Конфиг: {profile.title()}", json.dumps(config, ensure_ascii=False, indent=2), self,
                   intro=intro).exec()

    def delete_selected(self) -> None:
        selected = self._selected_profiles()
        if not selected:
            return
        from_subs = [p for p in selected if p.sub_id]
        text = f"Удалить {len(selected)} серв.?" if len(selected) > 1 else f"Удалить «{selected[0].title()}»?"
        if from_subs:
            text += "\n\nСерверы из подписки вернутся при её следующем обновлении."
        if QMessageBox.question(self, "Удаление", text, QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.store.remove_profiles({p.id for p in selected})
        self._schedule_save()
        self.refresh_servers()
        self.refresh_subscriptions()
        self.refresh_sidebar()

    def sort_by_ping(self) -> None:
        def key(p: Profile):
            if p.ping is None:
                return (2, 0)
            if p.ping < 0:
                return (3, 0)
            return (0, p.ping)
        self.store.profiles.sort(key=key)
        self._schedule_save()
        self.refresh_servers(keep_groups=True)

    # ---------------------------------------------------------------- проверка задержки

    def run_ping(self, mode: str, profiles: list[Profile] | None = None) -> None:
        if self.ping_cancel is not None:
            self.toast.show_message("Проверка уже идёт", "info")
            return
        profiles = list(profiles or self.model.profiles())
        if not profiles:
            return
        if mode == "real" and core.find_binary() is None:
            self.toast.show_message("Для реальной задержки нужно ядро — делаю быстрый TCP-пинг", "warn")
            mode = "tcp"
        cancel = threading.Event()
        self.ping_cancel = cancel
        for p in profiles:
            p.ping = None
            self.testing.add(p.id)
        self.model.refresh_all()
        total = len(profiles)
        state = {"done": 0}
        self.ping_progress_bar.setRange(0, total)
        self.ping_progress_bar.setValue(0)
        self.ping_progress_label.setText(f"Проверка 0 из {total}")
        self.ping_progress.show()
        self.ping_button.setEnabled(False)

        def on_result(item) -> None:
            profile_id, ms = item
            profile = self.store.profile(profile_id)
            self.testing.discard(profile_id)
            if profile is not None:
                profile.ping = ms
                self.model.refresh_row(profile_id)
            state["done"] += 1
            self.ping_progress_bar.setValue(state["done"])
            self.ping_progress_label.setText(f"Проверка {state['done']} из {total}")

        def finished() -> None:
            for p in profiles:
                self.testing.discard(p.id)
            self.ping_cancel = None
            self.ping_progress.hide()
            self.ping_button.setEnabled(True)
            self.model.refresh_all()
            self._schedule_save()
            ok = sum(1 for p in profiles if p.ping and p.ping > 0)
            self.toast.show_message(f"Отвечают {ok} из {total}", "ok" if ok else "warn")

        if mode == "tcp":
            def job(progress):
                def one(p: Profile):
                    if cancel.is_set():
                        return
                    if p.protocol == "hysteria2" or not p.address:
                        progress((p.id, PING_FAILED if not p.address else None))
                        return
                    progress((p.id, tcp_ping(p.address, p.port)))
                with ThreadPoolExecutor(max_workers=24) as pool:
                    list(pool.map(one, profiles))
        else:
            url = self.store.settings.test_url

            def job(progress):
                core.real_delays(profiles, url, lambda pid, ms, err: progress((pid, ms)), cancel)

        self.tasks.run(job, on_progress=on_result, on_finished=finished,
                       on_error=lambda msg: self.toast.show_message(f"Проверка не удалась: {msg}", "error"))

    def cancel_ping(self) -> None:
        if self.ping_cancel is not None:
            self.ping_cancel.set()

    # ---------------------------------------------------------------- импорт

    def _paste_shortcut(self) -> None:
        if self.stack.currentIndex() == 0:
            self.import_from_clipboard()

    def import_from_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text()
        if not text.strip():
            self.toast.show_message("Буфер обмена пуст — скопируйте ссылку и попробуйте снова", "warn")
            return
        self.import_text(text)

    def open_add_dialog(self) -> None:
        dialog = AddLinksDialog(self)
        if dialog.exec() and dialog.text().strip():
            self.import_text(dialog.text())

    def import_text(self, text: str) -> None:
        text = text.strip()
        if looks_like_subscription(text):
            self.add_subscription(text)
            return
        profiles, errors = parse_many(text)
        if not profiles and not errors:
            urls = [line.strip() for line in text.splitlines() if looks_like_subscription(line)]
            if urls:
                for url in urls:
                    self.add_subscription(url)
                return
            self.toast.show_message("Не нашёл ссылок на серверы в этом тексте", "warn")
            return
        added = self.store.add_profiles(profiles)
        self._schedule_save()
        self.refresh_servers()
        self.refresh_sidebar()
        if profiles:
            row = self.model.row_of(profiles[0].id)
            if row >= 0:
                self.server_list.scrollTo(self.model.index(row))
        skipped = len(profiles) - added
        message = f"Добавлено серверов: {added}" + (f", уже были в списке: {skipped}" if skipped else "")
        self.toast.show_message(message, "ok" if added else "info")
        if errors:
            TextDialog("Часть ссылок не добавлена", "\n".join(errors), self, mono=False,
                       intro="Эти ссылки не удалось разобрать или их не поддерживает ядро Xray:").exec()

    # ---------------------------------------------------------------- подписки

    def open_subscription_dialog(self) -> None:
        clip = QGuiApplication.clipboard().text().strip()
        dialog = SubscriptionDialog(self, url=clip if looks_like_subscription(clip) else "")
        if dialog.exec():
            name, url = dialog.values()
            self.add_subscription(url, name)

    def add_subscription(self, url: str, name: str = "") -> None:
        existing = next((s for s in self.store.subscriptions if s.url == url), None)
        if existing:
            self.toast.show_message("Эта подписка уже добавлена — обновляю", "info")
            self.update_subscription(existing.id)
            return
        sub = Subscription(url=url, name=name)
        self.store.subscriptions.append(sub)
        self._schedule_save()
        self.refresh_subscriptions()
        self._refresh_groups()
        self.update_subscription(sub.id, select_group=True)

    def edit_subscription(self, sub_id: str) -> None:
        sub = self.store.subscription(sub_id)
        if sub is None:
            return
        dialog = SubscriptionDialog(self, sub.name, sub.url, editing=True)
        if dialog.exec():
            name, url = dialog.values()
            changed = url != sub.url
            sub.name, sub.url = name, url
            self._schedule_save()
            self.refresh_subscriptions()
            self._refresh_groups()
            if changed:
                self.update_subscription(sub.id)

    def delete_subscription(self, sub_id: str) -> None:
        sub = self.store.subscription(sub_id)
        if sub is None:
            return
        if QMessageBox.question(self, "Удаление подписки",
                                f"Удалить подписку «{sub.title()}» вместе с её серверами?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.store.remove_subscription(sub_id)
        self._schedule_save()
        self.refresh_all()

    def _sub_proxy(self) -> str | None:
        s = self.store.settings
        if s.sub_via_proxy and self.ctrl.state == "on":
            return f"http://127.0.0.1:{s.http_port}"
        return None

    def update_subscription(self, sub_id: str, silent: bool = False, select_group: bool = False,
                            on_finished=None) -> None:
        sub = self.store.subscription(sub_id)
        if sub is None:
            return
        s = self.store.settings
        if not silent:
            self.toast.show_message(f"Обновляю «{sub.title()}»…", "info", 2000)

        def done(result) -> None:
            current = self.store.subscription(sub_id)
            if current is None:
                return
            apply_result(current, result)
            self.store.replace_subscription_profiles(sub_id, result.profiles)
            if not self.store.selected() and result.profiles:
                self.store.selected_id = result.profiles[0].id
            self._schedule_save()
            if select_group:
                self._refresh_groups()
                index = self.group_combo.findData(sub_id)
                if index >= 0:
                    self.group_combo.setCurrentIndex(index)
            self.refresh_servers()
            self.refresh_subscriptions()
            self.refresh_sidebar()
            if not silent:
                text = f"«{current.title()}»: серверов {len(result.profiles)}"
                if result.errors:
                    text += f", пропущено {len(result.errors)}"
                self.toast.show_message(text, "ok")
            if result.errors:
                self._log(f"Подписка «{current.title()}»: пропущены ссылки:\n  " + "\n  ".join(result.errors[:30]))

        def failed(message: str) -> None:
            current = self.store.subscription(sub_id)
            if current is None:
                return
            current.last_error = message
            self._schedule_save()
            self.refresh_subscriptions()
            self._log(f"Подписка «{current.title()}» не обновилась: {message}")
            if not silent:
                self.toast.show_message(f"Подписка не обновилась: {message}", "error", 6000)

        def job():
            try:
                return fetch(sub.url, user_agent=s.sub_user_agent, timeout=s.sub_timeout, proxy=self._sub_proxy())
            except SubscriptionError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise SubscriptionError(describe_error(exc)) from exc

        self.tasks.run(job, on_done=done, on_error=failed, on_finished=on_finished)

    def update_all_subscriptions(self, silent: bool = False, then_connect: bool = False) -> None:
        subs = list(self.store.subscriptions)
        if not subs:
            if not silent:
                self.toast.show_message("Подписок пока нет", "info")
            if then_connect:
                self.connect_selected()
            return
        pending = {"left": len(subs)}

        def one_finished():
            pending["left"] -= 1
            if pending["left"] == 0:
                if not silent:
                    self.toast.show_message("Подписки обновлены", "ok")
                if then_connect and self.store.selected() and core.find_binary():
                    self.connect_selected()

        for sub in subs:
            self.update_subscription(sub.id, silent=True, on_finished=one_finished)
        if not silent:
            self.toast.show_message(f"Обновляю подписки: {len(subs)}", "info", 2000)

    # ---------------------------------------------------------------- ядро

    def _refresh_core_status(self) -> None:
        def done(version):
            self._core_version = version
            self.core_banner.setVisible(version is None)
            self.core_label.setText(f"Xray {version}" if version else "не установлено")
            self.core_update_button.setText("Проверить обновление" if version else "Скачать ядро")
        self.core_banner.setVisible(core.find_binary() is None)
        self.tasks.run(core.core_version, on_done=done)

    def download_core(self, then_connect: bool = False) -> None:
        was_running = self.ctrl.is_running()
        dialog = QProgressDialog("Скачиваю ядро Xray с GitHub…", "Отмена", 0, 100, self)
        dialog.setWindowTitle("Ядро Xray")
        dialog.setMinimumWidth(420)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)
        cancel = threading.Event()
        dialog.canceled.connect(cancel.set)
        if was_running:
            self.ctrl.stop()  # в Windows нельзя заменить запущенный xray.exe

        def progress(value) -> None:
            done_bytes, total = value
            if total:
                dialog.setValue(int(done_bytes * 100 / total))
                dialog.setLabelText(f"Скачиваю ядро Xray… {done_bytes / 1048576:.1f} из {total / 1048576:.1f} МБ")

        def done(version: str) -> None:
            dialog.canceled.disconnect()
            dialog.close()
            self._refresh_core_status()
            self._log(f"Установлено ядро Xray {version}")
            self.toast.show_message(f"Ядро Xray {version} установлено", "ok")
            if then_connect or was_running:
                self.connect_selected()

        def failed(message: str) -> None:
            cancelled = cancel.is_set()
            dialog.canceled.disconnect()
            dialog.close()
            if cancelled:
                if was_running:
                    self.connect_selected()
                return
            hint = ""
            if "время" in message or "timed out" in message.lower() or "urlopen" in message.lower():
                hint = "\n\nЕсли GitHub недоступен, скачайте архив Xray-windows-64.zip вручную и положите " \
                       "xray.exe, geoip.dat и geosite.dat в папку ядра (Настройки → Ядро Xray → Открыть папку)."
            QMessageBox.warning(self, "Ядро Xray", f"Не удалось скачать ядро: {message}{hint}")
            if was_running:
                self.connect_selected()

        def job(progress):
            try:
                return core.download_core(proxy=None, progress=lambda done, total: progress((done, total)), cancel=cancel)
            except core.CoreError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise core.CoreError(describe_error(exc)) from exc

        self.tasks.run(job, on_done=done, on_error=failed, on_progress=progress)

    def check_core_update(self) -> None:
        if self._core_version is None:
            self.download_core()
            return
        self.core_update_button.setEnabled(False)

        def done(latest: str) -> None:
            self.core_update_button.setEnabled(True)
            current = tuple(int(x) for x in self._core_version.split("."))
            if tuple(int(x) for x in latest.split(".")) > current:
                if QMessageBox.question(self, "Обновление ядра",
                                        f"Доступна версия Xray {latest} (у вас {self._core_version}). Обновить?",
                                        QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                    self.download_core()
            else:
                self.toast.show_message(f"У вас последняя версия Xray ({self._core_version})", "ok")

        def failed(message: str) -> None:
            self.core_update_button.setEnabled(True)
            self.toast.show_message(f"Не удалось проверить обновление: {message}", "error")

        self.tasks.run(core.latest_version, on_done=done, on_error=failed)

    # ---------------------------------------------------------------- настройки

    def _set_setting(self, name: str, value, affects_core: bool = False) -> None:
        if getattr(self.store.settings, name) == value:
            return
        setattr(self.store.settings, name, value)
        self._schedule_save()
        self._update_ports_label()
        if affects_core:
            self.schedule_reconnect()

    def _apply_lists(self) -> None:
        s = self.store.settings
        changed = (s.proxy_list != self.proxy_list_edit.toPlainText() or
                   s.direct_list != self.direct_list_edit.toPlainText())
        s.proxy_list = self.proxy_list_edit.toPlainText()
        s.direct_list = self.direct_list_edit.toPlainText()
        self._schedule_save()
        if changed and self.ctrl.is_running():
            self.schedule_reconnect()
            self.toast.show_message("Списки применены, переподключаюсь", "ok")
        else:
            self.toast.show_message("Списки сохранены", "ok")

    def _on_mode_changed(self, _index: int) -> None:
        self._set_setting("routing_mode", self.mode_combo.currentData(), affects_core=True)

    def _on_sysproxy_toggled(self, enabled: bool) -> None:
        self._set_setting("system_proxy", enabled)
        self.ctrl.apply_system_proxy(enabled)

    def _on_autostart(self, enabled: bool) -> None:
        try:
            winutil.set_autostart(enabled, APP_NAME)
        except OSError as exc:
            self.toast.show_message(f"Не удалось изменить автозапуск: {exc}", "error")
            return
        self._set_setting("autostart", enabled)

    # ================================================================ прочее

    def _log(self, text: str) -> None:
        self._append_log(f"[{time.strftime('%H:%M:%S')}] {text}")

    def _append_log(self, line: str) -> None:
        self.log_view.appendPlainText(line)

    def _copy(self, text: str, message: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self.toast.show_message(message, "ok", 2000)

    def _open_folder(self, path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _schedule_save(self) -> None:
        self.save_timer.start()

    def _save(self) -> None:
        try:
            self.store.save()
        except OSError as exc:
            self._log(f"Не удалось сохранить настройки: {exc}")

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "toast"):
            self.toast.reposition()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        winutil.dark_title_bar(int(self.winId()))

    def closeEvent(self, event):  # noqa: N802
        if self._quitting:
            event.accept()
            return
        s = self.store.settings
        if s.tray_on_close and self.tray is not None:
            event.ignore()
            self.hide()
            if not s.tray_hint_shown:
                s.tray_hint_shown = True
                self._schedule_save()
                self.tray.showMessage(APP_NAME, "Tropa продолжает работать в трее. Чтобы выйти, "
                                      "нажмите правой кнопкой на значок и выберите «Выход».",
                                      QSystemTrayIcon.Information, 4000)
            return
        event.accept()
        QTimer.singleShot(0, self.quit_app)

    def quit_app(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.cancel_ping()
        self.ctrl.stop(quiet=True)
        self.save_timer.stop()
        self._save()
        if self.tray:
            self.tray.hide()
        self.close()
        QApplication.exit(0)  # exit, а не quit: без повторного закрытия окон, не зависает

    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            self.model.refresh_all()
