import sys

from PySide6.QtWidgets import QApplication

from yyict_toolbox.plugins.manager import create_plugin_manager
from yyict_toolbox.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("校园工具箱")
    app.setOrganizationName("YYICT")

    plugin_manager = create_plugin_manager()
    window = MainWindow(plugin_manager.get_tools())
    window.show()
    return app.exec()
