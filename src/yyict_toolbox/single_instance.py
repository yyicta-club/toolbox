"""单实例守卫：用文件锁检测同机是否已有同一程序在运行。"""

import os
import sys
from pathlib import Path
from typing import IO

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


def default_lock_path() -> Path:
    """返回默认锁文件路径；放在用户数据目录，使不同安装位置的同一程序互斥。"""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    else:
        base = Path.home() / ".local" / "share"
    return base / "yyict-toolbox" / ".toolbox.lock"


class SingleInstanceGuard:
    """基于文件锁的单实例守卫。

    锁由操作系统在进程退出时自动回收，崩溃残留的锁文件不会阻塞下次启动。
    """

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._lock_file: IO[str] | None = None

    def acquire(self) -> bool:
        """尝试获取单实例锁；返回 False 表示已有其他实例持有锁。"""
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = open(self._lock_path, "a")
        try:
            # Windows 的字节锁从当前文件位置算起，必须归零以保证各实例锁同一区域。
            lock_file.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock_file.close()
            return False
        self._lock_file = lock_file
        return True

    def release(self) -> None:
        """释放单实例锁；未持有时不做任何事。"""
        if self._lock_file is None:
            return
        try:
            self._lock_file.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            self._lock_file.close()
            self._lock_file = None
