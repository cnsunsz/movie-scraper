"""Desktop window styled after commercial MDC 8.0.6 (original PySide6 UI).

Behavioral concepts (folders, modes, site priority, proxy, translate, NFO skip)
align with open-source Movie_Data_Capture conventions; no GPL source is copied.
"""

from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

def _load_extra_qt_libs() -> None:
    """This Linux image has no libEGL / xcb helpers. Load copies from ~/.local/qt-libs if present."""
    extra = Path.home() / ".local" / "qt-libs"
    if not extra.is_dir():
        return
    import ctypes
    for name in (
        "libEGL.so.1",
        "libxcb-xkb.so.1",
        "libxcb-icccm.so.4",
        "libxcb-keysyms.so.1",
        "libxcb-cursor.so.0",
        "libxkbcommon-x11.so.0",
    ):
        path = extra / name
        if path.exists():
            ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)


_load_extra_qt_libs()

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QFont, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import (
    APP_DIR,
    MAIN_MODES,
    __version__,
    default_config,
    effective_proxy,
    get_config_path,
    load_config,
    load_config_from,
    run_job,
    run_one_file,
    save_config,
    set_config_path,
)
from scraper.parser import parse_filename
from scraper.sources import SITE_LABELS, default_sites, normalize_sites


def _pick_font() -> QFont:
    from PySide6.QtGui import QFontDatabase

    families = set(QFontDatabase.families())
    for name in (
        "Microsoft YaHei",
        "Microsoft YaHei UI",
        "Noto Sans CJK SC",
        "Noto Sans CJK JP",
        "Source Han Sans SC",
        "PingFang SC",
    ):
        if name in families:
            return QFont(name, 10)
    return QFont()


def _parse_proxy(proxy: str) -> tuple[str, str]:
    text = (proxy or "").strip()
    if not text:
        return "localhost", "1080"
    if "://" not in text:
        text = "http://" + text
    parsed = urlparse(text)
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 1080)
    return host, port


STYLESHEET = """
QMainWindow, QWidget#central {
    background: #F5F5F5;
    color: #222222;
}
QFrame#topNav {
    background: #FFFFFF;
    border-bottom: 1px solid #E5E5E5;
}
QPushButton.navBtn {
    background: transparent;
    border: none;
    padding: 14px 18px 12px 18px;
    color: #555555;
    font-size: 13px;
}
QPushButton.navBtn:checked {
    color: #111111;
    font-weight: 600;
    border-bottom: 3px solid #222222;
    border-radius: 0;
}
QFrame#bottomBar {
    background: #FFFFFF;
    border-top: 1px solid #E0E0E0;
}
QPushButton#startBtn {
    background: #22C55E;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 10px 28px;
    font-size: 15px;
    font-weight: 600;
    min-width: 110px;
}
QPushButton#startBtn:disabled {
    background: #A7F3D0;
    color: #F0FDF4;
}
QPushButton#stopBtn {
    background: #FFFFFF;
    border: 1px solid #D4D4D4;
    border-radius: 20px;
    min-width: 40px;
    max-width: 40px;
    min-height: 40px;
    max-height: 40px;
    color: #666666;
    font-size: 16px;
}
QPushButton#stopBtn:disabled {
    color: #BBBBBB;
}
QPushButton.linkish {
    background: transparent;
    border: none;
    color: #666666;
    padding: 6px 10px;
}
QPushButton#nameTest {
    background: transparent;
    border: none;
    color: #7C3AED;
    padding: 6px 12px;
    font-weight: 600;
}
QFrame.card {
    background: #FFFFFF;
    border: 1px solid #E8E8E8;
    border-radius: 8px;
}
QLabel.cardTitle {
    font-size: 14px;
    font-weight: 600;
    color: #222222;
}
QLabel.hint {
    color: #888888;
    font-size: 12px;
}
QLineEdit, QPlainTextEdit, QListWidget {
    background: #FFFFFF;
    border: 1px solid #D8D8D8;
    border-radius: 4px;
    padding: 6px;
    selection-background-color: #BFDBFE;
}
QPlainTextEdit#runLog {
    background: #3A3A3A;
    color: #F5F5F5;
    border: none;
    border-radius: 10px;
    padding: 12px;
    font-family: Consolas, "Courier New", monospace;
    font-size: 12px;
}
QPushButton.primary {
    background: #2563EB;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 10px 16px;
    font-weight: 600;
}
QPushButton.primary:hover { background: #1D4ED8; }
QPushButton.purple {
    background: #7C3AED;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 10px 16px;
    font-weight: 600;
}
QPushButton.secondary {
    background: #FFFFFF;
    border: 1px solid #D0D0D0;
    border-radius: 4px;
    padding: 6px 12px;
}
QPushButton.toggleOn {
    background: #2563EB;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 8px 18px;
}
QPushButton.toggleOff {
    background: #FFFFFF;
    color: #444444;
    border: 1px solid #D0D0D0;
    border-radius: 4px;
    padding: 8px 18px;
}
QCheckBox { spacing: 8px; }
QScrollArea { border: none; background: transparent; }
"""


