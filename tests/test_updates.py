import hashlib
import logging
import os
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import zipfile
from pathlib import Path

import pytest

import yyict_toolbox.ui.update_worker as update_worker
import yyict_toolbox.updates as updates
from yyict_toolbox import __version__
from yyict_toolbox.logging_system import UPDATE_LOGGER_NAME
from yyict_toolbox.updates import (
    APPLY_LOG_NAME,
    EXECUTABLE_NAME,
    RESULT_FILE_NAME,
    InstallHandshake,
    InstallPlan,
    ReleaseManifest,
    ReleaseSource,
    UpdateCandidate,
    UpdateCancelled,
    UpdateError,
    compare_versions,
    consume_update_result,
    download_package,
    extract_package,
    is_newer,
    new_start_marker,
    parse_manifest,
    parse_version,
    prepare_update,
    release_page_url,
    resolve_update,
    updates_root,
    write_apply_script,
)

WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != 'win32', reason='替换脚本只在 Windows 上运行'
)


class FakeProcess:
    """模拟脚本进程：poll() 返回退出码，仍在运行时返回 None。"""

    def __init__(self, returncode=None, pid=1234):
        self._returncode = returncode
        self.pid = pid

    def poll(self):
        return self._returncode


@pytest.fixture
def update_logs(caplog):
    """捕获版本更新日志；更新 logger 不向根 logger 传播，需要直接挂载捕获器。"""
    logger = logging.getLogger(UPDATE_LOGGER_NAME)
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)
        logger.setLevel(previous_level)


def make_package(path: Path, files: dict[str, str] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr(EXECUTABLE_NAME, "stub")
        for name, content in (files or {}).items():
            bundle.writestr(name, content)
    return path


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_for(package: Path, version: str = "0.2.0", min_supported: str = "0.1.0") -> ReleaseManifest:
    return ReleaseManifest(
        version=version,
        notes="修复若干问题",
        min_supported=min_supported,
        package_name=package.name,
        package_sha256=sha256_of(package),
        package_size=package.stat().st_size,
    )


def release_payload(assets: dict[str, str]) -> dict:
    return {
        "tag_name": "v0.2.0",
        "assets": [
            {"name": name, "browser_download_url": url} for name, url in assets.items()
        ],
    }


def test_version_parsing_accepts_prefix_and_padding():
    assert parse_version("v0.2.1") == (0, 2, 1)
    assert compare_versions("0.10.0", "0.9.9") == 1
    assert compare_versions("0.2", "0.2.0") == 0
    assert is_newer("0.2.0", "0.1.9")
    assert not is_newer("0.1.0", "0.1.0")


@pytest.mark.parametrize("text", ["", "abc", "1..2", "1.2.beta", "1.2.3.4.5", "-1.0"])
def test_version_parsing_rejects_unknown_formats(text):
    with pytest.raises(ValueError):
        parse_version(text)


def test_manifest_parses_required_fields():
    payload = {
        "version": "0.2.0",
        "notes": "说明",
        "min_supported": "0.1.0",
        "package": {"name": "app.zip", "sha256": "A" * 64, "size": 42},
    }
    manifest = parse_manifest(payload)
    assert manifest.version == "0.2.0"
    assert manifest.package_sha256 == "a" * 64


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"version": "0.2"},
        {"version": "0.2.0"},
        {"version": "0.2.0", "package": {"name": "../app.zip", "sha256": "0" * 64, "size": 1}},
        {"version": "0.2.0", "package": {"name": "app.zip", "sha256": "xyz", "size": 1}},
        {"version": "0.2.0", "package": {"name": "app.zip", "sha256": "0" * 64, "size": 0}},
        {"version": "0.2.0", "notes": 3, "package": {"name": "app.zip", "sha256": "0" * 64, "size": 1}},
    ],
)
def test_manifest_rejects_invalid_payloads(payload):
    with pytest.raises(UpdateError):
        parse_manifest(payload)


