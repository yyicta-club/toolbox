from yyict_toolbox.plugins.manager import create_plugin_manager


def test_builtin_campus_network_plugin_is_registered() -> None:
    tools = create_plugin_manager().get_tools()

    assert len(tools) == 1
    assert tools[0].id == "campus-network-login"
    assert tools[0].name == "校园网自动登录"
    assert tools[0].available is True
    assert tools[0].view_factory is not None
