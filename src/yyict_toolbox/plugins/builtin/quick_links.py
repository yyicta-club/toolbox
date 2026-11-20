from yyict_toolbox.plugins.specs import ToolDescriptor, hookimpl


class QuickLinksPlugin:
    """提供常用校园网站的快捷入口。"""

    @hookimpl
    def toolbox_tools(self) -> list[ToolDescriptor]:
        from yyict_toolbox.ui.quick_links_page import QuickLinksPage

        return [
            ToolDescriptor(
                id="quick-links",
                name="快捷链接面板",
                description="快速访问学校官网、数字校园和教务系统",
                view_factory=QuickLinksPage,
            )
        ]
