"""应用内更新：解析发布清单、下载并校验安装包、生成退出后替换文件的脚本。

发布物约定：仓库 Release 中同时上传 ``manifest.json`` 和整包 zip。清单只描述版本、
说明、最低支持版本和安装包文件名、SHA-256、大小；安装包与清单的下载地址由发布
平台的 API 提供，因此同一份清单可在 Gitea 与 GitHub 之间复用。

更新只替换打包后的 onedir 目录；源码运行时不下载安装包。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from yyict_toolbox import __version__
from yyict_toolbox.logging_system import UPDATE_LOGGER_NAME

GITEA_SERVER = "http://103.236.53.254:3560"
GITEA_REPOSITORY = "yyict/yyict-toolbox"
# 备用仓库建好后填写 "owner/repo"；为空表示只使用 Gitea 源。
GITHUB_REPOSITORY = ""

EXECUTABLE_NAME = "YYICToolbox.exe"
MANIFEST_ASSET = "manifest.json"
RESULT_FILE_NAME = "last-result.txt"
REQUEST_TIMEOUT_SECONDS = 10.0
_CHUNK_SIZE = 256 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class UpdateError(RuntimeError):
    """更新检查或安装包准备失败；消息可直接展示给用户。"""


class UpdateCancelled(RuntimeError):
    """用户取消了下载；由界面区分取消与失败。"""


@dataclass(frozen=True)
class ReleaseSource:
    """一个发布平台入口，按顺序尝试。"""

    name: str
    api_url: str


@dataclass(frozen=True)
class ReleaseManifest:
    """发布清单内容；字段含义见模块文档。"""

    version: str
    notes: str
    min_supported: str
    package_name: str
    package_sha256: str
    package_size: int


@dataclass(frozen=True)
class UpdateCandidate:
    """来自某个发布源的可用更新。"""

    source: ReleaseSource
    manifest: ReleaseManifest
    package_url: str

    def is_required(self, current_version: str) -> bool:
        """当前版本低于清单要求的最低版本时返回 True。"""
        return is_newer(self.manifest.min_supported, current_version)


@dataclass(frozen=True)
class InstallPlan:
    """已下载并解压、等待退出后替换的安装包。"""

    version: str
    work_dir: Path
    staging_dir: Path
    executable: Path


def parse_version(text: str) -> tuple[int, ...]:
    """把 ``0.2.1`` 或 ``v0.2.1`` 解析为可比较的整数元组。"""
    cleaned = text.strip()
    if cleaned[:1] in {"v", "V"}:
        cleaned = cleaned[1:]
    parts = cleaned.split(".")
    if not 1 <= len(parts) <= 4 or not all(part.isdigit() for part in parts):
        raise ValueError(f"无法识别的版本号：{text!r}")
    return tuple(int(part) for part in parts)


def compare_versions(left: str, right: str) -> int:
    """返回 -1、0、1 表示 ``left`` 小于、等于或大于 ``right``。"""
    left_parts = parse_version(left)
    right_parts = parse_version(right)
    width = max(len(left_parts), len(right_parts))
    left_padded = left_parts + (0,) * (width - len(left_parts))
    right_padded = right_parts + (0,) * (width - len(right_parts))
    if left_padded == right_padded:
        return 0
    return 1 if left_padded > right_padded else -1


def is_newer(candidate: str, current: str) -> bool:
    return compare_versions(candidate, current) > 0


def default_sources() -> tuple[ReleaseSource, ...]:
    """按优先级返回发布源：Gitea 优先，GitHub 兜底。"""
    sources = [
        ReleaseSource(
            "gitea",
            f"{GITEA_SERVER}/api/v1/repos/{GITEA_REPOSITORY}/releases/latest",
        )
    ]
    if GITHUB_REPOSITORY:
        sources.append(
            ReleaseSource(
                "github",
                f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest",
            )
        )
    return tuple(sources)


def fetch_json(url: str, timeout: float = REQUEST_TIMEOUT_SECONDS) -> object:
    """以 JSON 方式读取发布信息；网络错误交给调用方处理。"""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"yyict-toolbox/{__version__}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        # 兼容 PowerShell 5.1 生成的带 BOM 清单文件。
        return json.loads(response.read().decode("utf-8-sig"))


def parse_manifest(payload: object) -> ReleaseManifest:
    """校验并转换清单；任何不符合约定的字段都抛 ``UpdateError``。"""
    if not isinstance(payload, dict):
        raise UpdateError("更新清单不是 JSON 对象")
    version = payload.get("version")
    if not isinstance(version, str):
        raise UpdateError("更新清单缺少版本号")
    try:
        parse_version(version)
    except ValueError as error:
        raise UpdateError(str(error)) from error

    notes = payload.get("notes", "")
    if not isinstance(notes, str):
        raise UpdateError("更新说明必须是文本")

    min_supported = payload.get("min_supported", "0.0.0")
    if not isinstance(min_supported, str):
        raise UpdateError("最低支持版本必须是文本")
    try:
        parse_version(min_supported)
    except ValueError as error:
        raise UpdateError(str(error)) from error

    package = payload.get("package")
    if not isinstance(package, dict):
        raise UpdateError("更新清单缺少安装包信息")
    name = package.get("name")
    digest = package.get("sha256")
    size = package.get("size")
    if not isinstance(name, str) or Path(name).name != name or not name.endswith(".zip"):
        raise UpdateError("安装包文件名不合法")
    if not isinstance(digest, str) or not _SHA256_PATTERN.match(digest.lower()):
        raise UpdateError("安装包校验值必须是 64 位十六进制 SHA-256")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise UpdateError("安装包大小必须是正整数")

    return ReleaseManifest(
        version=version,
        notes=notes,
        min_supported=min_supported,
        package_name=name,
        package_sha256=digest.lower(),
        package_size=size,
    )


def _release_assets(release: object) -> dict[str, str]:
    if not isinstance(release, dict):
        raise UpdateError("发布信息不是 JSON 对象")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("发布信息缺少附件列表")
    urls: dict[str, str] = {}
    for asset in assets:
        if not isinstance(asset, Mapping):
            continue
        name = asset.get("name")
        url = asset.get("browser_download_url")
        if isinstance(name, str) and isinstance(url, str):
            urls[name] = url
    return urls


def _ensure_web_url(url: str, label: str) -> str:
    if not url.startswith(("http://", "https://")):
        raise UpdateError(f"{label}不是有效的下载地址")
    return url


def _candidate_from_release(
    source: ReleaseSource,
    release: object,
    fetch: Callable[[str], object],
) -> UpdateCandidate:
    assets = _release_assets(release)
    manifest_url = assets.get(MANIFEST_ASSET)
    if manifest_url is None:
        raise UpdateError(f"{source.name} 的最新发布缺少 {MANIFEST_ASSET}")
    manifest = parse_manifest(fetch(_ensure_web_url(manifest_url, "更新清单")))
    package_url = assets.get(manifest.package_name)
    if package_url is None:
        raise UpdateError(f"{source.name} 的最新发布缺少 {manifest.package_name}")
    return UpdateCandidate(source, manifest, _ensure_web_url(package_url, "安装包"))


def resolve_update(
    sources: Sequence[ReleaseSource] | None = None,
    current_version: str = __version__,
    *,
    fetch: Callable[[str], object] = fetch_json,
) -> UpdateCandidate | None:
    """按顺序查询发布源，返回高于当前版本的最新候选；没有更新返回 None。

    单个源失败不影响后续源；所有源都失败时抛 ``UpdateError``。
    """
    ordered = tuple(sources) if sources is not None else default_sources()
    failures: list[str] = []
    candidate: UpdateCandidate | None = None
    served = False
    for source in ordered:
        try:
            update = _candidate_from_release(source, fetch(source.api_url), fetch)
        except urllib.error.HTTPError as error:
            # 还没有发布任何版本的源不算故障，继续看下一个源。
            if error.code != 404:
                failures.append(f"{source.name}：HTTP {error.code}")
            continue
        except (OSError, ValueError, UpdateError) as error:
            failures.append(f"{source.name}：{error}")
            continue
        served = True
        if not is_newer(update.manifest.version, current_version):
            continue
        if candidate is None or is_newer(update.manifest.version, candidate.manifest.version):
            candidate = update
    if candidate is None and failures and not served:
        raise UpdateError("无法获取更新信息：" + "；".join(failures))
    return candidate


def download_package(
    candidate: UpdateCandidate,
    destination: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> Path:
    """流式下载安装包并校验大小与 SHA-256，校验失败不留下文件。"""
    manifest = candidate.manifest
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    digest = hashlib.sha256()
    received = 0
    completed = False
    request = urllib.request.Request(
        candidate.package_url,
        headers={"User-Agent": f"yyict-toolbox/{__version__}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or manifest.package_size)
            with open(partial, "wb") as handle:
                while chunk := response.read(_CHUNK_SIZE):
                    handle.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if progress is not None:
                        progress(received, total)
        completed = True
    finally:
        if not completed:
            partial.unlink(missing_ok=True)

    if received != manifest.package_size:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"安装包大小不符：期望 {manifest.package_size}，实际 {received}")
    if digest.hexdigest() != manifest.package_sha256:
        partial.unlink(missing_ok=True)
        raise UpdateError("安装包校验失败，请稍后重试")
    partial.replace(destination)
    return destination


def extract_package(archive: Path, staging: Path) -> Path:
    """解压安装包并确认可执行文件位于根目录；拒绝越出解压目录的条目。"""
    staging.mkdir(parents=True, exist_ok=True)
    root = staging.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            target = (root / info.filename).resolve()
            if not target.is_relative_to(root):
                raise UpdateError("安装包包含非法路径，已停止更新")
        bundle.extractall(root)
    executable = root / EXECUTABLE_NAME
    if not executable.is_file():
        raise UpdateError(f"安装包根目录缺少 {EXECUTABLE_NAME}")
    return executable


def updates_root(base: Path | None = None) -> Path:
    """返回更新工作目录，默认位于用户本地数据目录。"""
    if base is None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "yyict-toolbox" / "updates"


def install_directory() -> Path:
    """返回程序目录：打包后为 exe 所在目录，源码运行时为仓库根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def is_frozen_install() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_portable_install() -> bool:
    """单文件便携版：依赖被解压到临时目录，而不是 exe 旁的 ``_internal``。"""
    if not is_frozen_install():
        return False
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir is None:
        return False
    return Path(bundle_dir).parent != install_directory()


