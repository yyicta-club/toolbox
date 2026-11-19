import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from yyict_toolbox.plugins.manager import create_plugin_manager
from yyict_toolbox.ui.main_window import MainWindow


def test_main_window_shows_registered_placeholder_tool() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(create_plugin_manager().get_tools())

    assert window.windowTitle() == "校园工具箱"
    assert window._title_label.text() == "校园网自动登录"
    assert window._state_label.text() == "测试"

    window.close()
    app.processEvents()