class MainWindow(QMainWindow):
    NAV = (
        ("运行", "run"),
        ("完成项目信息", "done"),
        ("本地配置", "config"),
        ("自定义刮削", "custom"),
        ("演员", "actors"),
        ("语言", "lang"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"电影元数据刮削 v{__version__}")
        self.resize(1080, 760)
        self.setMinimumSize(920, 640)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue = queue.Queue()
        self._summary = {"success": 0, "fail": 0, "skip": 0, "lines": []}
        self._job_kind = ""
        self._config_path = get_config_path()  # session path; None = unsaved defaults

        config = load_config()  # defaults or session --config; never auto-creates file
        self._film_type = config.get("film_type") if config.get("film_type") in {"general", "other"} else "other"
        self._mode_cache = {
            "general": dict(config.get("general") or {}),
            "other": dict(config.get("other") or {}),
        }
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_top_nav())
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self.page_run = self._build_run_page()
        self.page_done = self._build_done_page()
        self.page_config = self._build_config_page(config)
        self.page_custom = self._build_custom_page()
        self.page_actors = self._build_actors_page(config)
        self.page_lang = self._build_lang_page()
        for page in (
            self.page_run,
            self.page_done,
            self.page_config,
            self.page_custom,
            self.page_actors,
            self.page_lang,
        ):
            self.stack.addWidget(page)

        root.addWidget(self._build_bottom_bar())
        self._sync_mode()
        self._sync_proxy_enabled()
        self._sync_avatar_source()
        self._sync_film_type_style()
        self._refresh_config_path_label()
        self._set_nav(0)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._drain)
        self._timer.start(150)

    # ---- chrome ----
    def _build_top_nav(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("topNav")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(4)
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []
        for index, (label, _key) in enumerate(self.NAV):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("class", "navBtn")
            btn.setObjectName(f"nav_{index}")
            btn.setStyleSheet("")  # class via stylesheet selector
            btn.setProperty("class", "navBtn")
            btn.setFlat(True)
            btn.setProperty("cssClass", "navBtn")
            # Use object property for Qt stylesheet: QPushButton.navBtn needs class via setProperty + polish
            btn.setProperty("class", "navBtn")
            self._nav_group.addButton(btn, index)
            btn.clicked.connect(lambda checked=False, i=index: self._set_nav(i))
            layout.addWidget(btn)
            self._nav_buttons.append(btn)
        layout.addStretch(1)
        # Apply class for stylesheet: Qt needs dynamic property + unpolish
        for btn in self._nav_buttons:
            btn.setProperty("class", "navBtn")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; padding: 14px 18px 12px 18px; color: #555; }"
                "QPushButton:checked { color: #111; font-weight: 600; border-bottom: 3px solid #222; }"
            )
        return frame

    def _set_nav(self, index: int) -> None:
        if 0 <= index < len(self._nav_buttons):
            self._nav_buttons[index].setChecked(True)
            self.stack.setCurrentIndex(index)

    def _build_bottom_bar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("bottomBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)

        help_btn = QPushButton("帮助")
        help_btn.setObjectName("helpBtn")
        help_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        help_btn.setStyleSheet("QPushButton { background: transparent; border: none; color: #666; padding: 6px 10px; }")
        help_btn.clicked.connect(self._show_help)
        refresh_btn = QPushButton("刷新")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setStyleSheet("QPushButton { background: transparent; border: none; color: #666; padding: 6px 10px; }")
        refresh_btn.clicked.connect(self._refresh_done)
        layout.addWidget(help_btn)
        layout.addWidget(refresh_btn)
        layout.addStretch(1)

        name_test = QPushButton("名称提取测试")
        name_test.setObjectName("nameTest")
        name_test.setCursor(Qt.CursorShape.PointingHandCursor)
        name_test.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #7C3AED; padding: 6px 12px; font-weight: 600; }"
        )
        name_test.clicked.connect(self._name_extract_dialog)
        layout.addWidget(name_test)

        self.stop_btn = QPushButton("■")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setToolTip("停止")
        self.stop_btn.clicked.connect(self._stop_job)
        layout.addWidget(self.stop_btn)

        self.start_btn = QPushButton("▶  开始")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self._start)
        layout.addWidget(self.start_btn)
        return frame

    # ---- pages ----
    def _build_run_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(10)
        self.progress = QLabel("进度: 0 / 0")
        self.progress.setStyleSheet("color: #555555; font-size: 13px;")
        layout.addWidget(self.progress)
        drop_hint = QLabel("可将视频文件拖到下方日志区进行单文件刮削")
        drop_hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(drop_hint)
        self.log = QPlainTextEdit()
        self.log.setObjectName("runLog")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        self.log.setAcceptDrops(True)
        self.log.dragEnterEvent = self._run_drag_enter  # type: ignore[method-assign]
        self.log.dropEvent = self._run_drop  # type: ignore[method-assign]
        layout.addWidget(self.log, 1)
        return page

    def _run_drag_enter(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def _run_drop(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls() if event.mimeData() else []
        videos = []
        for url in urls:
            local = url.toLocalFile()
            if local and Path(local).is_file():
                videos.append(Path(local))
        if not videos:
            return
        event.acceptProposedAction()
        # First file via single-file scrape; rest noted
        self.custom_file_edit.setText(str(videos[0]))
        if len(videos) > 1:
            self._append(f"拖入 {len(videos)} 个文件，先处理: {videos[0].name}")
        self._start_one_file()

    def _build_done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 12)
        card = QFrame()
        card.setProperty("class", "card")
        card.setStyleSheet("QFrame { background: white; border: 1px solid #E8E8E8; border-radius: 8px; }")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        title = QLabel("最近一次刮削摘要")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        card_layout.addWidget(title)
        self.done_summary = QLabel("尚未运行刮削。")
        self.done_summary.setWordWrap(True)
        self.done_summary.setStyleSheet("color: #444; font-size: 13px;")
        card_layout.addWidget(self.done_summary)
        self.done_list = QPlainTextEdit()
        self.done_list.setReadOnly(True)
        self.done_list.setPlaceholderText("成功 / 失败 / 跳过的文件行会显示在这里")
        card_layout.addWidget(self.done_list, 1)
        layout.addWidget(card, 1)
        return page

    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: white; border: 1px solid #E8E8E8; border-radius: 8px; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        label = QLabel(title)
        label.setStyleSheet("font-size: 14px; font-weight: 600; color: #222; border: none;")
        layout.addWidget(label)
        return frame, layout

    def _build_config_page(self, config: dict) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(16)

        # Film type toggle
        type_card, type_layout = self._card("影片类型")
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("刮削配置"))
        self.general_film_btn = QPushButton("一般影片")
        self.other_film_btn = QPushButton("其他影片")
        for btn in (self.general_film_btn, self.other_film_btn):
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._film_group = QButtonGroup(self)
        self._film_group.setExclusive(True)
        self._film_group.addButton(self.general_film_btn)
        self._film_group.addButton(self.other_film_btn)
        if self._film_type == "general":
            self.general_film_btn.setChecked(True)
        else:
            self.other_film_btn.setChecked(True)
        self.general_film_btn.toggled.connect(self._on_film_type_toggled)
        type_row.addWidget(self.general_film_btn)
        type_row.addWidget(self.other_film_btn)
        type_row.addStretch(1)
        type_layout.addLayout(type_row)
        type_hint = QLabel("切换后加载该类型的网站顺序、命名规则与翻译等设置；目录与代理为共用。")
        type_hint.setWordWrap(True)
        type_hint.setStyleSheet("color: #888; font-size: 12px; border: none;")
        type_layout.addWidget(type_hint)
        root.addWidget(type_card)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        root.addLayout(grid)

        # Directory (shared)
        dir_card, dir_layout = self._card("目录配置（共用）")
        media_row = QHBoxLayout()
        media_row.addWidget(QLabel("刮削源目录"))
        self.media_edit = QLineEdit(str(config.get("media_dir") or ""))
        self.media_edit.setPlaceholderText("视频所在目录")
        media_row.addWidget(self.media_edit, 1)
        media_btn = QPushButton("浏览")
        media_btn.setStyleSheet("QPushButton { background: white; border: 1px solid #D0D0D0; padding: 6px 12px; border-radius: 4px; }")
        media_btn.clicked.connect(self._browse_media)
        media_row.addWidget(media_btn)
        dir_layout.addLayout(media_row)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("主运行模式"))
        self.main_mode_combo = QComboBox()
        self._main_mode_items = [
            ("1", "1 · 整理+NFO+图片+改名并移动"),
            ("1_keep", "1_keep · 整理+NFO+图片+保留原名移动"),
            ("2", "2 · 仅按位置规则整理/移动"),
            ("4", "4 · 原地刮削（旁写 NFO/图片）"),
            ("5", "5 · 原地刮削并重命名"),
        ]
        for value, label in self._main_mode_items:
            self.main_mode_combo.addItem(label, value)
        mm = str(config.get("main_mode") or "4")
        if mm not in MAIN_MODES:
            mm = "4"
        idx = next((i for i, (v, _) in enumerate(self._main_mode_items) if v == mm), 3)
        self.main_mode_combo.setCurrentIndex(idx)
        self.main_mode_combo.currentIndexChanged.connect(self._sync_mode)
        mode_row.addWidget(self.main_mode_combo, 1)
        dir_layout.addLayout(mode_row)

        link_row = QHBoxLayout()
        link_row.addWidget(QLabel("整理方式"))
        self.link_move_radio = QRadioButton("移动")
        self.link_soft_radio = QRadioButton("软链接")
        self._link_group = QButtonGroup(self)
        self._link_group.addButton(self.link_move_radio)
        self._link_group.addButton(self.link_soft_radio)
        if config.get("link_mode") == "soft_link":
            self.link_soft_radio.setChecked(True)
        else:
            self.link_move_radio.setChecked(True)
        link_row.addWidget(self.link_move_radio)
        link_row.addWidget(self.link_soft_radio)
        link_note = QLabel("暂不支持硬链接/strm")
        link_note.setStyleSheet("color: #888; font-size: 12px; border: none;")
        link_row.addWidget(link_note)
        link_row.addStretch(1)
        dir_layout.addLayout(link_row)

        output_row = QHBoxLayout()
        self.output_label = QLabel("输出目录")
        output_row.addWidget(self.output_label)
        self.output_edit = QLineEdit(str(config.get("output_dir") or ""))
        self.output_edit.setPlaceholderText("模式 1 / 1_keep / 2 的输出根目录")
        output_row.addWidget(self.output_edit, 1)
        self.output_btn = QPushButton("浏览")
        self.output_btn.setStyleSheet("QPushButton { background: white; border: 1px solid #D0D0D0; padding: 6px 12px; border-radius: 4px; }")
        self.output_btn.clicked.connect(self._browse_output)
        output_row.addWidget(self.output_btn)
        dir_layout.addLayout(output_row)

        cfg_row = QHBoxLayout()
        self.config_path_label = QLabel("配置：未加载（使用内存默认，关闭不写盘）")
        self.config_path_label.setStyleSheet("color: #666; font-size: 12px; border: none;")
        self.config_path_label.setWordWrap(True)
        cfg_row.addWidget(self.config_path_label, 1)
        load_btn = QPushButton("加载配置")
        save_btn = QPushButton("保存")
        save_as_btn = QPushButton("另存为")
        for btn in (load_btn, save_btn, save_as_btn):
            btn.setStyleSheet("QPushButton { background: white; border: 1px solid #D0D0D0; padding: 6px 12px; border-radius: 4px; }")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        load_btn.clicked.connect(self._load_config_dialog)
        save_btn.clicked.connect(self._save_config_dialog)
        save_as_btn.clicked.connect(self._save_as_config_dialog)
        self.save_btn = save_btn
        cfg_row.addWidget(load_btn)
        cfg_row.addWidget(save_btn)
        cfg_row.addWidget(save_as_btn)
        dir_layout.addLayout(cfg_row)
        grid.addWidget(dir_card, 0, 0)

        # Network (shared)
        net_card, net_layout = self._card("网络与代理（共用）")
        proxy_top = QHBoxLayout()
        self.proxy_enabled = QCheckBox("启用代理")
        self.proxy_enabled.setChecked(bool(config.get("proxy_enabled", False)))
        self.proxy_enabled.toggled.connect(self._sync_proxy_enabled)
        proxy_top.addWidget(self.proxy_enabled)
        proxy_top.addStretch(1)
        net_layout.addLayout(proxy_top)
        host, port = _parse_proxy(str(config.get("proxy") or ""))
        proxy_row = QHBoxLayout()
        proxy_row.addWidget(QLabel("协议"))
        self.proxy_proto = QLineEdit("http")
        self.proxy_proto.setFixedWidth(70)
        self.proxy_proto.setReadOnly(True)
        proxy_row.addWidget(self.proxy_proto)
        proxy_row.addWidget(QLabel("地址"))
        self.proxy_host = QLineEdit(host)
        proxy_row.addWidget(self.proxy_host, 1)
        proxy_row.addWidget(QLabel("端口"))
        self.proxy_port = QLineEdit(port)
        self.proxy_port.setFixedWidth(70)
        proxy_row.addWidget(self.proxy_port)
        net_layout.addLayout(proxy_row)
        test_proxy = QPushButton("测试连接")
        test_proxy.setStyleSheet(
            "QPushButton { background: white; border: 1px solid #D0D0D0; padding: 8px; border-radius: 4px; }"
        )
        test_proxy.clicked.connect(self._test_proxy_message)
        net_layout.addWidget(test_proxy)
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("TMDB API Key"))
        self.tmdb_key_edit = QLineEdit(str(config.get("tmdb_key") or ""))
        self.tmdb_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.tmdb_key_edit.setPlaceholderText("没有 Key 时 TMDB 会跳过")
        key_row.addWidget(self.tmdb_key_edit, 1)
        net_layout.addLayout(key_row)
        grid.addWidget(net_card, 0, 1)

        # Common (per-mode)
        common_card, common_layout = self._card("常规 Common")
        self.skip_nfo_box = QCheckBox("跳过已有 NFO")
        self.download_images_box = QCheckBox("下载图片")
        self.download_missing_box = QCheckBox("仅下载缺失图片")
        self.print_nfo_box = QCheckBox("写入 NFO")
        self.extrafanart_box = QCheckBox("下载剧照 extrafanart")
        self.anonymous_fill_box = QCheckBox("匿名演员填充为「佚名」")
        self.actor_only_tag_box = QCheckBox("tag 只保留演员")
        self.trailer_box = QCheckBox("预告片（暂未实现）")
        self.storyline_box = QCheckBox("剧情扩展（暂未实现）")
        for box in (
            self.skip_nfo_box,
            self.download_images_box,
            self.download_missing_box,
            self.print_nfo_box,
            self.extrafanart_box,
            self.anonymous_fill_box,
            self.actor_only_tag_box,
            self.trailer_box,
            self.storyline_box,
        ):
            common_layout.addWidget(box)
        sleep_row = QHBoxLayout()
        sleep_row.addWidget(QLabel("文件间隔（秒）"))
        self.sleep_spin = QDoubleSpinBox()
        self.sleep_spin.setRange(0, 60)
        self.sleep_spin.setSingleStep(0.1)
        self.sleep_spin.setDecimals(1)
        sleep_row.addWidget(self.sleep_spin)
        sleep_row.addStretch(1)
        common_layout.addLayout(sleep_row)
        nfo_days_row = QHBoxLayout()
        nfo_days_row.addWidget(QLabel("NFO 跳过天数"))
        self.nfo_skip_spin = QSpinBox()
        self.nfo_skip_spin.setRange(0, 3650)
        nfo_days_row.addWidget(self.nfo_skip_spin)
        nfo_days_row.addWidget(QLabel("0=不按天数跳过"))
        nfo_days_row.addStretch(1)
        common_layout.addLayout(nfo_days_row)
        skip_note = QLabel("水印 / 人脸裁剪 / 后端托管 / OpenAI：本程序不提供。")
        skip_note.setWordWrap(True)
        skip_note.setStyleSheet("color: #888; font-size: 12px; border: none;")
        common_layout.addWidget(skip_note)
        grid.addWidget(common_card, 1, 0)

        # Translation / metadata extras
        meta_card, meta_layout = self._card("元数据 / 翻译")
        self.translate_box = QCheckBox("简介翻译为中文")
        meta_layout.addWidget(self.translate_box)
        self.jellyfin_box = QCheckBox("Jellyfin 模式（标记，行为与 Emby 兼容写入）")
        meta_layout.addWidget(self.jellyfin_box)
        self.kodi_actor_box = QCheckBox("Kodi 演员图片目录习惯（.actors）")
        self.kodi_actor_box.setChecked(True)
        self.kodi_actor_box.setEnabled(False)
        meta_layout.addWidget(self.kodi_actor_box)
        meta_hint = QLabel("一般影片默认可不翻译；其他影片可开翻译。演员头像仍写入 .actors。")
        meta_hint.setWordWrap(True)
        meta_hint.setStyleSheet("color: #888; font-size: 12px; border: none;")
        meta_layout.addWidget(meta_hint)
        meta_layout.addStretch(1)
        grid.addWidget(meta_card, 1, 1)

        # Sites
        sites_card, sites_layout = self._card("搜索网站（本类型）")
        sites_hint = QLabel("勾选后按从上到下顺序查询；严格匹配，对不上就换下一个。")
        sites_hint.setWordWrap(True)
        sites_hint.setStyleSheet("color: #888; font-size: 12px; border: none;")
        sites_layout.addWidget(sites_hint)
        sites_row = QHBoxLayout()
        self.site_list = QListWidget()
        sites_row.addWidget(self.site_list, 1)
        move_col = QVBoxLayout()
        up = QPushButton("上移")
        down = QPushButton("下移")
        for btn in (up, down):
            btn.setStyleSheet(
                "QPushButton { background: white; border: 1px solid #D0D0D0; padding: 6px 12px; border-radius: 4px; }"
            )
        up.clicked.connect(lambda: self._move_site(-1))
        down.clicked.connect(lambda: self._move_site(1))
        move_col.addWidget(up)
        move_col.addWidget(down)
        move_col.addStretch(1)
        sites_row.addLayout(move_col)
        sites_layout.addLayout(sites_row)
        tpdb_row = QHBoxLayout()
        tpdb_row.addWidget(QLabel("TPDB Token"))
        self.tpdb_edit = QLineEdit()
        self.tpdb_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.tpdb_edit.setPlaceholderText("可选；空则跳过（刮削器暂未接入）")
        tpdb_row.addWidget(self.tpdb_edit, 1)
        sites_layout.addLayout(tpdb_row)
        grid.addWidget(sites_card, 2, 0)

        # Naming
        name_card, name_layout = self._card("命名规则（本类型）")
        loc_row = QHBoxLayout()
        loc_row.addWidget(QLabel("文件夹规则"))
        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("如 actor+'/'+number 或 genres+'/'+title")
        loc_row.addWidget(self.location_edit, 1)
        name_layout.addLayout(loc_row)
        nam_row = QHBoxLayout()
        nam_row.addWidget(QLabel("文件命名"))
        self.naming_edit = QLineEdit()
        self.naming_edit.setPlaceholderText("如 number+'-'+title 或 title.year")
        nam_row.addWidget(self.naming_edit, 1)
        name_layout.addLayout(nam_row)
        max_row = QHBoxLayout()
        max_row.addWidget(QLabel("标题最大长度"))
        self.max_title_spin = QSpinBox()
        self.max_title_spin.setRange(10, 200)
        max_row.addWidget(self.max_title_spin)
        self.uppercase_box = QCheckBox("番号大写")
        max_row.addWidget(self.uppercase_box)
        max_row.addStretch(1)
        name_layout.addLayout(max_row)
        del_row = QHBoxLayout()
        del_row.addWidget(QLabel("标题删除字符"))
        self.delete_chars_edit = QLineEdit()
        self.delete_chars_edit.setPlaceholderText("这些字符会从命名结果中去掉")
        del_row.addWidget(self.delete_chars_edit, 1)
        name_layout.addLayout(del_row)
        excl_num_row = QHBoxLayout()
        excl_num_row.addWidget(QLabel("号码提取排除"))
        self.number_exclude_edit = QLineEdit()
        self.number_exclude_edit.setPlaceholderText("逗号分隔，如 xxx.com@,bbb.net")
        excl_num_row.addWidget(self.number_exclude_edit, 1)
        name_layout.addLayout(excl_num_row)
        token_hint = QLabel(
            "可用 token：title / original_title / actor / studio / director / release / year / "
            "number / tag / genres / runtime / series / prefix / letter / season / episode / suffix；"
            "outline 不参与路径。支持 genres/title、actor/[number]-title、title.year 与 + 引号拼接。"
        )
        token_hint.setWordWrap(True)
        token_hint.setStyleSheet("color: #888; font-size: 12px; border: none;")
        name_layout.addWidget(token_hint)
        grid.addWidget(name_card, 2, 1)

        # Exclusion
        excl_card, excl_layout = self._card("扫描排除（本类型）")
        fold_row = QHBoxLayout()
        fold_row.addWidget(QLabel("排除文件夹"))
        self.excluded_folders_edit = QLineEdit()
        self.excluded_folders_edit.setPlaceholderText("逗号分隔，如 failed,.actors,output")
        fold_row.addWidget(self.excluded_folders_edit, 1)
        excl_layout.addLayout(fold_row)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("忽略小于（MB）"))
        self.excluded_size_spin = QDoubleSpinBox()
        self.excluded_size_spin.setRange(0, 10000)
        self.excluded_size_spin.setDecimals(1)
        size_row.addWidget(self.excluded_size_spin)
        size_row.addWidget(QLabel("0=不按大小过滤"))
        size_row.addStretch(1)
        excl_layout.addLayout(size_row)
        excl_layout.addStretch(1)
        grid.addWidget(excl_card, 3, 0, 1, 2)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        root.addStretch(1)

        self._apply_mode_to_ui(self._film_type)
        return page

    def _build_custom_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(16)

        scrape_card, scrape_layout = self._card("单文件刮削")
        row = QHBoxLayout()
        self.custom_file_edit = QLineEdit()
        self.custom_file_edit.setPlaceholderText("选择一个视频文件")
        row.addWidget(self.custom_file_edit, 1)
        browse = QPushButton("浏览")
        browse.setStyleSheet(
            "QPushButton { background: white; border: 1px solid #D0D0D0; padding: 6px 12px; border-radius: 4px; }"
        )
        browse.clicked.connect(self._browse_custom_file)
        row.addWidget(browse)
        scrape_layout.addLayout(row)
        start_one = QPushButton("开始刮削该文件")
        start_one.setStyleSheet(
            "QPushButton { background: #2563EB; color: white; border: none; border-radius: 6px; padding: 10px 16px; font-weight: 600; }"
        )
        start_one.clicked.connect(self._start_one_file)
        scrape_layout.addWidget(start_one)
        layout.addWidget(scrape_card)

        name_card, name_layout = self._card("名称提取测试")
        name_row = QHBoxLayout()
        self.name_test_edit = QLineEdit()
        self.name_test_edit.setPlaceholderText("输入或粘贴文件名，例如 SSNI-001.mp4")
        name_row.addWidget(self.name_test_edit, 1)
        parse_btn = QPushButton("解析")
        parse_btn.setStyleSheet(
            "QPushButton { background: #7C3AED; color: white; border: none; border-radius: 6px; padding: 8px 16px; font-weight: 600; }"
        )
        parse_btn.clicked.connect(self._run_name_test)
        name_row.addWidget(parse_btn)
        name_layout.addLayout(name_row)
        self.name_test_result = QLabel("番号 / 标题 / 年份 / IMDb 会显示在这里")
        self.name_test_result.setWordWrap(True)
        self.name_test_result.setStyleSheet("color: #444; border: none;")
        name_layout.addWidget(self.name_test_result)
        layout.addWidget(name_card)
        layout.addStretch(1)
        return page

    def _build_actors_page(self, config: dict) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(16)

        left, left_layout = self._card("媒体服务器配置")
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("服务器类型"))
        self.emby_btn = QPushButton("Emby")
        self.jelly_btn = QPushButton("Jellyfin")
        for btn in (self.emby_btn, self.jelly_btn):
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._server_group = QButtonGroup(self)
        self._server_group.setExclusive(True)
        self._server_group.addButton(self.emby_btn)
        self._server_group.addButton(self.jelly_btn)
        if config.get("emby_type") == "jellyfin":
            self.jelly_btn.setChecked(True)
        else:
            self.emby_btn.setChecked(True)
        self.emby_btn.toggled.connect(self._sync_server_toggle_style)
        self._sync_server_toggle_style()
        type_row.addWidget(self.emby_btn)
        type_row.addWidget(self.jelly_btn)
        type_row.addStretch(1)
        left_layout.addLayout(type_row)

        left_layout.addWidget(QLabel("服务器地址"))
        self.emby_url_edit = QLineEdit(str(config.get("emby_url") or ""))
        self.emby_url_edit.setPlaceholderText("http://127.0.0.1:8096")
        left_layout.addWidget(self.emby_url_edit)

        left_layout.addWidget(QLabel("API 密钥"))
        self.emby_key_edit = QLineEdit(str(config.get("emby_api_key") or ""))
        self.emby_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        left_layout.addWidget(self.emby_key_edit)

        left_layout.addWidget(QLabel("用户 ID（可选）"))
        self.emby_user_edit = QLineEdit(str(config.get("emby_user_id") or ""))
        hint = QLabel("若填写，只获取该用户可访问媒体库中的演员")
        hint.setStyleSheet("color: #888; font-size: 12px; border: none;")
        left_layout.addWidget(self.emby_user_edit)
        left_layout.addWidget(hint)

        save_test = QPushButton("保存连接配置并测试")
        save_test.setStyleSheet(
            "QPushButton { background: #2563EB; color: white; border: none; border-radius: 6px; padding: 10px 16px; font-weight: 600; }"
        )
        save_test.clicked.connect(self._save_and_test_emby)
        left_layout.addWidget(save_test)
        left_layout.addStretch(1)
        layout.addWidget(left, 1)

        right, right_layout = self._card("演员头像管理")
        right_layout.addWidget(QLabel("头像来源库"))
        src_row = QHBoxLayout()
        self.gfriends_radio = QRadioButton("Gfriends")
        self.local_avatar_radio = QRadioButton("本地头像库")
        self._avatar_group = QButtonGroup(self)
        self._avatar_group.addButton(self.gfriends_radio)
        self._avatar_group.addButton(self.local_avatar_radio)
        if config.get("actor_avatar_source") == "local":
            self.local_avatar_radio.setChecked(True)
        else:
            self.gfriends_radio.setChecked(True)
        self.gfriends_radio.toggled.connect(self._sync_avatar_source)
        src_row.addWidget(self.gfriends_radio)
        src_row.addWidget(self.local_avatar_radio)
        src_row.addStretch(1)
        right_layout.addLayout(src_row)

        local_row = QHBoxLayout()
        self.actor_local_label = QLabel("本地目录")
        local_row.addWidget(self.actor_local_label)
        self.actor_local_edit = QLineEdit(str(config.get("actor_local_dir") or ""))
        local_row.addWidget(self.actor_local_edit, 1)
        self.actor_local_btn = QPushButton("浏览")
        self.actor_local_btn.setStyleSheet(
            "QPushButton { background: white; border: 1px solid #D0D0D0; padding: 6px 12px; border-radius: 4px; }"
        )
        self.actor_local_btn.clicked.connect(self._browse_actor_local)
        local_row.addWidget(self.actor_local_btn)
        right_layout.addLayout(local_row)

        fill_btn = QPushButton("开始补全缺失头像")
        fill_btn.setStyleSheet(
            "QPushButton { background: #7C3AED; color: white; border: none; border-radius: 6px; padding: 10px 16px; font-weight: 600; }"
        )
        fill_btn.clicked.connect(self._start_avatar_fill)
        right_layout.addWidget(fill_btn)
        note = QLabel("补全过程日志写到「运行」页。Gfriends 使用公开 Filetree；网络失败会明确记日志。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 12px; border: none;")
        right_layout.addWidget(note)
        right_layout.addStretch(1)
        layout.addWidget(right, 1)
        return page

    def _build_lang_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 12)
        card, card_layout = self._card("语言 / 关于")
        card_layout.addWidget(QLabel("当前界面：简体中文"))
        card_layout.addWidget(QLabel(f"版本：MovieScraper v{__version__}"))
        note = QLabel("暂未实现完整多语言切换。界面文案均为简体中文。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #666; border: none;")
        card_layout.addWidget(note)
        card_layout.addStretch(1)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _sync_server_toggle_style(self) -> None:
        on = "QPushButton { background: #2563EB; color: white; border: none; border-radius: 4px; padding: 8px 18px; }"
        off = "QPushButton { background: white; color: #444; border: 1px solid #D0D0D0; border-radius: 4px; padding: 8px 18px; }"
        self.emby_btn.setStyleSheet(on if self.emby_btn.isChecked() else off)
        self.jelly_btn.setStyleSheet(on if self.jelly_btn.isChecked() else off)

    def _sync_avatar_source(self) -> None:
        local = self.local_avatar_radio.isChecked()
        self.actor_local_label.setEnabled(local)
        self.actor_local_edit.setEnabled(local)
        self.actor_local_btn.setEnabled(local)

    def _sync_proxy_enabled(self) -> None:
        on = self.proxy_enabled.isChecked()
        for widget in (self.proxy_proto, self.proxy_host, self.proxy_port):
            widget.setEnabled(on)

    def _sync_mode(self) -> None:
        main_mode = self.main_mode_combo.currentData()
        needs_out = main_mode in {"1", "1_keep", "2"}
        self.output_label.setEnabled(needs_out)
        self.output_edit.setEnabled(needs_out)
        self.output_btn.setEnabled(needs_out)
        soft_ok = needs_out
        self.link_move_radio.setEnabled(soft_ok)
        self.link_soft_radio.setEnabled(soft_ok)

    def _move_site(self, delta: int) -> None:
        row = self.site_list.currentRow()
        if row < 0:
            return
        target = row + delta
        if target < 0 or target >= self.site_list.count():
            return
        item = self.site_list.takeItem(row)
        self.site_list.insertItem(target, item)
        self.site_list.setCurrentRow(target)

    def _sites(self) -> list[dict]:
        sites = []
        for index in range(self.site_list.count()):
            item = self.site_list.item(index)
            sites.append({
                "name": item.data(Qt.ItemDataRole.UserRole),
                "enabled": item.checkState() == Qt.CheckState.Checked,
            })
        return normalize_sites(sites, film_type=self._film_type)

    def _proxy_url(self) -> str:
        host = self.proxy_host.text().strip() or "localhost"
        port = self.proxy_port.text().strip() or "1080"
        return f"http://{host}:{port}"

    def _sync_film_type_style(self) -> None:
        on = "QPushButton { background: #2563EB; color: white; border: none; border-radius: 4px; padding: 8px 18px; }"
        off = "QPushButton { background: white; color: #444; border: 1px solid #D0D0D0; border-radius: 4px; padding: 8px 18px; }"
        self.general_film_btn.setStyleSheet(on if self.general_film_btn.isChecked() else off)
        self.other_film_btn.setStyleSheet(on if self.other_film_btn.isChecked() else off)

    def _on_film_type_toggled(self, checked: bool) -> None:
        if not checked:
            return
        self._capture_mode_from_ui()
        self._film_type = "general" if self.general_film_btn.isChecked() else "other"
        self._apply_mode_to_ui(self._film_type)
        self._sync_film_type_style()

    def _fill_site_list(self, sites: list[dict]) -> None:
        self.site_list.clear()
        for item in normalize_sites(sites, film_type=self._film_type):
            label = SITE_LABELS.get(item["name"], item["name"])
            row_item = QListWidgetItem(label)
            row_item.setData(Qt.ItemDataRole.UserRole, item["name"])
            row_item.setFlags(row_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row_item.setCheckState(
                Qt.CheckState.Checked if item["enabled"] else Qt.CheckState.Unchecked
            )
            self.site_list.addItem(row_item)

    def _capture_mode_from_ui(self) -> None:
        if not hasattr(self, "site_list"):
            return
        self._mode_cache[self._film_type] = {
            "sites": self._sites(),
            "skip_existing_nfo": self.skip_nfo_box.isChecked(),
            "translate_plot": self.translate_box.isChecked(),
            "download_images": self.download_images_box.isChecked(),
            "download_missing_only": self.download_missing_box.isChecked(),
            "sleep_seconds": float(self.sleep_spin.value()),
            "print_nfo": self.print_nfo_box.isChecked(),
            "nfo_skip_days": int(self.nfo_skip_spin.value()),
            "excluded_folders": self.excluded_folders_edit.text().strip(),
            "excluded_size_mb": float(self.excluded_size_spin.value()),
            "location_rule": self.location_edit.text().strip(),
            "naming_rule": self.naming_edit.text().strip(),
            "max_title_len": int(self.max_title_spin.value()),
            "delete_chars": self.delete_chars_edit.text(),
            "number_exclude_chars": self.number_exclude_edit.text().strip(),
            "uppercase_name": self.uppercase_box.isChecked(),
            "jellyfin_mode": self.jellyfin_box.isChecked(),
            "actor_photo_kodi": True,
            "anonymous_fill": self.anonymous_fill_box.isChecked(),
            "actor_only_tag": self.actor_only_tag_box.isChecked(),
            "tpdb_token": self.tpdb_edit.text().strip(),
            "extrafanart": self.extrafanart_box.isChecked(),
            "trailer": self.trailer_box.isChecked(),
            "storyline": self.storyline_box.isChecked(),
        }

    def _apply_mode_to_ui(self, film_type: str) -> None:
        mode = dict(self._mode_cache.get(film_type) or {})
        if not mode.get("sites"):
            mode["sites"] = default_sites(film_type)
        self._fill_site_list(mode.get("sites") or [])
        self.skip_nfo_box.setChecked(bool(mode.get("skip_existing_nfo", True)))
        self.translate_box.setChecked(bool(mode.get("translate_plot", film_type != "general")))
        self.download_images_box.setChecked(bool(mode.get("download_images", True)))
        self.download_missing_box.setChecked(bool(mode.get("download_missing_only", False)))
        self.print_nfo_box.setChecked(bool(mode.get("print_nfo", True)))
        self.extrafanart_box.setChecked(bool(mode.get("extrafanart", True)))
        self.trailer_box.setChecked(bool(mode.get("trailer", False)))
        self.storyline_box.setChecked(bool(mode.get("storyline", False)))
        self.sleep_spin.setValue(float(mode.get("sleep_seconds") or 0.3))
        self.nfo_skip_spin.setValue(int(mode.get("nfo_skip_days") or 0))
        self.jellyfin_box.setChecked(bool(mode.get("jellyfin_mode", False)))
        self.location_edit.setText(str(mode.get("location_rule") or (
            "genres+'/'+title" if film_type == "general" else "actor+'/'+number"
        )))
        self.naming_edit.setText(str(mode.get("naming_rule") or (
            "title.year" if film_type == "general" else "number+'-'+title"
        )))
        self.max_title_spin.setValue(int(mode.get("max_title_len") or 80))
        self.delete_chars_edit.setText(str(mode.get("delete_chars") or ""))
        self.number_exclude_edit.setText(str(mode.get("number_exclude_chars") or ""))
        self.uppercase_box.setChecked(bool(mode.get("uppercase_name", False)))
        self.anonymous_fill_box.setChecked(bool(mode.get("anonymous_fill", film_type == "other")))
        self.actor_only_tag_box.setChecked(bool(mode.get("actor_only_tag", False)))
        self.excluded_folders_edit.setText(str(mode.get("excluded_folders") or "failed,.actors"))
        self.excluded_size_spin.setValue(float(mode.get("excluded_size_mb") or 0))
        self.tpdb_edit.setText(str(mode.get("tpdb_token") or ""))
        # TPDB more relevant for other; still visible for both
        self.tpdb_edit.setEnabled(True)

    def _settings(self) -> dict:
        self._capture_mode_from_ui()
        film_type = "general" if self.general_film_btn.isChecked() else "other"
        self._film_type = film_type
        main_mode = self.main_mode_combo.currentData() or "4"
        return {
            "film_type": film_type,
            "media_dir": self.media_edit.text().strip(),
            "output_dir": self.output_edit.text().strip(),
            "main_mode": main_mode,
            "link_mode": "soft_link" if self.link_soft_radio.isChecked() else "move",
            "output_mode": "folder" if main_mode in {"1", "1_keep", "2"} else "beside",
            "tmdb_key": self.tmdb_key_edit.text().strip(),
            "proxy": self._proxy_url(),
            "proxy_enabled": self.proxy_enabled.isChecked(),
            "emby_type": "jellyfin" if self.jelly_btn.isChecked() else "emby",
            "emby_url": self.emby_url_edit.text().strip(),
            "emby_api_key": self.emby_key_edit.text().strip(),
            "emby_user_id": self.emby_user_edit.text().strip(),
            "actor_avatar_source": "local" if self.local_avatar_radio.isChecked() else "gfriends",
            "actor_local_dir": self.actor_local_edit.text().strip(),
            "general": dict(self._mode_cache.get("general") or {}),
            "other": dict(self._mode_cache.get("other") or {}),
            # Flatten active mode for scrape callers / CLI parity
            **dict(self._mode_cache.get(film_type) or {}),
        }

    def _remember(self) -> None:
        """No automatic disk write. Config is saved only via 保存 / 另存为."""

        return

    def _refresh_config_path_label(self) -> None:
        path = get_config_path() or self._config_path
        if path:
            self.config_path_label.setText(f"配置：{path}")
            self.save_btn.setEnabled(True)
        else:
            self.config_path_label.setText("配置：未加载（使用内存默认，关闭不写盘）")
            self.save_btn.setEnabled(False)

    def _apply_loaded_config(self, config: dict) -> None:
        self._film_type = config.get("film_type") if config.get("film_type") in {"general", "other"} else "other"
        self._mode_cache = {
            "general": dict(config.get("general") or {}),
            "other": dict(config.get("other") or {}),
        }
        self.general_film_btn.blockSignals(True)
        self.other_film_btn.blockSignals(True)
        if self._film_type == "general":
            self.general_film_btn.setChecked(True)
        else:
            self.other_film_btn.setChecked(True)
        self.general_film_btn.blockSignals(False)
        self.other_film_btn.blockSignals(False)
        self._sync_film_type_style()
        self.media_edit.setText(str(config.get("media_dir") or ""))
        self.output_edit.setText(str(config.get("output_dir") or ""))
        mm = str(config.get("main_mode") or "4")
        idx = next((i for i, (v, _) in enumerate(self._main_mode_items) if v == mm), 3)
        self.main_mode_combo.setCurrentIndex(idx)
        if config.get("link_mode") == "soft_link":
            self.link_soft_radio.setChecked(True)
        else:
            self.link_move_radio.setChecked(True)
        self.proxy_enabled.setChecked(bool(config.get("proxy_enabled", False)))
        host, port = _parse_proxy(str(config.get("proxy") or ""))
        self.proxy_host.setText(host)
        self.proxy_port.setText(port)
        self.tmdb_key_edit.setText(str(config.get("tmdb_key") or ""))
        if config.get("emby_type") == "jellyfin":
            self.jelly_btn.setChecked(True)
        else:
            self.emby_btn.setChecked(True)
        self.emby_url_edit.setText(str(config.get("emby_url") or ""))
        self.emby_key_edit.setText(str(config.get("emby_api_key") or ""))
        self.emby_user_edit.setText(str(config.get("emby_user_id") or ""))
        if config.get("actor_avatar_source") == "local":
            self.local_avatar_radio.setChecked(True)
        else:
            self.gfriends_radio.setChecked(True)
        self.actor_local_edit.setText(str(config.get("actor_local_dir") or ""))
        self._apply_mode_to_ui(self._film_type)
        self._sync_mode()
        self._sync_proxy_enabled()
        self._sync_avatar_source()
        self._config_path = get_config_path()
        self._refresh_config_path_label()

    def _load_config_dialog(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "加载配置", str(Path.home()), "JSON (*.json);;All (*.*)"
        )
        if not chosen:
            return
        try:
            config = load_config_from(chosen)
        except OSError as exc:
            QMessageBox.warning(self, "加载配置", str(exc))
            return
        self._apply_loaded_config(config)
        self._append(f"已加载配置: {chosen}")

    def _save_config_dialog(self) -> None:
        path = get_config_path() or self._config_path
        if not path:
            self._save_as_config_dialog()
            return
        try:
            save_config(self._settings(), path)
        except OSError as exc:
            QMessageBox.warning(self, "保存配置", str(exc))
            return
        self._config_path = get_config_path()
        self._refresh_config_path_label()
        self._append(f"已保存配置: {path}")

    def _save_as_config_dialog(self) -> None:
        chosen, _ = QFileDialog.getSaveFileName(
            self, "另存为配置", str(Path.home() / "movie-scraper-config.json"), "JSON (*.json);;All (*.*)"
        )
        if not chosen:
            return
        if not chosen.lower().endswith(".json"):
            chosen = chosen + ".json"
        try:
            save_config(self._settings(), chosen)
        except OSError as exc:
            QMessageBox.warning(self, "另存为", str(exc))
            return
        self._config_path = get_config_path()
        self._refresh_config_path_label()
        self._append(f"已另存为: {chosen}")

    def _append(self, message: str) -> None:
        self.log.appendPlainText(message)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        self._track_summary(message)

    def _track_summary(self, message: str) -> None:
        text = str(message)
        if "已有 NFO，跳过" in text or "跳过" in text and "NFO" in text:
            self._summary["skip"] += 1
            self._summary["lines"].append(f"[跳过] {text}")
        elif text.startswith("处理失败") or "上传失败" in text or "下载失败" in text:
            self._summary["fail"] += 1
            self._summary["lines"].append(f"[失败] {text}")
        elif text.startswith("写入 ") or "已上传头像" in text:
            self._summary["success"] += 1
            self._summary["lines"].append(f"[成功] {text}")
        elif " -> IMDb " in text:
            self._summary["lines"].append(text)
        # keep recent
        if len(self._summary["lines"]) > 200:
            self._summary["lines"] = self._summary["lines"][-200:]

    def _refresh_done(self) -> None:
        s = self._summary
        self.done_summary.setText(
            f"成功 {s['success']}　失败 {s['fail']}　跳过 {s['skip']}"
        )
        self.done_list.setPlainText("\n".join(s["lines"][-80:]) or "暂无记录")

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "帮助",
            "本地电影元数据刮削。\n\n"
            "1. 在「本地配置」选择一般影片/其他影片、主运行模式，再设目录与命名规则。\n"
            "2. 用「加载配置 / 保存 / 另存为」管理配置；默认不写盘，exe 旁不会自动生成配置。\n"
            "3. 点底部绿色「开始」批量刮削；也可把视频拖到「运行」日志区。\n"
            "4. 「自定义刮削」可单文件刮削或名称提取测试；「演员」可补全 Emby/Jellyfin 头像。\n"
            f"无登录、无到期限制。当前版本：v{__version__}",
        )

    def _browse_media(self) -> None:
        current = self.media_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择刮削源目录", current)
        if chosen:
            self.media_edit.setText(chosen)

    def _browse_output(self) -> None:
        current = self.output_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择输出目录", current)
        if chosen:
            self.output_edit.setText(chosen)

    def _browse_custom_file(self) -> None:
        current = self.custom_file_edit.text().strip() or str(Path.home())
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "选择视频文件",
            current,
            "Video (*.mkv *.mp4 *.avi *.wmv *.ts *.m2ts *.iso *.rmvb *.flv *.mov);;All (*.*)",
        )
        if chosen:
            self.custom_file_edit.setText(chosen)

    def _browse_actor_local(self) -> None:
        current = self.actor_local_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择本地头像库", current)
        if chosen:
            self.actor_local_edit.setText(chosen)

    def _test_proxy_message(self) -> None:
        if not self.proxy_enabled.isChecked():
            QMessageBox.information(self, "代理", "当前未启用代理。")
            return
        QMessageBox.information(self, "代理", f"将使用代理：{self._proxy_url()}\n实际连通性在刮削请求时验证。")

    def _run_name_test(self) -> None:
        name = self.name_test_edit.text().strip()
        if not name:
            self.name_test_result.setText("请输入文件名")
            return
        parsed = parse_filename(name)
        self.name_test_result.setText(
            f"番号: {parsed.code or '-'}\n"
            f"标题: {parsed.title or '-'}\n"
            f"年份: {parsed.year or '-'}\n"
            f"IMDb: {parsed.imdb_id or '-'}"
        )

    def _name_extract_dialog(self) -> None:
        self._set_nav(3)
        self.name_test_edit.setFocus()
        if self.name_test_edit.text().strip():
            self._run_name_test()

    def _busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _begin_job(self, kind: str) -> bool:
        if self._busy():
            self._append("已有任务正在运行，请先停止或等待结束")
            self._set_nav(0)
            return False
        self._job_kind = kind
        self._summary = {"success": 0, "fail": 0, "skip": 0, "lines": []}
        self._stop.clear()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._set_nav(0)
        return True

    def _start(self) -> None:
        settings = self._settings()
        if not settings["media_dir"]:
            self._append("请填写刮削源目录（本地配置）")
            self._set_nav(2)
            return
        if not Path(settings["media_dir"]).is_dir():
            self._append(f"刮削源目录不存在: {settings['media_dir']}")
            self._set_nav(0)
            return
        if settings.get("main_mode") in {"1", "1_keep", "2"} and not settings["output_dir"]:
            self._append("当前主运行模式请填写输出目录")
            self._set_nav(2)
            return
        if not self._begin_job("scrape"):
            return
        self._remember()
        self._append("======== 开始刮削 ========")

        def log(message: str) -> None:
            self._queue.put(("log", message))

        def progress(index: int, total: int, name: str) -> None:
            self._queue.put(("progress", (index, total, name)))

        def target() -> None:
            try:
                run_job(settings, self._stop.is_set, log, progress)
            except Exception as exc:
                log(f"错误: {exc}")
            finally:
                self._queue.put(("done", None))

        self._thread = threading.Thread(target=target, name="scrape", daemon=True)
        self._thread.start()

    def _start_one_file(self) -> None:
        path = self.custom_file_edit.text().strip()
        if not path:
            self._append("请选择要刮削的文件")
            return
        video = Path(path)
        if not video.is_file():
            self._append(f"文件不存在: {path}")
            return
        settings = self._settings()
        if settings.get("main_mode") in {"1", "1_keep", "2"} and not settings["output_dir"]:
            self._append("当前主运行模式请在本地配置填写输出目录")
            self._set_nav(2)
            return
        if not self._begin_job("one"):
            return
        self._remember()
        self._append(f"======== 单文件刮削: {video.name} ========")

        def log(message: str) -> None:
            self._queue.put(("log", message))

        def progress(index: int, total: int, name: str) -> None:
            self._queue.put(("progress", (index, total, name)))

        def target() -> None:
            try:
                run_one_file(settings, video, self._stop.is_set, log, progress)
            except Exception as exc:
                log(f"错误: {exc}")
            finally:
                self._queue.put(("done", None))

        self._thread = threading.Thread(target=target, name="scrape-one", daemon=True)
        self._thread.start()

    def _save_and_test_emby(self) -> None:
        self._remember()
        from scraper.emby_actors import test_connection

        settings = self._settings()
        ok, message = test_connection(
            settings["emby_type"],
            settings["emby_url"],
            settings["emby_api_key"],
            settings["emby_user_id"],
            proxy=effective_proxy(settings) or None,
        )
        self._append(message)
        self._set_nav(0)
        if ok:
            QMessageBox.information(self, "媒体服务器", message)
        else:
            QMessageBox.warning(self, "媒体服务器", message)

    def _start_avatar_fill(self) -> None:
        settings = self._settings()
        if not settings["emby_url"] or not settings["emby_api_key"]:
            QMessageBox.warning(self, "演员头像", "请先填写服务器地址和 API 密钥")
            return
        if settings["actor_avatar_source"] == "local" and not settings["actor_local_dir"]:
            QMessageBox.warning(self, "演员头像", "请选择本地头像库目录")
            return
        if not self._begin_job("avatars"):
            return
        self._remember()
        self._append("======== 开始补全缺失头像 ========")

        def log(message: str) -> None:
            self._queue.put(("log", message))

        def target() -> None:
            try:
                from scraper.emby_actors import fill_missing_avatars

                fill_missing_avatars(
                    server_type=settings["emby_type"],
                    url=settings["emby_url"],
                    api_key=settings["emby_api_key"],
                    user_id=settings["emby_user_id"],
                    source=settings["actor_avatar_source"],
                    local_dir=settings["actor_local_dir"],
                    proxy=effective_proxy(settings) or None,
                    cache_dir=APP_DIR,
                    stop_check=self._stop.is_set,
                    log=log,
                )
            except Exception as exc:
                log(f"错误: {exc}")
            finally:
                self._queue.put(("done", None))

        self._thread = threading.Thread(target=target, name="avatars", daemon=True)
        self._thread.start()

    def _stop_job(self) -> None:
        if not self._busy():
            return
        self._stop.set()
        self._append("正在停止，将在当前步骤结束后停下")

    def _drain(self) -> None:
        while True:
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                return
            if kind == "log":
                self._append(str(payload))
            elif kind == "progress":
                index, total, name = payload
                extra = f"  {name}" if name else ""
                self.progress.setText(f"进度: {index} / {total}{extra}")
            elif kind == "done":
                self.start_btn.setEnabled(True)
                self.stop_btn.setEnabled(False)
                self._refresh_done()
                self._append("======== 任务结束 ========")

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop.set()
        # Do not auto-write config beside exe; only 保存/另存为 persist settings.
        event.accept()


def launch(argv: list[str] | None = None) -> int:
    application = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    application.setStyle("Fusion")
    application.setFont(_pick_font())
    application.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    return application.exec()
