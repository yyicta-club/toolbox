from dataclasses import dataclass

import pluggy


PROJECT_NAME = "yyict_toolbox"
hookspec = pluggy.HookspecMarker(PROJECT_NAME)
hookimpl = pluggy.HookimplMarker(PROJECT_NAME)


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    """Display metadata exposed by a toolbox plugin."""

    id: str
    name: str
    description: str
    available: bool = True


class ToolboxHookSpec:
    @hookspec
    def toolbox_tools(self) -> list[ToolDescriptor]:
        """Return the tools provided by a plugin."""
