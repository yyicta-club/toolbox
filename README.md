# 校园工具箱

基于 Python 3.12+、PySide6 和 pluggy 的校园桌面工具箱。

## 校园网自动登录

在界面填写账号（不带运营商后缀）、密码，选择中国移动、中国联通或中国电信，设置探针间隔和日志等级，然后点击“启动监控”。配置同时保存；密码使用 Windows 凭据库，其余设置由 QSettings 保存到当前用户配置。

- 探针默认每 60 秒运行，可配置为 10–3600 秒；启动后立即检查。两个直连 HTTP 检测地址中任意一个返回预期状态和内容即视为联网，门户跳转或错误页面不算联网。
- 离线后向固定校园门户 `192.168.40.2:801` 发起登录；设备 IPv4 从门户重定向或登录页变量动态读取，不使用抓包中的固定 IP。请求不经过系统代理、不跟随重定向。
- 登录接口成功后再检查网络。连续失败超过 3 次（第 4 次）自动停止，需要手动重新启动；网络恢复后计数清零，失败重试仍按探针间隔进行。
- 点击“后台运行”或关闭窗口后驻留系统托盘；托盘菜单可恢复界面或退出。没有系统托盘时关闭窗口会退出。启动软件后需手动启动监控，不注册开机自启或 Windows 服务。
- 启动时检测同机是否已有本程序实例在运行（按用户数据目录下的锁文件判断）；重复启动会弹窗告警并退出，锁随进程退出自动释放。
- 运行中账号、密码、运营商及间隔不可更改，请先停止监控；日志显示等级可即时切换，停止后保存以持久化。

## 日志

文件日志位于 exe 同级 `log/toolbox.log`，源码启动时位于项目根目录 `log/toolbox.log`。所有探针、登录和运行事件均写入 UTF-8 文件，单文件最多 5 MiB，保留 3 个轮转备份；程序目录需可写。日志不包含账号密码、完整认证 URL 或原始认证响应。

界面日志等级：1 仅错误，2 警告和错误，3 完整日志。界面仅保留最近 1000 条，文件不受界面过滤影响。

## 开发环境

### 系统要求

- **操作系统**：Windows 10/11 x64（主要目标平台）
- **Python**：3.12 或更高版本
- **包管理**：pip 或 [uv](https://github.com/astral-sh/uv)（推荐）

### 依赖安装

**方式一：使用 pip（标准）**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

**方式二：使用 uv（推荐，更快）**

```powershell
uv venv --python 3.12
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[dev]"
```

**核心依赖说明**：

| 依赖 | 版本 | 用途 |
|------|------|------|
| `keyring` | >=25,<26 | Windows 凭据库存储密码 |
| `pluggy` | >=1.5,<2 | 插件 Hook 框架 |
| `PySide6_Essentials` | ==6.9.3 | Qt UI 框架（固定版本） |

**开发依赖**（`[dev]`）：

| 依赖 | 版本 | 用途 |
|------|------|------|
| `pytest` | >=8,<9 | 测试框架 |
| `pyinstaller` | >=6.10,<7 | Windows 打包 |

### IDE 配置

**PyCharm**：
1. 打开项目，选择 `Settings → Project → Python Interpreter`
2. 添加解释器 → 选择 `.venv\Scripts\python.exe`
3. 右键 `tests/` 目录 → `Run pytest` 验证配置

**VSCode**：
1. 安装 Python 扩展
2. `Ctrl+Shift+P` → `Python: Select Interpreter` → 选择 `.venv`
3. 测试面板自动识别 pytest

### 运行调试

启动桌面应用：

```powershell
python -m yyict_toolbox
```

### 测试规范

运行全部测试：

```powershell
python -m pytest
```

运行指定测试：

```powershell
python -m pytest tests/test_plugins.py -v
```

**UI 测试**：涉及 UI 的自动化测试需设置 offscreen 模式：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest tests/test_ui.py
```

## Windows 打包

在 Windows x64 环境安装开发依赖后运行：

```powershell
.\scripts\build_windows.ps1
```

应用目录输出到 `dist/YYICToolbox/`。PyInstaller 应在目标操作系统上构建对应平台的应用。

Qt 依赖固定为已验证打包启动的 `PySide6_Essentials==6.9.3`。如果旧环境装过其他版本的 PySide6 完整包，请使用新的虚拟环境安装项目依赖，避免 Qt 多个分发包混装；分发应用时需保留整个 `YYICToolbox` 目录，不能只复制 exe。

### 便携版（单文件）

```powershell
.\scripts\build_windows_onefile.ps1
```

输出 `dist\YYICToolbox-<版本>-portable.exe`，复制这一个文件即可运行；可以和其他发布物一起上传到 Release。单文件版每次启动都要把依赖解压到临时目录，启动速度比目录版慢，部分杀毒软件也更容易误报。配置仍保存在注册表、密码仍保存在 Windows 凭据库，所以“便携”只指程序文件本身；换机器使用时账号需要重新填写。

便携版的「检查更新」只提示新版本并打开下载页，需要手动下载同名 exe 替换；自动下载与替换仅支持目录版。

## 软件内更新

打包版本的主界面侧栏显示当前版本号，点击即可检查更新：从发布源读取清单、下载整包、校验 SHA-256，确认后退出程序，由后台脚本替换程序目录并自动重启；替换失败会回滚到原版本，结果写入更新目录并在下次启动时提示。源码运行只提示不支持自动更新，不下载安装包。

模块划分、时序和失败回滚策略见 [docs/UPDATE_ARCHITECTURE.md](docs/UPDATE_ARCHITECTURE.md)。

更新检查依次尝试 `src/yyict_toolbox/updates.py` 中的发布源：默认是自建 Gitea 仓库的 `releases/latest` API；创建 GitHub 备用仓库后，把 `GITHUB_REPOSITORY` 填成 `"owner/repo"` 即自动启用兜底。应用目录必须可写（与日志要求一致），更新不需要管理员权限。

发布新版本：

```powershell
# 先修改 src/yyict_toolbox/__init__.py 与 pyproject.toml 中的版本号
.\scripts\build_release.ps1 -Notes "本次更新说明" -MinSupported "0.1.0"
```

脚本打包 onedir、生成 `dist\YYICToolbox-<版本>-win64.zip` 与 `dist\manifest.json`。在 Gitea（或 GitHub）创建以版本号命名的 Release，同时上传 `manifest.json` 和 zip 两个附件，清单内 `package.name` 必须与 zip 文件名一致。`min_supported` 表示低于该版本的客户端应强制更新，没有特殊要求时传当前版本即可。`manifest.json` 形如：

```json
{
  "version": "0.2.0",
  "notes": "修复探针相关问题",
  "min_supported": "0.1.0",
  "package": {
    "name": "YYICToolbox-0.2.0-win64.zip",
    "sha256": "<64 位十六进制>",
    "size": 123456789
  }
}
```

## 插件结构

插件通过 `plugins/specs.py` 定义的 pluggy Hook 提供工具元数据和页面工厂。只注册随应用分发的内置插件，不扫描外部插件目录。

详细的插件开发指南请参考 [PLUGIN_DEVELOPMENT.md](PLUGIN_DEVELOPMENT.md)，其中包含完整的开发步骤和示例代码。
