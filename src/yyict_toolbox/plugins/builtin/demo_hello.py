"""插件开发示例：展示如何实现 Hook 接口并注册工具。

本模块是最小可运行的插件模板，演示：
1. 实现 `toolbox_tools` Hook 返回 `ToolDescriptor`
2. 工具 ID、名称、描述的命名规范
3. `view_factory` 延迟导入 UI 页面（避免循环导入）

学习者可复制本文件作为新插件的起点。
"""

from yyict_toolbox.plugins.specs import ToolDescriptor, hookimpl


class DemoHelloPlugin:
    """示例插件：提供一个简单的问候页面。

    插件类无需继承基类，只需实现 `toolbox_tools` Hook 即可接入。
    """

    @hookimpl
    def toolbox_tools(self) -> list[ToolDescriptor]:
        """返回本插件提供的工具列表。

        返回的 ToolDescriptor 必须是不可变元数据。
        view_factory 在 MainWindow 懒加载时才被调用，因此可延迟导入 UI。
        """
        from yyict_toolbox.ui.demo_hello_page import DemoHelloPage

        return [
            ToolDescriptor(
                id="demo-hello",
                name="插件开发示例",
                description="Hello World 级别的插件模板，适合学习插件接入流程",
                available=True,
                view_factory=DemoHelloPage,
            )
        ]
