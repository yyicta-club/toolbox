import logging
import os
from collections.abc import Sequence

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDesktopServices,
    QIcon,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from yyict_toolbox import __version__
from yyict_toolbox.logging_system import SYSTEM_LOGGER_NAME, UPDATE_LOGGER_NAME
from yyict_toolbox.plugins.specs import ToolDescriptor
from yyict_toolbox.resources import image_path, logo_path
from yyict_toolbox.ui.update_worker import (
    UpdateCheckWorker,
    UpdateDownloadWorker,
    UpdateInstallWorker,
)
from yyict_toolbox.updates import (
    APPLY_LOG_NAME,
    INSTALL_CONFIRM_TIMEOUT,
    InstallHandshake,
    InstallPlan,
    UpdateCandidate,
    UpdateError,
    is_frozen_install,
    is_portable_install,
    launch_update_install,
    release_page_url,
    updates_root,
)


class MainWindow(QMainWindow):
    exit_requested = Signal()

    def __init__(self, tools: Sequence[ToolDescriptor]) -> None:
        super().__init__()
        self._tools = list(tools)
        self._tool_buttons: dict[str, QPushButton] = {}
        self._pages: dict[str, QWidget] = {}
        self._exit_requested = False
        self._logger = logging.getLogger(SYSTEM_LOGGER_NAME)
        self._update_logger = logging.getLogger(UPDATE_LOGGER_NAME)
        self._update_worker: UpdateCheckWorker | None = None
        self._download_worker: UpdateDownloadWorker | None = None
        self._install_worker: UpdateInstallWorker | None = None
        self._progress_dialog: QProgressDialog | None = None
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(100)
        self._shutdown_timer.timeout.connect(self._complete_exit)
        self._tip_label: QLabel | None = None
        self._tip_timer = QTimer(self)
        self._tip_timer.setSingleShot(True)
        self._tip_timer.timeout.connect(self._hide_text_tip)
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
        download = self._download_worker
        if download is not None:
            download.cancel()
            download.wait(5000)
            self._download_worker = None
        check = self._update_worker
        if check is not None:
            check.wait(2000)
            self._update_worker = None
        install = self._install_worker
        if install is not None:
            # 启动确认线程按超时自行结束，等待它自然完成而不是强杀。
            install.wait(int(INSTALL_CONFIRM_TIMEOUT * 1000) + 2000)
        stopped = True
        for page in self._pages.values():
            shutdown = getattr(page, "shutdown", None)
            if shutdown:
                stopped = shutdown() and stopped
        return stopped

    def wait_for_shutdown(self) -> None:
        install = self._install_worker
        if install is not None:
            install.wait(int(INSTALL_CONFIRM_TIMEOUT * 1000) + 2000)
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
        background_association = QPushButton("信息通信技术协会")
        background_association.setStyleSheet("QPushButton { border: none; border-radius: 8px; }")
        background_association.clicked.connect(
            lambda: self._show_text_tip("欢迎扫描下方二维码进群", 3000)
        )
        layout.addWidget(background_association)

        self._image_pixmap = QPixmap(str(image_path("xiehuiqq.png")))
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
        self._update_button = QPushButton(
            f"YYICT TOOLBOX  ·  v{__version__}",
            objectName="versionButton",
        )
        self._update_button.setToolTip("点击检查更新")
        self._update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_button.setStyleSheet(
            "QPushButton#versionButton { border: none; background: transparent;"
            " color: #667783; font-size: 11px; font-weight: 600; text-align: left;"
            " min-height: 0; padding: 4px 0; }"
            "QPushButton#versionButton:hover { color: #12615e; }"
            "QPushButton#versionButton:disabled { color: #9aa7b0; }"
        )
        self._update_button.clicked.connect(self._check_updates)
        layout.addWidget(self._update_button)
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

    def _show_text_tip(self, text: str, duration_ms: int = 2000) -> QLabel:
        """在主窗口底部弹出文本提示并返回提示标签。

        duration_ms 为提示存活时间（毫秒），<=0 表示常驻直到下次调用或窗口关闭；
        重复调用复用同一标签并重置生命周期。
        """
        if self._tip_label is None:
            tip = QLabel(self)
            tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tip.setWordWrap(True)
            tip.setMaximumWidth(420)
            tip.setStyleSheet(
                "QLabel { background: #17212b; color: #ffffff; border-radius: 6px;"
                " padding: 8px 14px; font-size: 13px; }"
            )
            self._tip_label = tip
        tip = self._tip_label
        tip.setText(text)
        tip.adjustSize()
        self._place_text_tip()
        tip.show()
        tip.raise_()
        self._tip_timer.stop()
        if duration_ms > 0:
            self._tip_timer.start(duration_ms)
        return tip

    def _hide_text_tip(self) -> None:
        if self._tip_label is not None:
            self._tip_label.hide()

    def _place_text_tip(self) -> None:
        tip = self._tip_label
        if tip is None:
            return
        tip.move(
            (self.width() - tip.width()) // 2,
            self.height() - tip.height() - 24,
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_text_tip()

    def _show_enlarged_image(self) -> None:
        if self._image_pixmap.isNull():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("查看图片")
        screen = dialog.screen().availableGeometry()
        max_w, max_h = screen.width() * 3 // 4, screen.height() * 3 // 4
        self._image_pixmap = QPixmap(str(image_path("qq.jpg")))
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
        self._image_pixmap = QPixmap(str(image_path("xiehuiqq.png")))

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
        self._logger.info("切换到工具：%s", tool.name)

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

    def report_update_result(self, result: tuple[str, str] | None) -> None:
        """启动后展示上次自动更新的结果。"""
        if result is None:
            return
        status, version = result
        if status == "applied":
            self._show_text_tip(f"已更新到 {version}", 4000)
            return
        QMessageBox.warning(self, "更新未完成", "自动更新失败，已恢复原版本。详情见日志。")

    def _check_updates(self) -> None:
        if (
            self._update_worker is not None
            or self._download_worker is not None
            or self._install_worker is not None
        ):
            return
        if not is_frozen_install():
            self._update_logger.info("更新检查跳过：源码模式不支持自动更新")
            self._show_text_tip("源码模式不执行自动更新，请使用打包版本", 3000)
            return
        self._update_button.setEnabled(False)
        self._update_button.setText(f"YYICT TOOLBOX  ·  v{__version__}  检查中…")
        worker = UpdateCheckWorker()
        worker.resolved.connect(self._on_update_resolved)
        worker.failed.connect(self._on_update_check_failed)
        worker.finished.connect(self._on_update_check_finished)
        self._update_worker = worker
        worker.start()

    def _on_update_check_finished(self) -> None:
        self._update_worker = None
        self._update_button.setEnabled(True)
        self._update_button.setText(f"YYICT TOOLBOX  ·  v{__version__}")

    def _on_update_check_failed(self, message: str) -> None:
        self._show_text_tip(message, 6000)

    def _on_update_resolved(self, candidate: object) -> None:
        if not isinstance(candidate, UpdateCandidate):
            self._show_text_tip("已是最新版本", 3000)
            return
        manifest = candidate.manifest
        notes = manifest.notes.strip() or "本次更新没有提供说明。"
        if len(notes) > 800:
            notes = notes[:800] + "…"
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Information)
        if candidate.is_required(__version__):
            dialog.setWindowTitle("需要更新")
            dialog.setText(f"当前版本 v{__version__} 已不再受支持，请更新到 {manifest.version}")
        else:
            dialog.setWindowTitle("发现新版本")
            dialog.setText(f"发现新版本 {manifest.version}（当前 v{__version__}）")
        dialog.setInformativeText(notes)
        update_button = dialog.addButton("立即更新", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton("稍后", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is not update_button:
            return
        if is_portable_install():
            self._offer_manual_update(candidate)
            return
        self._start_download(candidate)

    def _offer_manual_update(self, candidate: UpdateCandidate) -> None:
        self._update_logger.info(
            "便携版更新：仅提供手动下载，版本 %s", candidate.manifest.version
        )
        dialog = QMessageBox(self)
        dialog.setWindowTitle("便携版更新")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText(f"发现新版本 {candidate.manifest.version}")
        dialog.setInformativeText("便携版是单个 exe，请下载新版本后替换当前文件。")
        open_button = dialog.addButton("打开下载页", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton("稍后", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is not open_button:
            return
        if not QDesktopServices.openUrl(QUrl(release_page_url())):
            self._show_text_tip(f"无法打开浏览器，请手动访问 {release_page_url()}", 6000)

    def _start_download(self, candidate: UpdateCandidate) -> None:
        dialog = QProgressDialog("正在下载更新…", "取消", 0, 100, self)
        dialog.setWindowTitle("软件更新")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        worker = UpdateDownloadWorker(candidate, updates_root())
        worker.progress.connect(self._on_download_progress)
        worker.prepared.connect(self._on_update_prepared)
        worker.failed.connect(self._on_update_failed)
        worker.cancelled.connect(self._on_update_cancelled)
        worker.finished.connect(self._on_download_finished)
        dialog.canceled.connect(worker.cancel)
        self._download_worker = worker
        self._progress_dialog = dialog
        worker.start()
        dialog.show()

    def _on_download_progress(self, received: int, total: int) -> None:
        dialog = self._progress_dialog
        if dialog is None:
            return
        total = max(total, 1)
        dialog.setValue(min(100, received * 100 // total))
        dialog.setLabelText(
            f"正在下载更新… {received / (1024 * 1024):.1f} / {total / (1024 * 1024):.1f} MB"
        )

    def _on_update_prepared(self, plan: object) -> None:
        self._close_progress_dialog()
        if not isinstance(plan, InstallPlan):
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("安装更新")
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText(f"更新 {plan.version} 已下载完成，是否立即退出并安装？")
        dialog.setInformativeText("程序会短暂退出，安装完成后自动重新启动。")
        install_button = dialog.addButton("立即安装", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton("稍后", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is not install_button:
            self._show_text_tip("已下载更新，稍后可再次检查更新安装", 4000)
            return
        self._start_install(plan)

    def _start_install(self, plan: InstallPlan) -> None:
        """启动更新脚本并等待启动确认；只有确认后主程序才退出。"""
        try:
            launch = launch_update_install(plan, os.getpid())
        except UpdateError as error:
            QMessageBox.critical(self, "无法安装更新", str(error))
            return
        worker = UpdateInstallWorker(
            InstallHandshake(launch.marker, launch.process),
            launch.log,
            parent=self,
        )
        worker.confirmed.connect(self._on_install_confirmed)
        worker.failed.connect(self._on_install_failed)
        worker.finished.connect(self._on_install_worker_finished)
        self._install_worker = worker
        self._show_text_tip("正在启动更新脚本，请留意弹出的 PowerShell 窗口", 5000)
        worker.start()

    def _on_install_confirmed(self) -> None:
        """收到本次启动标记，说明脚本已经开始执行，可以退出主程序。"""
        self._update_logger.info("更新脚本已确认开始执行，准备退出主程序")
        self._exit_application()

    def _on_install_failed(self, reason: str) -> None:
        """启动未确认：保留当前版本继续运行，并说明失败原因。"""
        self._update_logger.error("更新脚本未确认开始执行：%s", reason)
        QMessageBox.critical(
            self,
            "无法安装更新",
            f"{reason}\n当前版本将继续运行，详情见更新目录中的 {APPLY_LOG_NAME}。",
        )

    def _on_install_worker_finished(self) -> None:
        worker = self._install_worker
        self._install_worker = None
        if worker is not None:
            worker.deleteLater()

    def _on_update_failed(self, message: str) -> None:
        self._close_progress_dialog()
        QMessageBox.critical(self, "更新失败", message)

    def _on_update_cancelled(self) -> None:
        self._close_progress_dialog()
        self._show_text_tip("已取消更新", 3000)

    def _on_download_finished(self) -> None:
        worker = self._download_worker
        self._download_worker = None
        if worker is not None:
            worker.deleteLater()

    def _close_progress_dialog(self) -> None:
        dialog = self._progress_dialog
        self._progress_dialog = None
        if dialog is None:
            return
        dialog.close()
        dialog.deleteLater()

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
