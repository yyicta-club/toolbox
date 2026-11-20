import logging
import sys
from pathlib import Path

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from yyict_toolbox.logging_system import configure_logging
from yyict_toolbox.plugins.builtin.campus_settings import CampusSettingsStore
from yyict_toolbox.plugins.manager import create_plugin_manager
from yyict_toolbox.resources import logo_path
from yyict_toolbox.ui.main_window import MainWindow


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("校园工具箱")
    app.setOrganizationName("YYICT")
    app.setWindowIcon(QIcon(str(logo_path())))
    app.setFont(QFont("Microsoft YaHei UI", 10))

    try:
        log_queue = configure_logging(application_directory())
    except OSError:
        QMessageBox.critical(None, "日志初始化失败", "无法写入应用目录，请将软件放在可写目录中。")
        return 1
    logger = logging.getLogger("yyict_toolbox")
    plugin_manager = create_plugin_manager(
        CampusSettingsStore(),
        log_queue,
        logger,
    )
    window = MainWindow(plugin_manager.get_tools())
    if window.tray_available:
        app.setQuitOnLastWindowClosed(False)
    window.exit_requested.connect(app.quit)
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    logger.info("工具箱已启动")
    try:
        return app.exec()
    finally:
        window.wait_for_shutdown()
        logger.info("工具箱已退出")
        logging.shutdown()
