from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from yyict_toolbox.plugins.specs import ToolDescriptor
from yyict_toolbox.resources import logo_path


class MainWindow(QMainWindow):
    exit_requested = Signal()

    def __init__(self, tools: Sequence[ToolDescriptor]) -> None:
        super().__init__()
        self._tools = list(tools)
        self._tool_buttons: dict[str, QPushButton] = {}
        self._pages: dict[str, QWidget] = {}
        self._exit_requested = False
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(100)
        self._shutdown_timer.timeout.connect(self._complete_exit)
        self.setWindowTitle("校园工具箱")
        self.setWindowIcon(QIcon(str(logo_path())))
        self.setMinimumSize(780, 620)
        self.resize(980, 760)
        self.setStyleSheet(
            """
            QMainWindow, QWidget#root { background: #f5f7f8; color: #17212b; }
            QWidget#sidebar { background: #ffffff; border-right: 1px solid #e2e8ec; }
            QLabel#brand { color: #173b4d; font-size: 17px; font-weight: 700; }
            QLabel#eyebrow { color: #60717d; font-size: 11px; font-weight: 700; }
            QLabel#muted { color: #667783; font-size: 13px; }
            QPushButton#toolButton { text-align: left; padding: 10px 12px; border: 0;
                                     border-radius: 5px; color: #40515d; font-size: 13px; }
            QPushButton#toolButton:hover { background: #f0f5f7; }
            QPushButton#toolButton:checked { background: #e6f2f2; color: #12615e;
                                             font-weight: 600; }
            QFrame#separator { background: #e2e8ec; border: 0; max-height: 1px; }
            QLineEdit, QComboBox, QSpinBox { min-height: 30px; padding: 2px 8px;
                                             border: 1px solid #d6dfe4; border-radius: 4px;
                                             background: #ffffff; }
            QPushButton { min-height: 32px; padding: 2px 12px; }
            QPlainTextEdit { background: #ffffff; border: 1px solid #e2e8ec;
                             border-radius: 4px; color: #263640; }
            """
        )

        root = QWidget(objectName="root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())
        layout.addWidget(self._build_content(), 1)
        self.setCentralWidget(root)
        self._setup_tray_icon()

        if self._tools:
            self._select_tool(self._tools[0].id)

    @property
    def tray_available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def shutdown(self) -> bool:
        stopped = True
        for page in self._pages.values():
            shutdown = getattr(page, "shutdown", None)
            if shutdown:
                stopped = shutdown() and stopped
        return stopped

    def wait_for_shutdown(self) -> None:
        for page in self._pages.values():
            wait = getattr(page, "wait_for_shutdown", None)
            if wait:
                wait()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.tray_available and not self._exit_requested:
            self.hide()
            event.ignore()
            return
        event.ignore()
        self._exit_application()

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget(objectName="sidebar")
        sidebar.setFixedWidth(228)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 20, 14, 16)
        layout.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        logo_label = QLabel(objectName="brandLogo")
        logo_pixmap = QPixmap(str(logo_path()))
        logo_label.setPixmap(
            logo_pixmap.scaled(
                36,
                36,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        brand_row.addWidget(logo_label)
        brand_row.addWidget(QLabel("校园工具箱", objectName="brand"))
        brand_row.addStretch(1)
        layout.addLayout(brand_row)
        layout.addSpacing(22)
        layout.addWidget(QLabel("工具", objectName="eyebrow"))
        layout.addSpacing(5)

        for tool in self._tools:
            button = QPushButton(tool.name, objectName="toolButton")
            button.setCheckable(True)
            button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon))
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda checked=False, tool_id=tool.id: self._select_tool(tool_id))
            layout.addWidget(button)
            self._tool_buttons[tool.id] = button

        layout.addStretch(1)
        self._image_pixmap = QPixmap(
            str(Path(__file__).resolve().parent.parent / "resources" / "images" / "xiehuiqq.png")
        )
        join_button = QPushButton()
        if not self._image_pixmap.isNull():
            join_button.setIcon(QIcon(self._image_pixmap))
            join_button.setIconSize(QSize(200, 200))
        join_button.setFixedSize(200, 200)
        join_button.setToolTip("点击查看大图")
        join_button.setStyleSheet(
            "QPushButton { border: none; border-radius: 8px; }"
            "QPushButton:hover { background: #f0f5f7; }"
        )
        join_button.clicked.connect(self._show_enlarged_image)
        layout.addWidget(join_button)
        background_button = QPushButton("后台运行")
        background_button.setEnabled(self.tray_available)
        background_button.setToolTip("隐藏到系统托盘继续运行；从托盘菜单退出")
        background_button.clicked.connect(self.hide)
        layout.addWidget(background_button)
        exit_button = QPushButton("退出工具箱")
        exit_button.clicked.connect(self._exit_application)
        layout.addWidget(exit_button)
        layout.addWidget(QLabel("YYICT TOOLBOX  ·  0.1.0", objectName="muted"))
        return sidebar

    def _build_content(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._page_layout = QVBoxLayout()
        self._page_layout.setContentsMargins(0, 0, 0, 0)
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(34, 22, 34, 18)
        header_layout.addWidget(QLabel("工具箱  /  功能", objectName="muted"))
        layout.addWidget(header)
        separator = QFrame(objectName="separator")
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)
        page_host = QWidget()
        page_host.setLayout(self._page_layout)
        layout.addWidget(page_host, 1)
        return content

    def _setup_tray_icon(self) -> None:
        icon = QIcon(str(logo_path()))
        self._tray_icon = QSystemTrayIcon(icon, self)
        self._tray_icon.setToolTip("校园工具箱")
        menu = QMenu(self)
        show_action = QAction("打开主界面", self)
        exit_action = QAction("退出", self)
        show_action.triggered.connect(self._show_window)
        exit_action.triggered.connect(self._exit_application)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        self._tray_icon.setContextMenu(menu)
        self._tray_icon.activated.connect(self._tray_activated)
        if self.tray_available:
            self._tray_icon.show()

    def _show_enlarged_image(self) -> None:
        if self._image_pixmap.isNull():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("查看图片")
        screen = dialog.screen().availableGeometry()
        max_w, max_h = screen.width() * 3 // 4, screen.height() * 3 // 4
        scaled = self._image_pixmap.scaled(
            max_w, max_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        label = QLabel()
        label.setPixmap(scaled)
        label.setScaledContents(False)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        dialog.adjustSize()
        dialog.exec()

    def _select_tool(self, tool_id: str) -> None:
        tool = next((item for item in self._tools if item.id == tool_id), None)
        if tool is None:
            return
        for current_id, button in self._tool_buttons.items():
            button.setChecked(current_id == tool_id)

        current = self._page_layout.itemAt(0)
        if current:
            old_page = current.widget()
            self._page_layout.removeWidget(old_page)
            old_page.hide()

        page = self._pages.get(tool_id)
        if page is None:
            page = tool.view_factory() if tool.view_factory else QLabel("该工具尚未实现")
            self._pages[tool_id] = page
        self._page_layout.addWidget(page)
        page.show()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_window()

    def _show_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _exit_application(self) -> None:
        self._exit_requested = True
        self.centralWidget().setEnabled(False)
        self._shutdown_timer.start()
        self._complete_exit()

    def _complete_exit(self) -> None:
        if self.shutdown():
            self._shutdown_timer.stop()
            self._tray_icon.hide()
            self.hide()
            self.exit_requested.emit()
