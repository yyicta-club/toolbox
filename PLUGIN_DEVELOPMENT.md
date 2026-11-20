# 插件开发指南

本指南面向希望为 yyict-toolbox 添加新工具的开发者，分步骤讲解插件开发全流程。

## 快速上手

复制 `src/yyict_toolbox/plugins/builtin/demo_hello.py` 和 `src/yyict_toolbox/ui/demo_hello_page.py` 作为起点，修改工具 ID、名称和页面内容即可。

## 插件架构概览

```
specs.py (Hook 规范)
    ↓
DemoHelloPlugin (@hookimpl toolbox_tools)
    ↓
manager.py (create_plugin_manager 注册)
    ↓
MainWindow (侧边栏按钮 + 懒加载 view_factory)
    ↓
DemoHelloPage (QWidget 页面)
```

## 开发步骤

### 1. 定义工具元数据

工具元数据使用 `ToolDescriptor`（`plugins/specs.py`）：

```python
from yyict_toolbox.plugins.specs import ToolDescriptor

ToolDescriptor(
    id="my-tool-id",           # 稳定、唯一的 kebab-case ID
    name="我的工具",            # 中文展示名称
    description="工具描述",     # 简短说明
    available=True,             # 是否可用
    view_factory=MyPage,        # 可选：QWidget 页面工厂
)
```

**命名规范**：
- 工具 ID：kebab-case，全局唯一，稳定不变
- 名称：清晰的中文
- 描述：简短说明功能

### 2. 创建插件类

插件类无需继承基类，只需实现 `toolbox_tools` Hook：

```python
from yyict_toolbox.plugins.specs import ToolDescriptor, hookimpl

class MyPlugin:
    @hookimpl
    def toolbox_tools(self) -> list[ToolDescriptor]:
        from yyict_toolbox.ui.my_page import MyPage  # 延迟导入

        return [
            ToolDescriptor(
                id="my-tool-id",
                name="我的工具",
                description="工具描述",
                available=True,
                view_factory=MyPage,
            )
        ]
```

**注意事项**：
- `view_factory` 是 `Callable[[], QWidget] | None`，MainWindow 懒加载（首次切换到该工具时才调用）
- UI 模块在 Hook 方法内延迟导入，避免循环导入
- 插件类可注入依赖（如 `settings_store`、`log_queue`），由 `create_plugin_manager` 传入

### 3. 创建 UI 页面

UI 页面是 `QWidget` 子类，如需后台任务需实现生命周期方法：

```python
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

class MyPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Hello"))

    def shutdown(self) -> bool:
        """请求停止后台任务。返回是否已停止。"""
        return True

    def wait_for_shutdown(self) -> None:
        """阻塞等待后台任务完成。"""
```

**生命周期契约**：
- `shutdown() -> bool`：请求停止后台任务，返回是否已停止
- `wait_for_shutdown() -> None`：阻塞等待所有后台任务完成
- MainWindow 退出时自动调用这两个方法

**规范要求**：
- 页面关闭时必须支持停止后台任务并等待完成
- 禁止强杀工作线程，必须优雅退出

### 4. 注册插件

在 `plugins/manager.py` 的 `create_plugin_manager()` 中注册：

```python
from yyict_toolbox.plugins.builtin.my_plugin import MyPlugin

def create_plugin_manager(...) -> PluginManager:
    manager = PluginManager()
    manager.register(
        CampusNetworkPlugin(
            settings_store or CampusSettingsStore(),
            log_queue or Queue(),
            logger or logging.getLogger("yyict_toolbox"),
        )
    )
    manager.register(MyPlugin())  # 新增
    return manager
```

**注册规范**：
- 所有插件通过 pluggy Hook 规范接入，禁止绕过管理器让 UI 直接实例化插件
- 只注册随应用分发的内置插件，不扫描外部插件目录

### 5. 编写测试

新插件必须有注册测试（`tests/test_plugins.py`）：

```python
from yyict_toolbox.plugins.manager import create_plugin_manager

def test_my_plugin_is_registered() -> None:
    tools = create_plugin_manager().get_tools()

    my_tools = [t for t in tools if t.id == "my-tool-id"]
    assert len(my_tools) == 1
    assert my_tools[0].name == "我的工具"
    assert my_tools[0].available is True
    assert my_tools[0].view_factory is not None
```

运行测试：

```powershell
python -m pytest tests/test_plugins.py -v
```

## 示例文件清单

| 文件 | 作用 |
|------|------|
| `src/yyict_toolbox/plugins/specs.py` | Hook 规范定义（`ToolDescriptor`、`ToolboxHookSpec`） |
| `src/yyict_toolbox/plugins/builtin/demo_hello.py` | 示例插件类 `DemoHelloPlugin` |
| `src/yyict_toolbox/ui/demo_hello_page.py` | 示例 UI 页面 `DemoHelloPage` |
| `src/yyict_toolbox/plugins/manager.py` | 插件管理器（注册入口） |
| `tests/test_plugins.py` | 插件注册测试 |

## 常见问题

### 如何避免循环导入？

UI 模块在 Hook 方法内延迟导入：

```python
@hookimpl
def toolbox_tools(self) -> list[ToolDescriptor]:
    from yyict_toolbox.ui.my_page import MyPage  # 方法内导入
    return [ToolDescriptor(..., view_factory=MyPage)]
```

### 工具 ID 可以修改吗？

不建议。工具 ID 应保持稳定，修改可能导致配置或快捷方式失效。

### 插件如何存储配置？

参考 `plugins/builtin/campus_settings.py`，使用 `QSettings` 存储普通配置，密码等敏感信息使用 Windows 凭据库。

### 如何调试插件？

1. 运行测试：`python -m pytest tests/test_plugins.py -v`
2. 启动应用：`python -m yyict_toolbox`，在侧边栏查看工具是否出现
3. UI 自动化测试使用 `QT_QPA_PLATFORM=offscreen`
