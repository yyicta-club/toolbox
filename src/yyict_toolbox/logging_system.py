import logging
import logging.handlers
from pathlib import Path
from queue import Empty, Full, Queue


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


def configure_logging(application_directory: Path) -> Queue[logging.LogRecord]:
    log_directory = application_directory / "log"
    log_directory.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("yyict_toolbox")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.handlers.RotatingFileHandler(
        log_directory / "toolbox.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    log_queue: Queue[logging.LogRecord] = Queue(maxsize=1000)
    queue_handler = DisplayQueueHandler(log_queue)
    queue_handler.setLevel(logging.DEBUG)
    logger.addHandler(queue_handler)
    return log_queue
