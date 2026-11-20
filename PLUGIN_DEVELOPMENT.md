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
from yyict_toolbox.logging_system import plugin_logger_name
from yyict_toolbox.plugins.builtin.my_plugin import MyPlugin

def create_plugin_manager(...) -> PluginManager:
    manager = PluginManager()
    manager.register(MyPlugin(logging.getLogger(plugin_logger_name("my-tool-id"))))
    return manager
```

**注册规范**：
- 所有插件通过 pluggy Hook 规范接入，禁止绕过管理器让 UI 直接实例化插件
- 只注册随应用分发的内置插件，不扫描外部插件目录
- pluggy 后注册的插件先返回工具，侧栏顺序与注册顺序相反

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

## 插件日志

插件日志统一走 `logging_system` 的事件中心，侧栏「运行日志」页面按插件分组展示。

### logger 命名

插件 logger 名称固定为 `yyict_toolbox.plugin.<稳定工具 ID>`，工具 ID 与 `ToolDescriptor.id` 一致：

```python
from yyict_toolbox.logging_system import plugin_logger_name

logger = logging.getLogger(plugin_logger_name("my-tool-id"))
# yyict_toolbox.plugin.my-tool-id
```

工具 ID 必须稳定：改名会让历史日志失去归属。系统日志使用 `yyict_toolbox.system`，版本更新日志使用 `yyict_toolbox.update`，两者都不是插件来源，会归到「系统日志」。

### 在插件中使用 logger

logger 由插件管理器注入，页面需要时继续向下传递：

```python
class MyPlugin:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    @hookimpl
    def toolbox_tools(self) -> list[ToolDescriptor]:
        from yyict_toolbox.ui.my_page import MyPage

        return [
            ToolDescriptor(
                id="my-tool-id",
                name="我的工具",
                description="工具描述",
                view_factory=lambda: MyPage(self._logger),
            )
        ]
```

### 日志内容约束

- 只记录状态、结果和错误类型；不写密码、令牌、认证请求地址或响应原文
- 异常只写 `type(error).__name__`，不要写异常文本和回溯

### 订阅统一日志流

页面需要自己展示日志时，订阅事件中心并在关闭时取消订阅：

```python
from yyict_toolbox.logging_system import LogEvent, LogEventHub

class MyPage(QWidget):
    def __init__(self, events: LogEventHub) -> None:
        super().__init__()
        self._events = events
        self._subscription = events.subscribe()

    def shutdown(self) -> bool:
        self._events.unsubscribe(self._subscription)
        return True
```

事件中心会把同一条日志分发给所有订阅者，因此多个页面可以同时收到同一批事件；订阅队列有界，满了会丢弃最旧事件，页面始终能拿到最新日志。

## 示例文件清单

| 文件 | 作用 |
|------|------|
| `src/yyict_toolbox/plugins/specs.py` | Hook 规范定义（`ToolDescriptor`、`ToolboxHookSpec`） |
| `src/yyict_toolbox/plugins/builtin/demo_hello.py` | 示例插件类 `DemoHelloPlugin` |
| `src/yyict_toolbox/ui/demo_hello_page.py` | 示例 UI 页面 `DemoHelloPage` |
| `src/yyict_toolbox/plugins/builtin/system_logs.py` | 运行日志页面插件（工具 ID `system-logs`） |
| `src/yyict_toolbox/ui/system_logs_page.py` | 统一日志页面（来源、等级筛选与实时追加） |
| `src/yyict_toolbox/logging_system.py` | 日志事件模型、事件中心与文件日志配置 |
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

不建议。工具 ID 应保持稳定，修改可能导致配置、快捷方式或日志归属失效。

### 插件如何存储配置？

参考 `plugins/builtin/campus_settings.py`，使用 `QSettings` 存储普通配置，密码等敏感信息使用 Windows 凭据库。

### 如何调试插件？

1. 运行测试：`python -m pytest tests/test_plugins.py -v`
2. 启动应用：`python -m yyict_toolbox`，在侧边栏查看工具是否出现
3. 在「运行日志」页面按来源筛选查看本插件的事件
4. UI 自动化测试使用 `QT_QPA_PLATFORM=offscreen`
