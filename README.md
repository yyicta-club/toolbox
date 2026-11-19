# 校园工具箱

基于 Python 3.12+、PySide6 和 pluggy 的校园桌面工具箱。
## 开发环境

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

启动桌面应用：

```powershell
python -m yyict_toolbox
```

运行测试：

```powershell
python -m pytest
```

## Windows 打包

在 Windows x64 环境安装开发依赖后运行：

```powershell
.\scripts\build_windows.ps1
```

应用目录输出到 `dist/YYICToolbox/`。PyInstaller 应在目标操作系统上构建对应平台的应用。

## 插件结构

插件通过 `plugins/specs.py` 定义的 pluggy Hook 提供工具元数据。首版只注册随应用分发的内置插件，不扫描外部插件目录。
