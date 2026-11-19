import logging
from collections import deque
from queue import Empty, Queue

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from yyict_toolbox.plugins.builtin.campus_network_service import CampusNetworkMonitor
from yyict_toolbox.plugins.builtin.campus_settings import (
    CampusSettings,
    CampusSettingsStore,
    CredentialStorageError,
)


class CampusNetworkPage(QWidget):
    def __init__(
        self,
        settings_store: CampusSettingsStore,
        log_queue: Queue[logging.LogRecord],
        logger: logging.Logger,
    ) -> None:
        super().__init__()
        self._settings_store = settings_store
        self._log_queue = log_queue
        self._logger = logger
        self._monitor: CampusNetworkMonitor | None = None
        self._log_entries: deque[tuple[int, str]] = deque(maxlen=1000)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 26, 34, 24)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        title = QLabel("校园网自动登录")
        title.setStyleSheet("font-size: 21px; font-weight: 700; color: #17212b;")
        heading.addWidget(title)
        heading.addStretch(1)
        self._status_label = QLabel("未运行")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #667783; font-size: 13px;")
        heading.addWidget(self._status_label)
        layout.addLayout(heading)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self._account_input = QLineEdit()
        self._account_input.setPlaceholderText("输入校园网账号")
        self._password_input = QLineEdit()
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_input.setPlaceholderText("输入校园网密码")
        self._carrier_input = QComboBox()
        self._carrier_input.addItem("中国移动", "cmcc")
        self._carrier_input.addItem("中国联通", "unicom")
        self._carrier_input.addItem("中国电信", "telecom")
        self._interval_input = QSpinBox()
        self._interval_input.setRange(5, 3600)
        self._interval_input.setSuffix(" 秒")
        self._level_input = QComboBox()
        self._level_input.addItem("1  错误", 1)
        self._level_input.addItem("2  警告及错误", 2)
        self._level_input.addItem("3  全部", 3)
        self._level_input.setToolTip("仅过滤界面显示；文件保留所有探针与登录事件")
        form.addRow("账号", self._account_input)
        form.addRow("密码", self._password_input)
        form.addRow("运营商", self._carrier_input)
        form.addRow("探针间隔", self._interval_input)
        form.addRow("日志等级", self._level_input)
        layout.addLayout(form)

        actions = QHBoxLayout()
        self._save_button = QPushButton("保存配置")
        self._save_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self._start_button = QPushButton("启动监控")
        self._start_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self._stop_button = QPushButton("停止监控")
        self._stop_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self._stop_button.setEnabled(False)
        actions.addWidget(self._save_button)
        actions.addWidget(self._start_button)
        actions.addWidget(self._stop_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        log_heading = QHBoxLayout()
        log_heading.addWidget(QLabel("运行日志"))
        log_heading.addStretch(1)
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(1000)
        self._log_view.setPlaceholderText("探针与登录事件将显示在这里")
        layout.addLayout(log_heading)
        layout.addWidget(self._log_view, 1)

        self._save_button.clicked.connect(self._save_settings)
        self._start_button.clicked.connect(self._start_monitor)
        self._stop_button.clicked.connect(self._stop_monitor)
        self._level_input.currentIndexChanged.connect(self._refresh_log_view)
        self._queue_timer = QTimer(self)
        self._queue_timer.setInterval(250)
        self._queue_timer.timeout.connect(self._drain_log_queue)
        self._queue_timer.start()
        self._load_settings()

    def shutdown(self) -> bool:
        if self._monitor and self._monitor.isRunning():
            self._monitor.stop()
            self._status_label.setText("正在停止，请等待当前网络请求结束")
            return False
        self._queue_timer.stop()
        return True

    def wait_for_shutdown(self) -> None:
        if self._monitor:
            self._monitor.stop()
            self._monitor.wait()

    def _load_settings(self) -> None:
        try:
            settings, password = self._settings_store.load()
        except (CredentialStorageError, ValueError, TypeError) as error:
            self._logger.error("读取校园网配置失败（%s）", type(error).__name__)
            self._status_label.setText("配置无法读取，请重新填写")
            settings, password = CampusSettings(), ""
        self._account_input.setText(settings.account)
        self._password_input.setText(password)
        carrier_index = self._carrier_input.findData(settings.carrier)
        self._carrier_input.setCurrentIndex(max(carrier_index, 0))
        self._interval_input.setValue(settings.probe_interval)
        level_index = self._level_input.findData(settings.log_level)
        self._level_input.setCurrentIndex(max(level_index, 0))

    def _current_settings(self) -> CampusSettings:
        return CampusSettings(
            account=self._account_input.text().strip(),
            carrier=str(self._carrier_input.currentData()),
            probe_interval=self._interval_input.value(),
            log_level=int(self._level_input.currentData()),
        )

    def _save_settings(self) -> bool:
        settings = self._current_settings()
        try:
            self._settings_store.save(settings, self._password_input.text())
        except (CredentialStorageError, ValueError) as error:
            self._logger.error("保存校园网配置失败：%s", error)
            self._status_label.setText(str(error))
            return False
        self._status_label.setText("配置已保存")
        self._logger.info("校园网配置已保存")
        self._refresh_log_view()
        return True

    def _start_monitor(self) -> None:
        if self._monitor is not None:
            return
        settings = self._current_settings()
        password = self._password_input.text()
        if not settings.account or not password:
            self._status_label.setText("请填写账号和密码")
            return
        if not self._save_settings():
            return
        self._monitor = CampusNetworkMonitor(settings, password, self._logger)
        self._monitor.status_changed.connect(self._status_label.setText)
        self._monitor.finished.connect(self._monitor_finished)
        self._start_button.setEnabled(False)
        self._stop_button.setEnabled(True)
        self._set_configuration_enabled(False)
        self._monitor.start()

    def _stop_monitor(self) -> None:
        if self._monitor and self._monitor.isRunning():
            self._monitor.stop()
            self._status_label.setText("正在停止监控")
            self._stop_button.setEnabled(False)

    def _monitor_finished(self) -> None:
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._set_configuration_enabled(True)
        if self._monitor:
            self._monitor.deleteLater()
        self._monitor = None

    def _set_configuration_enabled(self, enabled: bool) -> None:
        for widget in (
            self._account_input, self._password_input, self._carrier_input,
            self._interval_input, self._save_button,
        ):
            widget.setEnabled(enabled)

    def _drain_log_queue(self) -> None:
        changed = False
        while True:
            try:
                record = self._log_queue.get_nowait()
            except Empty:
                break
            message = record.getMessage()
            timestamp = logging.Formatter("%(asctime)s").formatTime(record, "%H:%M:%S")
            self._log_entries.append((record.levelno, f"{timestamp} {record.levelname} {message}"))
            changed = True
        if changed:
            self._refresh_log_view()

    def _refresh_log_view(self) -> None:
        selected_level = int(self._level_input.currentData())
        minimum_level = {1: logging.ERROR, 2: logging.WARNING, 3: logging.DEBUG}[selected_level]
        self._log_view.setPlainText(
            "\n".join(message for level, message in self._log_entries if level >= minimum_level)
        )
        cursor = self._log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._log_view.setTextCursor(cursor)
