"""统一日志页面插件。

页面本身不直接实例化业务，只订阅日志事件中心并展示系统、插件与更新日志。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from yyict_toolbox.logging_system import LogEventHub
from yyict_toolbox.plugins.specs import ToolDescriptor, hookimpl

SYSTEM_LOGS_TOOL_ID = "system-logs"


class SystemLogsPlugin:
    """提供统一的运行日志页面。

    tools_provider 返回当前已注册的工具清单，页面据此把稳定的插件 ID
    映射为中文展示名称。
    """

    def __init__(
        self,
        events: LogEventHub,
        tools_provider: Callable[[], Sequence[ToolDescriptor]],
    ) -> None:
        self._events = events
        self._tools_provider = tools_provider

    @hookimpl
    def toolbox_tools(self) -> list[ToolDescriptor]:
        from yyict_toolbox.ui.system_logs_page import SystemLogsPage

        return [
            ToolDescriptor(
                id=SYSTEM_LOGS_TOOL_ID,
                name="运行日志",
                description="统一查看系统、插件与版本更新日志",
                available=True,
                view_factory=lambda: SystemLogsPage(self._events, self._tools_provider),
            )
        ]
