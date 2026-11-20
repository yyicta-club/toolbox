import logging
from queue import Queue

from yyict_toolbox.logging_system import LogEventHub
from yyict_toolbox.plugins.builtin.campus_settings import CampusSettingsStore
from yyict_toolbox.plugins.specs import ToolDescriptor, hookimpl

CAMPUS_NETWORK_TOOL_ID = "campus-network-login"


class CampusNetworkPlugin:
    def __init__(
        self,
        settings_store: CampusSettingsStore,
        log_queue: Queue[logging.LogRecord],
        logger: logging.Logger,
        events: LogEventHub | None = None,
    ) -> None:
        self._settings_store = settings_store
        self._log_queue = log_queue
        self._logger = logger
        self._events = events

    @hookimpl
    def toolbox_tools(self) -> list[ToolDescriptor]:
        from yyict_toolbox.ui.campus_network_page import CampusNetworkPage

        return [
            ToolDescriptor(
                id=CAMPUS_NETWORK_TOOL_ID,
                name="校园网自动登录",
                description="校园网络连接工具",
                available=True,
                view_factory=lambda: CampusNetworkPage(
                    self._settings_store,
                    self._log_queue,
                    self._logger,
                    self._events,
                ),
            )
        ]
