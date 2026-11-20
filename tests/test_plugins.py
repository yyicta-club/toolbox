from yyict_toolbox.plugins.manager import create_plugin_manager


def test_builtin_campus_network_plugin_is_registered() -> None:
    tools = create_plugin_manager().get_tools()

    assert len(tools) == 2
    campus_tools = [t for t in tools if t.id == "campus-network-login"]
    assert len(campus_tools) == 1
    assert campus_tools[0].name == "校园网自动登录"
    assert campus_tools[0].available is True
    assert campus_tools[0].view_factory is not None


def test_demo_hello_plugin_is_registered() -> None:
    tools = create_plugin_manager().get_tools()

    demo_tools = [t for t in tools if t.id == "demo-hello"]
    assert len(demo_tools) == 1
    assert demo_tools[0].name == "插件开发示例"
    assert demo_tools[0].available is True
    assert demo_tools[0].view_factory is not None