def release_page_url() -> str:
    """返回发布页面地址，供便携版手动下载新 exe。"""
    return f"{GITEA_SERVER}/{GITEA_REPOSITORY}/releases"


def prepare_update(
    candidate: UpdateCandidate,
    root: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> InstallPlan:
    """下载并解压安装包到独立目录，返回可交给替换脚本的计划。"""
    work_dir = root / candidate.manifest.version
    if work_dir.exists():
        shutil.rmtree(work_dir)
    staging_dir = work_dir / "package"
    staging_dir.mkdir(parents=True)
    archive = work_dir / candidate.manifest.package_name
    download_package(candidate, archive, progress=progress)
    executable = extract_package(archive, staging_dir)
    _remove_stale_versions(root, keep=work_dir)
    return InstallPlan(candidate.manifest.version, work_dir, staging_dir, executable)


def _remove_stale_versions(root: Path, keep: Path) -> None:
    if not root.is_dir():
        return
    for entry in root.iterdir():
        if entry.is_dir() and entry != keep:
            shutil.rmtree(entry, ignore_errors=True)


_APPLY_SCRIPT_TEMPLATE = """$ErrorActionPreference = 'Stop'
$appPid = @PID@
$installDir = @INSTALL@
$stagingDir = @STAGING@
$version = @VERSION@
$resultFile = @RESULT@
$backupDir = $installDir + '.old'
$executable = Join-Path $installDir 'YYICToolbox.exe'
$moved = $false

Set-Location $env:TEMP
$deadline = (Get-Date).AddMinutes(5)
while ((Get-Process -Id $appPid -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $deadline)) {
    Start-Sleep -Milliseconds 500
}

try {
    if (Test-Path -LiteralPath $backupDir) {
        Remove-Item -LiteralPath $backupDir -Recurse -Force
    }
    Move-Item -LiteralPath $installDir -Destination $backupDir
    $moved = $true
    robocopy $stagingDir $installDir /E /MOVE /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy 退出码 $LASTEXITCODE"
    }
    if (-not (Test-Path -LiteralPath $executable)) {
        throw '更新后的目录缺少可执行文件'
    }
    # 先写结果再启动，保证新进程启动时能读到本次更新状态。
    Set-Content -LiteralPath $resultFile -Value "applied $version" -Encoding UTF8
    Start-Process -FilePath $executable -WorkingDirectory $installDir
    Remove-Item -LiteralPath $backupDir -Recurse -Force -ErrorAction SilentlyContinue
}
catch {
    if ($moved -and (Test-Path -LiteralPath $installDir)) {
        Remove-Item -LiteralPath $installDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($moved -and (Test-Path -LiteralPath $backupDir)) {
        Move-Item -LiteralPath $backupDir -Destination $installDir
    }
    Set-Content -LiteralPath $resultFile -Value "failed $version" -Encoding UTF8
    exit 1
}
"""


def _ps_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def write_apply_script(install_dir: Path, plan: InstallPlan, app_pid: int) -> Path:
    """生成等待本进程退出后替换目录的 PowerShell 脚本；返回脚本路径。"""
    script = plan.work_dir / "apply-update.ps1"
    script.parent.mkdir(parents=True, exist_ok=True)
    content = (
        _APPLY_SCRIPT_TEMPLATE.replace("@PID@", str(int(app_pid)))
        .replace("@INSTALL@", _ps_literal(install_dir))
        .replace("@STAGING@", _ps_literal(plan.staging_dir))
        .replace("@VERSION@", _ps_literal(plan.version))
        .replace("@RESULT@", _ps_literal(plan.work_dir.parent / RESULT_FILE_NAME))
    )
    script.write_text(content, encoding="utf-8-sig")
    return script


def launch_apply_script(script: Path) -> None:
    """后台启动替换脚本；脚本自身等待进程退出，调用方随后应尽快退出。"""
    if not is_frozen_install():
        raise UpdateError("源码模式不支持自动替换程序文件")
    if is_portable_install():
        raise UpdateError("便携版是单个 exe，请下载新版本后手动替换")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "DETACHED_PROCESS", 0
    )
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(script),
        ],
        cwd=str(script.parent),
        creationflags=creation_flags,
        close_fds=True,
    )


