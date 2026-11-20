import logging
from queue import Queue

import pluggy

from yyict_toolbox.plugins.builtin.campus_network import CampusNetworkPlugin
from yyict_toolbox.plugins.builtin.campus_settings import CampusSettingsStore
from yyict_toolbox.plugins.builtin.demo_hello import DemoHelloPlugin
from yyict_toolbox.plugins.builtin.quick_links import QuickLinksPlugin
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
    logger: logging.Logger | None = None,
) -> PluginManager:
    manager = PluginManager()
    # 注册内置插件
    manager.register(DemoHelloPlugin())
    manager.register(QuickLinksPlugin())
    manager.register(
        CampusNetworkPlugin(
            settings_store or CampusSettingsStore(),
            log_queue or Queue(),
            logger or logging.getLogger("yyict_toolbox"),
        )
    )
    return manager
