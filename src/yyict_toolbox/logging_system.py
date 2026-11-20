"""统一日志：文件日志、兼容记录队列与实时事件中心。

日志来源用 logger 名称区分：

* 系统日志：``yyict_toolbox.system``
* 版本更新日志：``yyict_toolbox.update``
* 插件日志：``yyict_toolbox.plugin.<稳定插件 ID>``

事件中心把同一条日志同时分发给所有订阅页面，因此统一日志页面与校园网页面
能看到完全相同的事件流。没有明确来源的历史记录按系统日志解析。
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Empty, Full, Queue

SYSTEM_LOGGER_NAME = "yyict_toolbox.system"
UPDATE_LOGGER_NAME = "yyict_toolbox.update"
PLUGIN_LOGGER_PREFIX = "yyict_toolbox.plugin."
ROOT_LOGGER_NAME = "yyict_toolbox"
SYSTEM_SOURCE_ID = "system"

LOG_DIRECTORY_NAME = "log"
LOG_FILE_NAME = "toolbox.log"
LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_DISPLAY_EVENTS = 1000
MAX_HISTORY_EVENTS = 2000
SUBSCRIBER_QUEUE_SIZE = 1000
ROTATED_BACKUP_COUNT = 3


def plugin_logger_name(tool_id: str) -> str:
    """返回某个插件工具对应的 logger 名称。"""
    return f"{PLUGIN_LOGGER_PREFIX}{tool_id}"


def source_id_for_logger(logger_name: str) -> str:
    """把 logger 名称映射为日志来源 ID：插件取工具 ID，其余归系统日志。"""
    if logger_name.startswith(PLUGIN_LOGGER_PREFIX):
        plugin_id = logger_name[len(PLUGIN_LOGGER_PREFIX):]
        if plugin_id:
            return plugin_id
    return SYSTEM_SOURCE_ID


@dataclass(frozen=True, slots=True)
class LogEvent:
    """统一的日志事件；只包含时间、等级、来源和消息，不携带凭据等敏感信息。"""

    timestamp: datetime
    level: int
    logger_name: str
    message: str

    @classmethod
    def from_record(cls, record: logging.LogRecord) -> "LogEvent":
        """把标准库日志记录转换为统一事件。"""
        return cls(
            timestamp=datetime.fromtimestamp(record.created),
            level=record.levelno,
            logger_name=record.name,
            message=record.getMessage(),
        )

    @property
    def source_id(self) -> str:
        """事件来源 ID：插件工具 ID 或 ``system``。"""
        return source_id_for_logger(self.logger_name)

    @property
    def level_name(self) -> str:
        return logging.getLevelName(self.level)


class LogEventHub:
    """统一日志事件中心：缓存最近事件，并向所有订阅者实时分发。

    订阅队列有界，队列满时丢弃最旧事件，保证页面总能收到最新日志。
    """

    def __init__(
        self,
        max_events: int = MAX_HISTORY_EVENTS,
        log_file: Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._events: deque[LogEvent] = deque(maxlen=max_events)
        self._subscribers: list[Queue[LogEvent]] = []
        self._log_file = log_file

    @property
    def log_file(self) -> Path | None:
        """当前写入的日志文件路径；未配置时为 None。"""
        return self._log_file

    def set_log_file(self, path: Path) -> None:
        with self._lock:
            self._log_file = path

    def publish(self, event: LogEvent) -> None:
        """记录事件并分发给所有订阅者。"""
        with self._lock:
            self._events.append(event)
            for queue in list(self._subscribers):
                _put_latest(queue, event)

    def subscribe(self) -> Queue[LogEvent]:
        """订阅事件流，返回一个有界队列。"""
        queue: Queue[LogEvent] = Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        with self._lock:
            self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: Queue[LogEvent]) -> None:
        """取消订阅，页面关闭时必须调用。"""
        with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    def history(self) -> list[LogEvent]:
        """返回本次运行中已记录的事件副本。"""
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        """清空内存中的事件缓存，不影响已写入的日志文件。"""
        with self._lock:
            self._events.clear()

    def read_history(self, limit: int = MAX_HISTORY_EVENTS) -> list[LogEvent]:
        """读取持久化日志（含轮转备份）中的历史事件。"""
        path = self._log_file
        if path is None:
            return []
        return read_log_events(path, limit)


_EVENT_HUB = LogEventHub()


def event_hub() -> LogEventHub:
    """返回进程内统一的日志事件中心。"""
    return _EVENT_HUB


def _put_latest(queue: Queue[LogEvent], event: LogEvent) -> None:
    """队列已满时丢弃最旧事件，保证订阅者收到最新日志。"""
    try:
        queue.put_nowait(event)
    except Full:
        try:
            queue.get_nowait()
        except Empty:
            pass
        try:
            queue.put_nowait(event)
        except Full:
            pass


class DisplayQueueHandler(logging.handlers.QueueHandler):
    def enqueue(self, record: logging.LogRecord) -> None:
        # 文件日志不丢弃；界面只保留最近事件，避免后台常驻时内存持续增长。
        try:
            self.queue.put_nowait(record)
        except Full:
            try:
                self.queue.get_nowait()
            except Empty:
                pass
            try:
                self.queue.put_nowait(record)
            except Full:
                pass


class EventHubHandler(logging.Handler):
    """把日志记录转发给统一事件中心。"""

    def __init__(self, hub: LogEventHub) -> None:
        super().__init__()
        self._hub = hub

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._hub.publish(LogEvent.from_record(record))
        except Exception:  # noqa: BLE001 -- 日志失败不能影响业务流程
            self.handleError(record)


_CURRENT_LINE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) "
    r"(?P<level>[A-Z]+) \[(?P<logger>[^\[\]\s]+)\] (?P<message>.*)$"
)
_LEGACY_LINE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) "
    r"(?P<level>[A-Z]+) (?P<message>.*)$"
)


def _parse_log_line(line: str) -> LogEvent | None:
    """解析一行日志；旧格式（无 logger 名称）按系统日志兼容解析。"""
    match = _CURRENT_LINE.match(line)
    logger_name = ""
    if match is not None and "." in match.group("logger"):
        logger_name = match.group("logger")
    else:
        match = _LEGACY_LINE.match(line)
        if match is None:
            return None
        logger_name = SYSTEM_LOGGER_NAME
    level = logging.getLevelName(match.group("level"))
    if not isinstance(level, int):
        level = logging.INFO
    try:
        timestamp = datetime.strptime(match.group("time"), LOG_TIME_FORMAT)
    except ValueError:
        return None
    return LogEvent(
        timestamp=timestamp,
        level=level,
        logger_name=logger_name,
        message=match.group("message"),
    )


def _rotated_log_files(log_file: Path) -> list[Path]:
    """按时间从旧到新返回轮转备份与当前日志文件。"""
    backups: list[Path] = []
    for index in range(1, ROTATED_BACKUP_COUNT + 1):
        candidate = log_file.with_name(f"{log_file.name}.{index}")
        if not candidate.is_file():
            break
        backups.append(candidate)
    files = list(reversed(backups))
    if log_file.is_file():
        files.append(log_file)
    return files


def _parse_log_file(path: Path) -> list[LogEvent]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    events: list[LogEvent] = []
    for line in content.splitlines():
        event = _parse_log_line(line)
        if event is not None:
            events.append(event)
    return events


def read_log_events(log_file: Path, limit: int = MAX_HISTORY_EVENTS) -> list[LogEvent]:
    """读取当前日志与轮转备份，返回按时间排序的最近事件。"""
    events: list[LogEvent] = []
    for path in _rotated_log_files(log_file):
        events.extend(_parse_log_file(path))
    events.sort(key=lambda event: event.timestamp)
    if limit > 0 and len(events) > limit:
        events = events[-limit:]
    return events


def configure_logging(application_directory: Path) -> Queue[logging.LogRecord]:
    """配置文件日志、兼容记录队列与统一事件中心，返回原始记录队列。

    返回的 ``Queue[LogRecord]`` 供仍按原始记录消费的组件注入使用；
    新的日志页面统一订阅事件中心。
    """
    log_directory = application_directory / LOG_DIRECTORY_NAME
    log_directory.mkdir(parents=True, exist_ok=True)
    log_file = log_directory / LOG_FILE_NAME

    logger = logging.getLogger(ROOT_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt=LOG_TIME_FORMAT,
    )
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=ROTATED_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    log_queue: Queue[logging.LogRecord] = Queue(maxsize=MAX_DISPLAY_EVENTS)
    queue_handler = DisplayQueueHandler(log_queue)
    queue_handler.setLevel(logging.DEBUG)
    logger.addHandler(queue_handler)

    hub = event_hub()
    hub.set_log_file(log_file)
    hub_handler = EventHubHandler(hub)
    hub_handler.setLevel(logging.DEBUG)
    logger.addHandler(hub_handler)
    return log_queue
