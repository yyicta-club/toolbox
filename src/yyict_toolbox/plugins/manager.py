import logging
from queue import Queue

import pluggy

from yyict_toolbox.logging_system import LogEventHub, event_hub, plugin_logger_name
from yyict_toolbox.plugins.builtin.campus_network import (
    CAMPUS_NETWORK_TOOL_ID,
    CampusNetworkPlugin,
)
from yyict_toolbox.plugins.builtin.campus_settings import CampusSettingsStore
# from yyict_toolbox.plugins.builtin.demo_hello import DemoHelloPlugin
from yyict_toolbox.plugins.builtin.quick_links import QUICK_LINKS_TOOL_ID, QuickLinksPlugin
from yyict_toolbox.plugins.builtin.system_logs import SystemLogsPlugin
from yyict_toolbox.plugins.specs import PROJECT_NAME, ToolboxHookSpec, ToolDescriptor


class PluginManager:
    def __init__(self) -> None:
        self._manager = pluggy.PluginManager(PROJECT_NAME)
        self._manager.add_hookspecs(ToolboxHookSpec)

    def register(self, plugin: object, name: str | None = None) -> str | None:
        return self._manager.register(plugin, name=name)

    def get_tools(self) -> list[ToolDescriptor]:
        results = self._manager.hook.toolbox_tools()
        return [tool for plugin_tools in results for tool in plugin_tools]


def create_plugin_manager(
    settings_store: CampusSettingsStore | None = None,
    log_queue: Queue[logging.LogRecord] | None = None,
    *,
    events: LogEventHub | None = None,
) -> PluginManager:
    """注册内置插件。

    ``log_queue`` 保留兼容注入：仍按原始日志记录消费的组件可以继续使用它；
    ``events`` 是统一日志事件中心，日志页面通过它订阅实时事件。
    """
    manager = PluginManager()
    hub = events if events is not None else event_hub()
    # 注册内置插件
    # manager.register(DemoHelloPlugin())
    # pluggy 后注册的插件先返回工具，侧栏顺序与注册顺序相反；日志模块排在最后。
    manager.register(SystemLogsPlugin(hub, lambda: manager.get_tools()))
    manager.register(
        QuickLinksPlugin(logging.getLogger(plugin_logger_name(QUICK_LINKS_TOOL_ID)))
    )
    manager.register(
        CampusNetworkPlugin(
            settings_store or CampusSettingsStore(),
            log_queue or Queue(),
            logging.getLogger(plugin_logger_name(CAMPUS_NETWORK_TOOL_ID)),
            hub,
        )
    )
    return manager