def test_resolve_falls_back_to_second_source_when_primary_fails():
    primary = ReleaseSource("gitea", "https://gitea.example/api")
    backup = ReleaseSource("github", "https://github.example/api")
    payload = release_payload(
        {
            "manifest.json": "https://github.example/manifest.json",
            "app.zip": "https://github.example/app.zip",
        }
    )
    manifest = {
        "version": "0.2.0",
        "notes": "",
        "min_supported": "0.1.0",
        "package": {"name": "app.zip", "sha256": "0" * 64, "size": 1},
    }

    def fetch(url: str) -> object:
        if url == primary.api_url:
            raise OSError("连接超时")
        if url == backup.api_url:
            return payload
        if url == "https://github.example/manifest.json":
            return manifest
        raise AssertionError(f"未预期的请求：{url}")

    candidate = resolve_update((primary, backup), "0.1.0", fetch=fetch)
    assert candidate is not None
    assert candidate.source.name == "github"
    assert candidate.package_url == "https://github.example/app.zip"


def test_resolve_returns_none_when_release_is_not_newer():
    source = ReleaseSource("gitea", "https://gitea.example/api")
    payload = release_payload(
        {
            "manifest.json": "https://gitea.example/manifest.json",
            "app.zip": "https://gitea.example/app.zip",
        }
    )
    manifest = {
        "version": "0.1.0",
        "package": {"name": "app.zip", "sha256": "0" * 64, "size": 1},
    }

    def fetch(url: str) -> object:
        return payload if url == source.api_url else manifest

    assert resolve_update((source,), "0.1.0", fetch=fetch) is None


def test_resolve_reports_failure_only_when_every_source_fails():
    primary = ReleaseSource("gitea", "https://gitea.example/api")
    backup = ReleaseSource("github", "https://github.example/api")

    def fetch(url: str) -> object:
        raise OSError("连接超时")

    with pytest.raises(UpdateError):
        resolve_update((primary, backup), "0.1.0", fetch=fetch)


def test_resolve_treats_missing_release_as_no_update():
    source = ReleaseSource("gitea", "https://gitea.example/api")

    def fetch(url: str) -> object:
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    assert resolve_update((source,), "0.1.0", fetch=fetch) is None


def test_resolve_raises_when_unreachable_source_hides_update_checks():
    missing = ReleaseSource("gitea", "https://gitea.example/api")
    unreachable = ReleaseSource("github", "https://github.example/api")

    def fetch(url: str) -> object:
        if url == missing.api_url:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        raise OSError("连接超时")

    with pytest.raises(UpdateError):
        resolve_update((missing, unreachable), "0.1.0", fetch=fetch)


def test_resolve_rejects_release_without_manifest_asset():
    source = ReleaseSource("gitea", "https://gitea.example/api")

    def fetch(url: str) -> object:
        return release_payload({"app.zip": "https://gitea.example/app.zip"})

    with pytest.raises(UpdateError):
        resolve_update((source,), "0.1.0", fetch=fetch)


def test_resolve_rejects_non_web_download_url():
    source = ReleaseSource("gitea", "https://gitea.example/api")
    payload = release_payload(
        {
            "manifest.json": "file:///tmp/manifest.json",
            "app.zip": "https://gitea.example/app.zip",
        }
    )

    def fetch(url: str) -> object:
        return payload

    with pytest.raises(UpdateError):
        resolve_update((source,), "0.1.0", fetch=fetch)


def test_required_update_uses_min_supported():
    manifest = ReleaseManifest("0.3.0", "", "0.2.0", "app.zip", "0" * 64, 1)
    candidate = UpdateCandidate(
        ReleaseSource("gitea", "https://gitea.example/api"),
        manifest,
        "file://localhost/app.zip",
    )
    assert candidate.is_required("0.1.0")
    assert not candidate.is_required("0.2.0")


def test_download_verifies_size_and_digest(tmp_path):
    package = make_package(tmp_path / "app.zip", {"data.txt": "payload"})
    candidate = UpdateCandidate(
        ReleaseSource("file", "file://localhost"),
        manifest_for(package),
        package.as_uri(),
    )
    target = tmp_path / "downloads" / "app.zip"
    received: list[tuple[int, int]] = []
    download_package(candidate, target, progress=lambda done, total: received.append((done, total)))
    assert target.read_bytes() == package.read_bytes()
    assert received and received[-1][0] == package.stat().st_size


