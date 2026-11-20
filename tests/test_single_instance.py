from pathlib import Path

from yyict_toolbox.single_instance import SingleInstanceGuard, default_lock_path


def test_second_instance_is_rejected_until_first_releases(tmp_path: Path) -> None:
    lock_path = tmp_path / ".toolbox.lock"
    first = SingleInstanceGuard(lock_path)
    second = SingleInstanceGuard(lock_path)
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


def test_release_without_acquire_is_noop(tmp_path: Path) -> None:
    guard = SingleInstanceGuard(tmp_path / ".toolbox.lock")
    guard.release()
    assert guard.acquire() is True
    guard.release()


def test_acquire_creates_lock_file_in_new_directory(tmp_path: Path) -> None:
    lock_path = tmp_path / "nested" / ".toolbox.lock"
    guard = SingleInstanceGuard(lock_path)
    assert guard.acquire() is True
    assert lock_path.exists()
    guard.release()


def test_acquire_returns_false_when_lock_path_is_directory(tmp_path: Path) -> None:
    lock_path = tmp_path / ".toolbox.lock"
    lock_path.mkdir()
    guard = SingleInstanceGuard(lock_path)
    assert guard.acquire() is False
    guard.release()


def test_acquire_returns_false_when_parent_path_is_file(tmp_path: Path) -> None:
    blocked_parent = tmp_path / "yyict-toolbox"
    blocked_parent.write_text("占用", encoding="utf-8")
    guard = SingleInstanceGuard(blocked_parent / ".toolbox.lock")
    assert guard.acquire() is False
    guard.release()


def test_default_lock_path_is_per_user_and_app_scoped() -> None:
    lock_path = default_lock_path()
    assert lock_path.name == ".toolbox.lock"
    assert lock_path.parent.name == "yyict-toolbox"
