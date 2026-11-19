from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

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
    view_factory: Callable[[], "QWidget"] | None = None


class ToolboxHookSpec:
    @hookspec
    def toolbox_tools(self) -> list[ToolDescriptor]:
        """Return the tools provided by a plugin."""
