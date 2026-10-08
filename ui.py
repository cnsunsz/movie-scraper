"""Desktop window for the movie scraper (PySide6)."""

from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

def _load_extra_qt_libs() -> None:
    """This Linux image has no libEGL / xcb helpers. Load copies from ~/.local/qt-libs if present.

    Changing LD_LIBRARY_PATH after startup is ignored by glibc, so open the
    sonames with RTLD_GLOBAL before importing Qt. Windows does not use this.
    """
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

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import load_config, run_job, save_config
from scraper.sources import SITE_LABELS, normalize_sites


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
            return QFont(name, 11)
    return QFont()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("电影元数据刮削")
        self.resize(980, 720)
        self.setMinimumSize(860, 600)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue = queue.Queue()

        config = load_config()
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_scrape_tab(config), "刮削")
        self.tabs.addTab(self._build_sites_tab(config), "网站")

        self._sync_mode()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._drain)
        self._timer.start(150)

    def _build_scrape_tab(self, config: dict) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        folder_box = QGroupBox("目录")
        folder_layout = QVBoxLayout(folder_box)
        media_row = QHBoxLayout()
        media_row.addWidget(QLabel("媒体目录"))
        self.media_edit = QLineEdit(str(config.get("media_dir") or ""))
        self.media_edit.setPlaceholderText("选择存放视频的文件夹")
        media_row.addWidget(self.media_edit, 1)
        media_btn = QPushButton("浏览")
        media_btn.clicked.connect(self._browse_media)
        media_row.addWidget(media_btn)
        folder_layout.addLayout(media_row)

        self.beside_radio = QRadioButton("旁边写文件")
        self.folder_radio = QRadioButton("按演员/标题改名并移动")
        self._modes = QButtonGroup(self)
        self._modes.addButton(self.beside_radio)
        self._modes.addButton(self.folder_radio)
        if config.get("output_mode") == "folder":
            self.folder_radio.setChecked(True)
        else:
            self.beside_radio.setChecked(True)
        self.beside_radio.toggled.connect(self._sync_mode)
        self.folder_radio.toggled.connect(self._sync_mode)
        mode_row = QHBoxLayout()
        mode_row.addWidget(self.beside_radio)
        mode_row.addWidget(self.folder_radio)
        mode_row.addStretch(1)
        folder_layout.addLayout(mode_row)

        output_row = QHBoxLayout()
        self.output_label = QLabel("输出目录")
        output_row.addWidget(self.output_label)
        self.output_edit = QLineEdit(str(config.get("output_dir") or ""))
        self.output_edit.setPlaceholderText("仅移动模式需要")
        output_row.addWidget(self.output_edit, 1)
        self.output_btn = QPushButton("浏览")
        self.output_btn.clicked.connect(self._browse_output)
        output_row.addWidget(self.output_btn)
        folder_layout.addLayout(output_row)
        layout.addWidget(folder_box)

        option_box = QGroupBox("选项")
        option_layout = QHBoxLayout(option_box)
        from PySide6.QtWidgets import QCheckBox
        self.skip_nfo_box = QCheckBox("跳过已有 NFO")
        self.skip_nfo_box.setChecked(bool(config.get("skip_existing_nfo", True)))
        self.translate_box = QCheckBox("简介翻译为中文")
        self.translate_box.setChecked(bool(config.get("translate_plot", True)))
        option_layout.addWidget(self.skip_nfo_box)
        option_layout.addWidget(self.translate_box)
        option_layout.addStretch(1)
        layout.addWidget(option_box)

        actions = QHBoxLayout()
        self.start_btn = QPushButton("开始")
        self.start_btn.setObjectName("start")
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("stop")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self._stop_job)
        self.progress = QLabel("进度: 0 / 0")
        actions.addWidget(self.start_btn)
        actions.addWidget(self.stop_btn)
        actions.addWidget(self.progress)
        actions.addStretch(1)
        layout.addLayout(actions)

        log_box = QGroupBox("日志")
        log_layout = QVBoxLayout(log_box)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        log_layout.addWidget(self.log)
        layout.addWidget(log_box, 1)
        return page

    def _build_sites_tab(self, config: dict) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        box = QGroupBox("查询顺序")
        box_layout = QVBoxLayout(box)
        hint = QLabel("勾选的网站按从上到下的顺序查询，番号或标题对不上就换下一个，不会拿另一部充数。")
        hint.setWordWrap(True)
        box_layout.addWidget(hint)

        row = QHBoxLayout()
        self.site_list = QListWidget()
        self.site_list.setObjectName("sites")
        for item in normalize_sites(config.get("sites")):
            label = SITE_LABELS.get(item["name"], item["name"])
            row_item = QListWidgetItem(label)
            row_item.setData(Qt.ItemDataRole.UserRole, item["name"])
            row_item.setFlags(row_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row_item.setCheckState(Qt.CheckState.Checked if item["enabled"] else Qt.CheckState.Unchecked)
            self.site_list.addItem(row_item)
        row.addWidget(self.site_list, 1)
        buttons = QVBoxLayout()
        up = QPushButton("上移")
        down = QPushButton("下移")
        up.clicked.connect(lambda: self._move_site(-1))
        down.clicked.connect(lambda: self._move_site(1))
        buttons.addWidget(up)
        buttons.addWidget(down)
        buttons.addStretch(1)
        row.addLayout(buttons)
        box_layout.addLayout(row)
        layout.addWidget(box, 1)

        keys = QGroupBox("密钥和代理")
        keys_layout = QVBoxLayout(keys)
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("TMDB API Key"))
        self.tmdb_key_edit = QLineEdit(str(config.get("tmdb_key") or ""))
        self.tmdb_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.tmdb_key_edit.setPlaceholderText("没有 Key 时 TMDB 会跳过")
        key_row.addWidget(self.tmdb_key_edit, 1)
        keys_layout.addLayout(key_row)
        proxy_row = QHBoxLayout()
        proxy_row.addWidget(QLabel("代理"))
        self.proxy_edit = QLineEdit(str(config.get("proxy") or ""))
        self.proxy_edit.setPlaceholderText("可选，http://127.0.0.1:7890")
        proxy_row.addWidget(self.proxy_edit, 1)
        keys_layout.addLayout(proxy_row)
        layout.addWidget(keys)
        return page

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
        return normalize_sites(sites)

    def _sync_mode(self) -> None:
        folder = self.folder_radio.isChecked()
        self.output_label.setEnabled(folder)
        self.output_edit.setEnabled(folder)
        self.output_btn.setEnabled(folder)

    def _browse_media(self) -> None:
        current = self.media_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择媒体目录", current)
        if chosen:
            self.media_edit.setText(chosen)

    def _browse_output(self) -> None:
        current = self.output_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择输出目录", current)
        if chosen:
            self.output_edit.setText(chosen)

    def _settings(self) -> dict:
        return {
            "media_dir": self.media_edit.text().strip(),
            "output_dir": self.output_edit.text().strip(),
            "output_mode": "folder" if self.folder_radio.isChecked() else "beside",
            "sites": self._sites(),
            "tmdb_key": self.tmdb_key_edit.text().strip(),
            "proxy": self.proxy_edit.text().strip(),
            "skip_existing_nfo": self.skip_nfo_box.isChecked(),
            "translate_plot": self.translate_box.isChecked(),
        }

    def _remember(self) -> None:
        try:
            save_config(self._settings())
        except OSError as exc:
            self._append(f"无法保存 config.json: {exc}")

    def _append(self, message: str) -> None:
        self.log.appendPlainText(message)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._append("已有任务正在运行，请先停止或等待结束")
            return
        settings = self._settings()
        if not settings["media_dir"]:
            self._append("请填写媒体目录")
            return
        if not Path(settings["media_dir"]).is_dir():
            self._append(f"媒体目录不存在: {settings['media_dir']}")
            return
        if settings["output_mode"] == "folder" and not settings["output_dir"]:
            self._append("移动模式请填写输出目录")
            return
        self._remember()
        self._stop.clear()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._append("开始刮削")

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

    def _stop_job(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            return
        self._stop.set()
        self._append("正在停止，将在当前文件结束后停下")

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

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop.set()
        self._remember()
        event.accept()


def launch(argv: list[str] | None = None) -> int:
    application = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    application.setStyle("Fusion")
    application.setFont(_pick_font())
    application.setStyleSheet(
        """
        QWidget { background: #F3F3F3; color: #1A1A1A; }
        QGroupBox {
            background: white;
            border: 1px solid #E0E0E0;
            border-radius: 4px;
            margin-top: 12px;
            padding: 10px 8px 8px 8px;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; background: white; }
        QLineEdit, QPlainTextEdit, QListWidget {
            background: white;
            border: 1px solid #D0D0D0;
            padding: 4px;
        }
        QPushButton { background: white; border: 1px solid #C8C8C8; padding: 6px 14px; }
        QPushButton#start { background: #0078D4; color: white; border: none; }
        QPushButton#stop { background: #E1E1E1; color: #333333; border: none; }
        QTabWidget::pane { border: none; background: #F3F3F3; }
        QTabBar::tab { background: #E8E8E8; padding: 8px 18px; }
        QTabBar::tab:selected { background: white; }
        """
    )
    window = MainWindow()
    window.show()
    return application.exec()