def apply_update(plan: InstallPlan, app_pid: int) -> Path:
    """生成并启动替换脚本；失败抛 ``UpdateError`` 并写入更新日志。

    日志只记录版本和错误类型，不记录脚本路径或下载地址。
    """
    logger = logging.getLogger(UPDATE_LOGGER_NAME)
    try:
        script = write_apply_script(install_directory(), plan, app_pid)
        launch_apply_script(script)
    except UpdateError as error:
        logger.error("更新安装脚本启动失败：版本 %s（%s）", plan.version, type(error).__name__)
        raise
    except OSError as error:
        logger.error("更新安装脚本启动失败：版本 %s（%s）", plan.version, type(error).__name__)
        raise UpdateError(f"无法启动更新安装脚本：{error}") from error
    logger.info("更新安装脚本已启动：版本 %s", plan.version)
    return script


def consume_update_result(root: Path | None = None) -> tuple[str, str] | None:
    """读取并删除上次替换脚本留下的结果，返回 ``(状态, 版本)``。"""
    path = updates_root(root) / RESULT_FILE_NAME
    if not path.is_file():
        return None
    try:
        # Windows PowerShell 5.1 写出的 UTF-8 带 BOM，按 utf-8-sig 读取两种编码都兼容。
        text = path.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return None
    finally:
        path.unlink(missing_ok=True)
    parts = text.split()
    if len(parts) != 2 or parts[0] not in {"applied", "failed"}:
        return None
    try:
        parse_version(parts[1])
    except ValueError:
        return None
    logger = logging.getLogger(UPDATE_LOGGER_NAME)
    if parts[0] == "applied":
        logger.info("自动更新成功：已更新到 %s", parts[1])
    else:
        logger.warning("自动更新失败并已回滚：版本 %s", parts[1])
    # 替换已完成或已回滚，安装包与解压目录都不再需要，避免长期占用磁盘。
    shutil.rmtree(path.parent / parts[1], ignore_errors=True)
    return parts[0], parts[1]
