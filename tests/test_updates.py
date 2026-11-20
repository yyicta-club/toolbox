import hashlib
import sys
import tomllib
import urllib.error
import zipfile
from pathlib import Path

import pytest

import yyict_toolbox.updates as updates
from yyict_toolbox import __version__
from yyict_toolbox.updates import (
    EXECUTABLE_NAME,
    RESULT_FILE_NAME,
    InstallPlan,
    ReleaseManifest,
    ReleaseSource,
    UpdateCandidate,
    UpdateError,
    compare_versions,
    consume_update_result,
    download_package,
    extract_package,
    is_newer,
    parse_manifest,
    parse_version,
    prepare_update,
    release_page_url,
    resolve_update,
    updates_root,
    write_apply_script,
)


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
