"""更新检查与下载的后台线程：网络请求和磁盘操作都不在界面线程执行。"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from yyict_toolbox.logging_system import UPDATE_LOGGER_NAME
from yyict_toolbox.updates import (
    InstallHandshake,
    UpdateCandidate,
    UpdateCancelled,
    UpdateError,
    append_update_log,
    prepare_update,
    resolve_update,
)

logger = logging.getLogger(UPDATE_LOGGER_NAME)


class UpdateCheckWorker(QThread):
    """查询发布源；``resolved`` 携带 ``UpdateCandidate`` 或 ``None``。"""

    resolved = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        logger.info("更新检查开始")
        try:
            candidate = resolve_update()
        except UpdateError as error:
            # 只记录错误类型，避免把发布源地址写进日志。
            logger.error("更新检查失败（%s）", type(error).__name__)
            self.failed.emit(str(error))
            return
        except Exception as error:  # 线程边界：未预期错误也要回到界面提示
            logger.error("更新检查失败（%s）", type(error).__name__)
            self.failed.emit(f"检查更新失败：{error}")
            return
        if candidate is None:
            logger.info("更新检查完成：无可用更新")
        else:
            logger.info("更新检查完成：发现新版本 %s", candidate.manifest.version)
        self.resolved.emit(candidate)


class UpdateDownloadWorker(QThread):
    """下载并解压安装包，支持用户取消。"""

    progress = Signal(int, int)
    prepared = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        candidate: UpdateCandidate,
        root: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._candidate = candidate
        self._root = root
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _report_progress(self, received: int, total: int) -> None:
        if self._cancelled:
            raise UpdateCancelled
        self.progress.emit(received, total)

    def run(self) -> None:
        version = self._candidate.manifest.version
        logger.info("更新下载开始：版本 %s", version)
        try:
            plan = prepare_update(
                self._candidate,
                self._root,
                progress=self._report_progress,
            )
        except UpdateCancelled:
            logger.info("更新下载已取消：版本 %s", version)
            self.cancelled.emit()
            return
        except UpdateError as error:
            logger.error("更新下载失败：版本 %s（%s）", version, type(error).__name__)
            self.failed.emit(str(error))
            return
        except Exception as error:  # 线程边界：未预期错误也要回到界面提示
            logger.error("更新下载失败：版本 %s（%s）", version, type(error).__name__)
            self.failed.emit(f"更新下载失败：{error}")
            return
        logger.info("更新安装包校验成功：版本 %s", version)
        self.prepared.emit(plan)


class UpdateInstallWorker(QThread):
    """在后台等待更新脚本的启动标记，避免阻塞界面。

    ``confirmed`` 表示脚本已经运行到写入标记这一步，可以退出主程序；
    ``failed`` 携带可展示的原因，主程序应保留当前版本继续运行。
    """

    confirmed = Signal()
    failed = Signal(str)

    def __init__(
        self,
        handshake: InstallHandshake,
        log_file: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handshake = handshake
        self._log_file = log_file

    def run(self) -> None:
        reason = self._handshake.wait()
        if reason is None:
            self.confirmed.emit()
            return
        if self._log_file is not None:
            append_update_log(self._log_file, f"启动确认失败：{reason}")
        self.failed.emit(reason)