def test_download_rejects_wrong_digest_and_leaves_no_file(tmp_path):
    package = make_package(tmp_path / "app.zip")
    manifest = ReleaseManifest("0.2.0", "", "0.1.0", package.name, "0" * 64, package.stat().st_size)
    candidate = UpdateCandidate(
        ReleaseSource("file", "file://localhost"), manifest, package.as_uri()
    )
    target = tmp_path / "downloads" / "app.zip"
    with pytest.raises(UpdateError):
        download_package(candidate, target)
    assert not target.exists()
    assert not target.with_name(target.name + ".part").exists()


def test_extract_rejects_entries_outside_staging(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../evil.txt", "x")
        bundle.writestr(EXECUTABLE_NAME, "stub")
    with pytest.raises(UpdateError):
        extract_package(archive, tmp_path / "staging")
    assert not (tmp_path / "evil.txt").exists()


def test_extract_requires_executable_in_root(tmp_path):
    archive = tmp_path / "app.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("readme.txt", "x")
    with pytest.raises(UpdateError):
        extract_package(archive, tmp_path / "staging")


def test_prepare_update_downloads_and_extracts(tmp_path):
    package = make_package(tmp_path / "app.zip", {"data.txt": "payload"})
    candidate = UpdateCandidate(
        ReleaseSource("file", "file://localhost"),
        manifest_for(package),
        package.as_uri(),
    )
    plan = prepare_update(candidate, tmp_path / "updates")
    assert plan.executable == plan.staging_dir / EXECUTABLE_NAME
    assert plan.executable.is_file()
    assert (plan.staging_dir / "data.txt").read_text(encoding="utf-8") == "payload"
    assert plan.version == "0.2.0"


def test_apply_script_waits_for_process_and_escapes_paths(tmp_path):
    install_dir = tmp_path / "O'Brien" / "YYICToolbox"
    work_dir = tmp_path / "updates" / "0.2.0"
    plan = InstallPlan(
        version="0.2.0",
        work_dir=work_dir,
        staging_dir=work_dir / "package",
        executable=work_dir / "package" / EXECUTABLE_NAME,
    )
    script = write_apply_script(install_dir, plan, 4321)
    content = script.read_text(encoding="utf-8-sig")
    assert "$appPid = 4321" in content
    assert "Get-Process -Id $appPid" in content
    assert "'" + str(install_dir).replace("'", "''") + "'" in content
    assert "robocopy" in content
    assert "failed $version" in content
    assert str(work_dir.parent / RESULT_FILE_NAME) in content


def test_consume_update_result_reads_and_removes_file(tmp_path):
    root = updates_root(tmp_path)
    root.mkdir(parents=True)
    (root / RESULT_FILE_NAME).write_text("applied 0.2.0", encoding="utf-8")
    work_dir = root / "0.2.0"
    work_dir.mkdir()
    (work_dir / "app.zip").write_bytes(b"x")
    assert consume_update_result(tmp_path) == ("applied", "0.2.0")
    assert not (root / RESULT_FILE_NAME).exists()
    assert not work_dir.exists()
    assert consume_update_result(tmp_path) is None


def test_consume_update_result_ignores_unknown_status(tmp_path):
    root = updates_root(tmp_path)
    root.mkdir(parents=True)
    (root / RESULT_FILE_NAME).write_text("unknown 0.2.0", encoding="utf-8")
    assert consume_update_result(tmp_path) is None


def test_consume_update_result_keeps_failure_log(tmp_path):
    root = updates_root(tmp_path)
    work_dir = root / "0.2.0"
    package_dir = work_dir / "package"
    package_dir.mkdir(parents=True)
    (package_dir / "data.txt").write_text("payload", encoding="utf-8")
    log_file = work_dir / APPLY_LOG_NAME
    log_file.write_text("更新失败：robocopy 退出码 16", encoding="utf-8")
    (root / RESULT_FILE_NAME).write_text("failed 0.2.0", encoding="utf-8")
    assert consume_update_result(tmp_path) == ("failed", "0.2.0")
    # 失败时保留更新日志供排查，只清理下载的安装包。
    assert log_file.is_file()
    assert not package_dir.exists()


def test_package_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__


def test_portable_install_detected_by_temporary_bundle_dir(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    monkeypatch.setattr(updates, "install_directory", lambda: app_dir)
    monkeypatch.setattr(updates, "is_frozen_install", lambda: True)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle" / "_MEI123"), raising=False)
    assert updates.is_portable_install()
    monkeypatch.setattr(sys, "_MEIPASS", str(app_dir / "_internal"), raising=False)
    assert not updates.is_portable_install()


def test_source_mode_is_not_a_portable_install(monkeypatch):
    monkeypatch.setattr(updates, "is_frozen_install", lambda: False)
    assert not updates.is_portable_install()


def test_portable_install_cannot_apply_update_automatically(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "is_frozen_install", lambda: True)
    monkeypatch.setattr(updates, "is_portable_install", lambda: True)
    with pytest.raises(UpdateError):
        updates.launch_apply_script(tmp_path / "apply-update.ps1")


def test_release_page_url_points_to_repository_releases():
    assert release_page_url() == f"{updates.GITEA_SERVER}/{updates.GITEA_REPOSITORY}/releases"


def update_candidate(version='0.2.0'):
    return UpdateCandidate(
        ReleaseSource('gitea', 'https://gitea.example/api'),
        ReleaseManifest(version, '说明', '0.1.0', 'app.zip', '0' * 64, 1),
        'https://gitea.example/app.zip',
    )


def test_update_check_logs_start_and_no_available_update(update_logs, monkeypatch):
    monkeypatch.setattr(update_worker, 'resolve_update', lambda: None)
    update_worker.UpdateCheckWorker().run()
    assert '更新检查开始' in update_logs.text
    assert '无可用更新' in update_logs.text


def test_update_check_logs_found_version(update_logs, monkeypatch):
    monkeypatch.setattr(update_worker, 'resolve_update', update_candidate)
    update_worker.UpdateCheckWorker().run()
    assert '更新检查完成：发现新版本 0.2.0' in update_logs.text


def test_update_check_failure_logs_error_type_only(update_logs, monkeypatch):
    def fail():
        raise UpdateError('无法获取更新信息：gitea：连接超时')

    monkeypatch.setattr(update_worker, 'resolve_update', fail)
    update_worker.UpdateCheckWorker().run()
    assert '更新检查失败' in update_logs.text
    assert 'UpdateError' in update_logs.text
    assert 'gitea.example' not in update_logs.text


def test_update_download_logs_start_and_verified_package(update_logs, monkeypatch, tmp_path):
    plan = InstallPlan('0.2.0', tmp_path, tmp_path, tmp_path / EXECUTABLE_NAME)
    monkeypatch.setattr(update_worker, 'prepare_update', lambda *args, **kwargs: plan)
    update_worker.UpdateDownloadWorker(update_candidate(), tmp_path).run()
    assert '更新下载开始：版本 0.2.0' in update_logs.text
    assert '更新安装包校验成功：版本 0.2.0' in update_logs.text


def test_update_download_logs_cancellation(update_logs, monkeypatch, tmp_path):
    def cancel(*args, **kwargs):
        raise UpdateCancelled()

    monkeypatch.setattr(update_worker, 'prepare_update', cancel)
    update_worker.UpdateDownloadWorker(update_candidate(), tmp_path).run()
    assert '更新下载已取消：版本 0.2.0' in update_logs.text


def test_update_download_failure_logs_error_type_only(update_logs, monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise UpdateError('安装包校验失败，请稍后重试')

    monkeypatch.setattr(update_worker, 'prepare_update', fail)
    update_worker.UpdateDownloadWorker(update_candidate(), tmp_path).run()
    assert '更新下载失败：版本 0.2.0' in update_logs.text
    assert 'UpdateError' in update_logs.text
    assert 'gitea.example' not in update_logs.text


def test_launch_update_install_logs_install_start(update_logs, monkeypatch, tmp_path):
    plan = InstallPlan('0.2.0', tmp_path, tmp_path, tmp_path / EXECUTABLE_NAME)
    monkeypatch.setattr(updates, 'install_directory', lambda: tmp_path)
    monkeypatch.setattr(updates, 'launch_apply_script', lambda script: FakeProcess())
    launch = updates.launch_update_install(plan, 4321)
    assert launch.marker.parent == tmp_path
    assert not launch.marker.exists()
    assert '更新安装脚本已启动：版本 0.2.0' in update_logs.text


def test_launch_update_install_failure_logs_error_type_only(update_logs, monkeypatch, tmp_path):
    plan = InstallPlan('0.2.0', tmp_path, tmp_path, tmp_path / EXECUTABLE_NAME)
    monkeypatch.setattr(updates, 'install_directory', lambda: tmp_path)
    with pytest.raises(UpdateError):
        updates.launch_update_install(plan, 4321)
    assert '更新安装脚本启动失败：版本 0.2.0' in update_logs.text
    assert 'UpdateError' in update_logs.text


def test_apply_script_is_launched_in_visible_window(monkeypatch, tmp_path):
    captured = {}

    def fake_popen(command, **kwargs):
        captured['command'] = command
        captured['kwargs'] = kwargs
        return FakeProcess()

    monkeypatch.setattr(updates, 'is_frozen_install', lambda: True)
    monkeypatch.setattr(updates, 'is_portable_install', lambda: False)
    monkeypatch.setattr(subprocess, 'Popen', fake_popen)
    updates.launch_apply_script(tmp_path / 'apply-update.ps1')
    assert 'Hidden' not in captured['command']
    assert '-WindowStyle' not in captured['command']
    assert '-NonInteractive' not in captured['command']
    flags = captured['kwargs']['creationflags']
    assert not flags & getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def test_install_handshake_confirms_after_marker_is_written(tmp_path):
    marker = tmp_path / 'started.marker'
    handshake = InstallHandshake(marker, FakeProcess(), timeout=5)
    marker.write_text('1234', encoding='utf-8')
    assert handshake.wait() is None


def test_install_handshake_fails_when_script_exits_early(tmp_path):
    handshake = InstallHandshake(tmp_path / 'started.marker', FakeProcess(1), timeout=5)
    reason = handshake.wait()
    assert reason is not None
    assert '退出码 1' in reason


def test_install_handshake_times_out_without_marker(tmp_path):
    handshake = InstallHandshake(tmp_path / 'started.marker', FakeProcess(), timeout=0.05)
    reason = handshake.wait()
    assert reason is not None
    assert '超时' in reason


def test_start_marker_is_unique_for_each_install(tmp_path):
    assert new_start_marker(tmp_path) != new_start_marker(tmp_path)


def run_apply_script(script: Path, work_dir: Path) -> subprocess.CompletedProcess:
    """在隐藏窗口中运行替换脚本，避免测试时弹出控制台窗口。"""
    output = work_dir / 'script-output.txt'
    with output.open('w', encoding='utf-8') as handle:
        return subprocess.run(
            [
                'powershell.exe',
                '-NoProfile',
                '-ExecutionPolicy',
                'Bypass',
                '-File',
                str(script),
            ],
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            cwd=str(work_dir),
            timeout=120,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )


def prepare_script_case(tmp_path, staging_files=None):
    """准备一次替换脚本运行所需的安装目录、暂存目录和脚本。"""
    install_dir = tmp_path / 'app'
    install_dir.mkdir()
    (install_dir / EXECUTABLE_NAME).write_text('old', encoding='utf-8')
    work_dir = tmp_path / 'updates' / '0.2.0'
    staging = work_dir / 'package'
    staging.mkdir(parents=True)
    for name, content in (staging_files or {}).items():
        (staging / name).write_text(content, encoding='utf-8')
    plan = InstallPlan('0.2.0', work_dir, staging, staging / EXECUTABLE_NAME)
    marker = work_dir / 'started-test.marker'
    log = work_dir / APPLY_LOG_NAME
    return install_dir, plan, marker, log


@WINDOWS_ONLY
def test_apply_script_replaces_directory_and_writes_marker(tmp_path):
    install_dir, plan, marker, log = prepare_script_case(tmp_path)
    # 用系统自带的小工具充当新版本可执行文件，脚本能真正启动它。
    helper = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'whoami.exe'
    if not helper.is_file():
        pytest.skip('系统缺少 whoami.exe，无法验证重新启动步骤')
    shutil.copy2(helper, plan.staging_dir / EXECUTABLE_NAME)
    script = write_apply_script(install_dir, plan, 999999, marker, log, wait_seconds=5)
    result = run_apply_script(script, plan.work_dir)
    assert result.returncode == 0
    assert marker.is_file()
    assert (install_dir / EXECUTABLE_NAME).read_bytes() == helper.read_bytes()
    assert not (install_dir.parent / 'app.old').exists()
    result_text = (plan.work_dir.parent / RESULT_FILE_NAME).read_text(encoding='utf-8-sig')
    assert 'applied 0.2.0' in result_text
    log_text = log.read_text(encoding='utf-8-sig')
    assert '更新脚本已启动' in log_text
    assert '替换完成' in log_text


@WINDOWS_ONLY
def test_apply_script_keeps_install_directory_when_wait_times_out(tmp_path):
    install_dir, plan, marker, log = prepare_script_case(tmp_path)
    # 当前进程仍在运行，脚本等待超时后必须放弃替换。
    script = write_apply_script(install_dir, plan, os.getpid(), marker, log, wait_seconds=1)
    result = run_apply_script(script, plan.work_dir)
    assert result.returncode == 1
    assert marker.is_file()
    assert (install_dir / EXECUTABLE_NAME).read_text(encoding='utf-8') == 'old'
    result_text = (plan.work_dir.parent / RESULT_FILE_NAME).read_text(encoding='utf-8-sig')
    assert 'failed 0.2.0' in result_text
    log_text = log.read_text(encoding='utf-8-sig')
    assert '已停止本次替换' in log_text


@WINDOWS_ONLY
def test_apply_script_restores_install_directory_when_replacement_fails(tmp_path):
    install_dir, plan, marker, log = prepare_script_case(tmp_path)
    # 暂存目录内容缺失，robocopy 失败后脚本必须恢复原安装目录。
    plan = InstallPlan('0.2.0', plan.work_dir, plan.work_dir / 'missing', plan.executable)
    script = write_apply_script(install_dir, plan, 999999, marker, log, wait_seconds=5)
    result = run_apply_script(script, plan.work_dir)
    assert result.returncode == 1
    assert (install_dir / EXECUTABLE_NAME).read_text(encoding='utf-8') == 'old'
    result_text = (plan.work_dir.parent / RESULT_FILE_NAME).read_text(encoding='utf-8-sig')
    assert 'failed 0.2.0' in result_text
    log_text = log.read_text(encoding='utf-8-sig')
    assert '更新失败' in log_text
    assert '已恢复原安装目录' in log_text


def test_consume_update_result_logs_success_and_rollback(update_logs, tmp_path):
    root = updates_root(tmp_path)
    root.mkdir(parents=True)
    (root / RESULT_FILE_NAME).write_text('applied 0.2.0', encoding='utf-8')
    assert consume_update_result(tmp_path) == ('applied', '0.2.0')
    assert '自动更新成功：已更新到 0.2.0' in update_logs.text

    root.mkdir(parents=True, exist_ok=True)
    (root / RESULT_FILE_NAME).write_text('failed 0.2.0', encoding='utf-8')
    assert consume_update_result(tmp_path) == ('failed', '0.2.0')
    assert '自动更新失败并已回滚：版本 0.2.0' in update_logs.text
