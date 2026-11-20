import logging
import sys

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from yyict_toolbox.logging_system import configure_logging
from yyict_toolbox.plugins.builtin.campus_settings import CampusSettingsStore
from yyict_toolbox.plugins.manager import create_plugin_manager
from yyict_toolbox.resources import logo_path
from yyict_toolbox.single_instance import SingleInstanceGuard, default_lock_path
from yyict_toolbox.ui.main_window import MainWindow
from yyict_toolbox.updates import consume_update_result, install_directory


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("校园工具箱")
    app.setOrganizationName("YYICT")
    app.setWindowIcon(QIcon(str(logo_path())))
    app.setFont(QFont("Microsoft YaHei UI", 10))

    guard = SingleInstanceGuard(default_lock_path())
    if not guard.acquire():
        QMessageBox.warning(
            None,
            "重复启动",
            "校园工具箱已在运行中，请勿重复启动。\n如未看到主窗口，请检查系统托盘。",
        )
        return 1
    try:
        return _run_application(app)
    finally:
        guard.release()


def _run_application(app: QApplication) -> int:
    try:
        log_queue = configure_logging(install_directory())
    except OSError:
        QMessageBox.critical(None, "日志初始化失败", "无法写入应用目录，请将软件放在可写目录中。")
        return 1
    logger = logging.getLogger("yyict_toolbox")
    update_result = consume_update_result()
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
    if update_result is not None:
        logger.info("上次更新结果：%s %s", update_result[0], update_result[1])
    window.report_update_result(update_result)
    try:
        return app.exec()
    finally:
        window.wait_for_shutdown()
        logger.info("工具箱已退出")
        logging.shutdown()
