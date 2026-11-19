import pluggy

from yyict_toolbox.plugins.builtin.campus_network import CampusNetworkPlugin
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


def create_plugin_manager() -> PluginManager:
    manager = PluginManager()
    manager.register(CampusNetworkPlugin())
    return manager
