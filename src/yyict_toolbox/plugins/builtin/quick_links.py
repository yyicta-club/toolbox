import logging

from yyict_toolbox.plugins.specs import ToolDescriptor, hookimpl

QUICK_LINKS_TOOL_ID = "quick-links"


class QuickLinksPlugin:
    """提供常用校园网站的快捷入口。"""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    @hookimpl
    def toolbox_tools(self) -> list[ToolDescriptor]:
        from yyict_toolbox.ui.quick_links_page import QuickLinksPage

        return [
            ToolDescriptor(
                id=QUICK_LINKS_TOOL_ID,
                name="快捷链接面板",
                description="快速访问学校官网、数字校园和教务系统",
                view_factory=lambda: QuickLinksPage(self._logger),
            )
        ]
