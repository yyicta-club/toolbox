"""统一日志页面：合并持久化历史与实时日志流，并按来源和等级筛选。"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Sequence
from queue import Empty, Queue

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QShowEvent, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from yyict_toolbox.logging_system import (
    MAX_DISPLAY_EVENTS,
    SYSTEM_SOURCE_ID,
    UPDATE_LOGGER_NAME,
    LogEvent,
    LogEventHub,
)
from yyict_toolbox.plugins.builtin.system_logs import SYSTEM_LOGS_TOOL_ID
from yyict_toolbox.plugins.specs import ToolDescriptor

ALL_SOURCES = "全部来源"
ALL_LEVELS = "全部等级"
SYSTEM_SOURCE_LABEL = "系统日志"
UPDATE_SOURCE_LABEL = "版本更新"
POLL_INTERVAL_MS = 250


class SystemLogsPage(QWidget):
    """统一日志页面。

    页面合并持久化历史与实时事件流：刷新或重新打开页面时重新读取持久化历史，
    “清空当前显示”只清除页面内容，不删除日志文件。页面最多保留最近 1000 条记录。
    """

    def __init__(
        self,
        events: LogEventHub,
        tools_provider: Callable[[], Sequence[ToolDescriptor]],
    ) -> None:
        super().__init__()
        self._events = events
        self._tools_provider = tools_provider
        self._entries: deque[LogEvent] = deque(maxlen=MAX_DISPLAY_EVENTS)
        self._subscription: Queue[LogEvent] | None = None
        self._source_labels = self._build_source_labels()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 26, 34, 24)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        title = QLabel("运行日志")
        title.setStyleSheet("font-size: 21px; font-weight: 700; color: #17212b;")
        heading.addWidget(title)
        heading.addStretch(1)
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #667783; font-size: 13px;")
        heading.addWidget(self._status_label)
        layout.addLayout(heading)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("来源"))
        self._source_input = QComboBox()
        self._source_input.addItem(ALL_SOURCES, None)
        self._source_input.addItem(SYSTEM_SOURCE_LABEL, SYSTEM_SOURCE_ID)
        for tool in self._tools_provider():
            if tool.id == SYSTEM_LOGS_TOOL_ID:
                continue
            self._source_input.addItem(tool.name, tool.id)
        filters.addWidget(self._source_input)

        filters.addWidget(QLabel("等级"))
        self._level_input = QComboBox()
        self._level_input.addItem(ALL_LEVELS, 0)
        self._level_input.addItem("调试", logging.DEBUG)
        self._level_input.addItem("信息", logging.INFO)
        self._level_input.addItem("警告", logging.WARNING)
        self._level_input.addItem("错误", logging.ERROR)
        filters.addWidget(self._level_input)

        self._refresh_button = QPushButton("刷新")
        self._refresh_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self._clear_button = QPushButton("清空当前显示")
        self._clear_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton)
        )
        self._open_button = QPushButton("打开日志文件")
        filters.addWidget(self._refresh_button)
        filters.addWidget(self._clear_button)
        filters.addWidget(self._open_button)
        filters.addStretch(1)
        layout.addLayout(filters)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(MAX_DISPLAY_EVENTS)
        self._view.setPlaceholderText("系统、插件与版本更新日志将显示在这里")
        layout.addWidget(self._view, 1)

        self._source_input.currentIndexChanged.connect(self._refresh_view)
        self._level_input.currentIndexChanged.connect(self._refresh_view)
        self._refresh_button.clicked.connect(self.reload_history)
        self._clear_button.clicked.connect(self.clear_display)
        self._open_button.clicked.connect(self.open_log_file)

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.drain_events)

        self._start_subscription()
        self.reload_history()

    def _build_source_labels(self) -> dict[str, str]:
        """把稳定的插件 ID 映射为展示名称；未知插件显示其稳定 ID。"""
        labels = {SYSTEM_SOURCE_ID: SYSTEM_SOURCE_LABEL}
        for tool in self._tools_provider():
            if tool.id == SYSTEM_LOGS_TOOL_ID:
                continue
            labels[tool.id] = tool.name
        return labels

    def _start_subscription(self) -> None:
        if self._subscription is None:
            self._subscription = self._events.subscribe()
            self._timer.start()

    def _stop_subscription(self) -> None:
        self._timer.stop()
        if self._subscription is not None:
            self._events.unsubscribe(self._subscription)
            self._subscription = None

    def _source_label(self, event: LogEvent) -> str:
        if event.logger_name == UPDATE_LOGGER_NAME:
            return UPDATE_SOURCE_LABEL
        return self._source_labels.get(event.source_id, event.source_id)

    def _format_event(self, event: LogEvent) -> str:
        return (
            f"{event.timestamp.strftime('%H:%M:%S')} {event.level_name:<7} "
            f"[{self._source_label(event)}] {event.message}"
        )

    def _matches(self, event: LogEvent) -> bool:
        source = self._source_input.currentData()
        if source is not None and event.source_id != source:
            return False
        minimum = int(self._level_input.currentData() or 0)
        return not minimum or event.level >= minimum

    def drain_events(self) -> None:
        """取出订阅队列中的新事件并追加到页面底部。"""
        subscription = self._subscription
        if subscription is None:
            return
        new_events: list[LogEvent] = []
        while True:
            try:
                event = subscription.get_nowait()
            except Empty:
                break
            new_events.append(event)
        if not new_events:
            return
        self._entries.extend(new_events)
        for event in new_events:
            if self._matches(event):
                self._view.appendPlainText(self._format_event(event))

    def reload_history(self) -> None:
        """重新读取持久化历史，并保留尚未写入文件的实时事件。"""
        self.drain_events()
        history = self._events.read_history()
        known = set(history)
        merged = list(history)
        merged.extend(event for event in self._entries if event not in known)
        merged.sort(key=lambda event: event.timestamp)
        self._entries.clear()
        self._entries.extend(merged)
        self._refresh_view()

    def clear_display(self) -> None:
        """只清空页面当前显示，持久化日志保持不变。"""
        self._entries.clear()
        self._view.clear()

    def open_log_file(self) -> None:
        """用系统默认程序打开日志文件。"""
        path = self._events.log_file
        if path is None or not path.is_file():
            self._status_label.setText("日志文件尚未生成")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self._status_label.setText("无法打开日志文件，请手动查看日志目录")

    def _refresh_view(self) -> None:
        self._view.setPlainText(
            "\n".join(
                self._format_event(event) for event in self._entries if self._matches(event)
            )
        )
        cursor = self._view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._view.setTextCursor(cursor)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.reload_history()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop_subscription()
        super().closeEvent(event)

    def shutdown(self) -> bool:
        """取消日志订阅；页面没有其他后台任务。"""
        self._stop_subscription()
        return True

    def wait_for_shutdown(self) -> None:
        """页面没有需要等待的后台任务。"""
