from yyict_toolbox.plugins.specs import ToolDescriptor, hookimpl


class CampusNetworkPlugin:
    @hookimpl
    def toolbox_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                id="campus-network-login",
                name="校园网自动登录",
                description="校园网络连接工具",
                available=False,
            )
        ]
