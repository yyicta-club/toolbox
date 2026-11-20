"""更新检查与下载的后台线程：网络请求和磁盘操作都不在界面线程执行。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from yyict_toolbox.updates import (
    UpdateCandidate,
    UpdateCancelled,
    UpdateError,
    prepare_update,
    resolve_update,
)


class UpdateCheckWorker(QThread):
    """查询发布源；``resolved`` 携带 ``UpdateCandidate`` 或 ``None``。"""

    resolved = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            candidate = resolve_update()
        except UpdateError as error:
            self.failed.emit(str(error))
            return
        except Exception as error:  # 线程边界：未预期错误也要回到界面提示
            self.failed.emit(f"检查更新失败：{error}")
            return
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
        try:
            plan = prepare_update(
                self._candidate,
                self._root,
                progress=self._report_progress,
            )
        except UpdateCancelled:
            self.cancelled.emit()
            return
        except UpdateError as error:
            self.failed.emit(str(error))
            return
        except Exception as error:  # 线程边界：未预期错误也要回到界面提示
            self.failed.emit(f"更新下载失败：{error}")
            return
        self.prepared.emit(plan)
