import logging
import os
from datetime import datetime
from pathlib import Path
from queue import Queue

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QSettings, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QSystemTrayIcon

from yyict_toolbox import __version__
from yyict_toolbox.logging_system import (
    SYSTEM_LOGGER_NAME,
    LogEvent,
    configure_logging,
    event_hub,
    plugin_logger_name,
)
from yyict_toolbox.plugins.builtin.campus_settings import (
    CampusSettings,
    CampusSettingsStore,
    CredentialStorageError,
)
from yyict_toolbox.plugins.manager import create_plugin_manager
from yyict_toolbox.ui.campus_network_page import CampusNetworkPage
from yyict_toolbox.ui.main_window import MainWindow
from yyict_toolbox.ui.quick_links_page import QuickLinksPage
from yyict_toolbox.ui.system_logs_page import SystemLogsPage


class FakeCredentialBackend:
    def __init__(self):
        self.passwords = {}

    def get_password(self, service, username):
        return self.passwords.get((service, username))

    def set_password(self, service, username, password):
        self.passwords[(service, username)] = password

    def delete_password(self, service, username):
        self.passwords.pop((service, username), None)


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store(tmp_path):
    return CampusSettingsStore(
        QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat),
        FakeCredentialBackend(),
    )


@pytest.fixture
def window(app, store, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: False)
    event_hub().clear()
    manager = create_plugin_manager(store, Queue(), events=event_hub())
    window = MainWindow(manager.get_tools())
    yield window
    window.shutdown()
    window.wait_for_shutdown()
    window._shutdown_timer.stop()
    window._tray_icon.hide()
    window.hide()
    window.deleteLater()
    app.processEvents()
    event_hub().clear()


@pytest.fixture
def log_page(window, tmp_path):
    """打开运行日志页面，并把统一日志指向临时日志目录。"""
    configure_logging(tmp_path)
    window._tool_buttons['system-logs'].click()
    page = window._pages['system-logs']
    assert isinstance(page, SystemLogsPage)
    return page


def publish(message, level=logging.INFO, logger_name=SYSTEM_LOGGER_NAME):
    event_hub().publish(
        LogEvent(
            timestamp=datetime.now(),
            level=level,
            logger_name=logger_name,
            message=message,
        )
    )


def test_main_window_displays_campus_network_configuration(window):
    page = window._pages['campus-network-login']
    assert isinstance(page, CampusNetworkPage)
    assert page._interval_input.value() == 60
    assert page._carrier_input.count() == 3
    assert page._level_input.count() == 3


@pytest.mark.parametrize('name, url', [
    ('学校官网', 'https://www.jxyy.edu.cn/'),
    ('数字校园', 'https://cas.jxyy.edu.cn/lyuapServer/login'),
    ('教务系统', 'https://jw.jxyy.edu.cn:9002/jwglxt'),
])
def test_quick_links_open_in_default_browser(window, monkeypatch, name, url) -> None:
    opened_urls: list[str] = []

    def open_url(address: QUrl) -> bool:
        opened_urls.append(address.toString())
        return True

    monkeypatch.setattr(QDesktopServices, 'openUrl', open_url)
    window._tool_buttons['quick-links'].click()
    page = window._pages['quick-links']
    assert isinstance(page, QuickLinksPage)
    assert url in [label.text() for label in page.findChildren(QLabel)]
    button = next(button for button in page.findChildren(QPushButton) if button.text() == name)
    button.click()
    assert opened_urls == [url]
    assert page._status_label.text() == ''
    window._tool_buttons['campus-network-login'].click()
    window._tool_buttons['quick-links'].click()
    assert window._pages['quick-links'] is page
    assert page.shutdown() is True
    page.wait_for_shutdown()


def test_quick_links_browser_failure_can_be_retried(window, monkeypatch) -> None:
    monkeypatch.setattr(QDesktopServices, 'openUrl', lambda url: False)
    window._tool_buttons['quick-links'].click()
    page = window._pages['quick-links']
    button = page.findChildren(QPushButton)[0]
    button.click()
    assert '无法打开浏览器' in page._status_label.text()
    monkeypatch.setattr(QDesktopServices, 'openUrl', lambda url: True)
    button.click()
    assert page._status_label.text() == ''


@pytest.mark.parametrize('level, expected', [
    (1, ['错误']), (2, ['警告', '错误']), (3, ['详细', '正常', '警告', '错误']),
])
def test_log_level_filter(window, level, expected):
    page = window._pages['campus-network-login']
    for severity, message in [(logging.DEBUG, '详细'), (logging.INFO, '正常'),
                              (logging.WARNING, '警告'), (logging.ERROR, '错误')]:
        publish(message, severity)
    page._level_input.setCurrentIndex(page._level_input.findData(level))
    page._drain_log_queue()
    content = page._log_view.toPlainText()
    for message in ['详细', '正常', '警告', '错误']:
        assert (message in content) == (message in expected)


def test_campus_page_falls_back_to_record_queue(app, store):
    queue: Queue[logging.LogRecord] = Queue()
    page = CampusNetworkPage(store, queue, logging.getLogger('legacy-test'))
    try:
        queue.put(logging.LogRecord('legacy', logging.ERROR, '', 0, '旧队列事件', (), None))
        page._drain_log_queue()
        assert '旧队列事件' in page._log_view.toPlainText()
    finally:
        page.shutdown()


def test_settings_roundtrip_without_plaintext_password(store, tmp_path):
    settings = CampusSettings('test-user', 'telecom', 120, 2)
    store.save(settings, 'test-password-secret')
    assert store.load() == (settings, 'test-password-secret')
    assert 'test-password-secret' not in (tmp_path / 'settings.ini').read_text()
    store.save(settings, '')
    assert store.load() == (settings, '')


def test_storage_error_does_not_expose_password(store):
    def fail(*args):
        raise RuntimeError('test-password-secret')

    store._credential_backend.set_password = fail
    with pytest.raises(CredentialStorageError) as error:
        store.save(CampusSettings('test-user'), 'test-password-secret')
    assert 'test-password-secret' not in str(error.value)


@pytest.mark.parametrize('settings', [
    CampusSettings(''), CampusSettings('a@cmcc'), CampusSettings('a,b'),
    CampusSettings('a b'), CampusSettings('test', carrier='invalid'),
    CampusSettings('test', probe_interval=0), CampusSettings('test', log_level=4),
])
def test_invalid_settings_rejected(settings, store):
    with pytest.raises(ValueError):
        store.save(settings, 'test-password')


def test_missing_credentials_do_not_start_monitor(window):
    page = window._pages['campus-network-login']
    page._start_monitor()
    assert page._monitor is None
    assert '填写' in page._status_label.text()


def test_close_to_tray_keeps_monitor_page_alive(window, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    events = []
    window.exit_requested.connect(lambda: events.append('exit'))
    window.show()
    window.close()
    assert not window.isVisible()
    assert events == []
    assert window._pages['campus-network-login']._queue_timer.isActive()


def test_exit_waits_asynchronously_for_page_to_stop(window, monkeypatch):
    page = window._pages['campus-network-login']
    stopped = [False]
    monkeypatch.setattr(page, 'shutdown', lambda: stopped[0])
    events = []
    window.exit_requested.connect(lambda: events.append('exit'))
    window._exit_application()
    assert window._shutdown_timer.isActive()
    assert events == []
    stopped[0] = True
    window._complete_exit()
    assert events == ['exit']
    assert not window._shutdown_timer.isActive()


def test_start_stop_monitor_without_duplicate_threads(window, app, monkeypatch):
    import time

    from yyict_toolbox.plugins.builtin.campus_network_service import (
        CampusNetworkClient,
        ProbeResult,
    )

    monkeypatch.setattr(CampusNetworkClient, 'probe', lambda self: ProbeResult(True))
    page = window._pages['campus-network-login']
    page._account_input.setText('test-user')
    page._password_input.setText('test-password')
    page._start_monitor()
    first_monitor = page._monitor
    assert first_monitor is not None
    assert not page._account_input.isEnabled()
    page._start_monitor()
    assert page._monitor is first_monitor
    page._stop_monitor()
    deadline = time.monotonic() + 3
    while page._monitor is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert page._monitor is None
    assert page._start_button.isEnabled()
    assert not page._stop_button.isEnabled()
    assert page._account_input.isEnabled()


def test_main_window_shows_logo_in_window_tray_and_sidebar(window):
    assert not window.windowIcon().isNull()
    logo_label = window.findChild(QLabel, 'brandLogo')
    assert logo_label is not None
    pixmap = logo_label.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert not window._tray_icon.icon().isNull()


def test_text_tip_lifecycle_is_configurable(window, app):
    import time

    window.show()
    tip = window._show_text_tip('提示内容', 50)
    assert tip.text() == '提示内容'
    assert tip.isVisible()
    assert window._tip_timer.isActive()
    assert window._tip_timer.interval() == 50
    deadline = time.monotonic() + 3
    while tip.isVisible() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert not tip.isVisible()

    persistent = window._show_text_tip('常驻提示', 0)
    assert persistent.isVisible()
    assert not window._tip_timer.isActive()
    assert persistent is tip


def test_version_button_shows_package_version(window):
    button = window.findChild(QPushButton, 'versionButton')
    assert button is not None
    assert __version__ in button.text()


def test_update_check_in_source_mode_explains_limit(window, monkeypatch):
    import yyict_toolbox.ui.main_window as main_window

    monkeypatch.setattr(main_window, 'is_frozen_install', lambda: False)
    window._check_updates()
    assert window._tip_label is not None
    assert '源码模式' in window._tip_label.text()
    assert window._update_worker is None


def test_report_update_result_shows_applied_version(window):
    window.report_update_result(('applied', '0.2.0'))
    assert window._tip_label is not None
    assert '0.2.0' in window._tip_label.text()


def _close_modal_dialog(titles):
    modal = QApplication.activeModalWidget()
    if modal is not None:
        titles.append(modal.windowTitle())
        modal.close()


def test_update_available_shows_version_dialog(window):
    from yyict_toolbox.updates import ReleaseManifest, ReleaseSource, UpdateCandidate

    candidate = UpdateCandidate(
        ReleaseSource('test', 'http://example.invalid'),
        ReleaseManifest('0.2.0', '测试说明', '0.0.0', 'app.zip', '0' * 64, 1),
        'http://example.invalid/app.zip',
    )
    titles = []
    QTimer.singleShot(50, lambda: _close_modal_dialog(titles))
    window._on_update_resolved(candidate)
    assert titles == ['发现新版本']


def test_failed_update_result_warns(window):
    titles = []
    QTimer.singleShot(50, lambda: _close_modal_dialog(titles))
    window.report_update_result(('failed', '0.2.0'))
    assert titles == ['更新未完成']


def test_sidebar_contains_log_tool(window):
    assert 'system-logs' in window._tool_buttons
    assert window._tool_buttons['system-logs'].text() == '运行日志'


def test_log_page_source_and_level_filters(log_page):
    publish('系统信息事件')
    publish('插件警告事件', logging.WARNING, plugin_logger_name('quick-links'))
    publish('插件错误事件', logging.ERROR, plugin_logger_name('quick-links'))
    log_page.drain_events()
    content = log_page._view.toPlainText()
    assert '系统信息事件' in content
    assert '插件警告事件' in content
    assert '插件错误事件' in content
    assert '[快捷链接面板]' in content

    log_page._source_input.setCurrentIndex(
        log_page._source_input.findData('quick-links')
    )
    content = log_page._view.toPlainText()
    assert '系统信息事件' not in content
    assert '插件错误事件' in content

    log_page._source_input.setCurrentIndex(0)
    log_page._level_input.setCurrentIndex(log_page._level_input.findData(logging.WARNING))
    content = log_page._view.toPlainText()
    assert '系统信息事件' not in content
    assert '插件警告事件' in content
    assert '插件错误事件' in content


def test_log_page_shows_unknown_plugin_source_as_stable_id(log_page):
    publish('未知插件事件', logging.INFO, plugin_logger_name('not-installed-tool'))
    log_page.drain_events()
    assert '[not-installed-tool]' in log_page._view.toPlainText()


def test_log_page_refresh_reads_persisted_history(log_page):
    logging.getLogger(SYSTEM_LOGGER_NAME).info('写入文件的事件')
    log_page._refresh_button.click()
    content = log_page._view.toPlainText()
    assert '写入文件的事件' in content


def test_log_page_clear_only_clears_display(log_page, tmp_path):
    logging.getLogger(SYSTEM_LOGGER_NAME).info('清空前的事件')
    log_page.drain_events()
    assert '清空前的事件' in log_page._view.toPlainText()
    log_page._clear_button.click()
    assert log_page._view.toPlainText() == ''
    log_file = tmp_path / 'log/toolbox.log'
    assert '清空前的事件' in log_file.read_text(encoding='utf-8')


def test_log_page_open_log_file_action(log_page, tmp_path, monkeypatch):
    opened: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, 'openUrl', lambda url: bool(opened.append(url)))
    log_page._open_button.click()
    assert opened
    assert Path(opened[0].toLocalFile()) == tmp_path / 'log/toolbox.log'
    assert (tmp_path / 'log/toolbox.log').exists()


def test_campus_page_receives_same_log_stream(window, log_page):
    campus_page = window._pages['campus-network-login']
    publish('统一日志事件')
    campus_page._drain_log_queue()
    log_page.drain_events()
    assert '统一日志事件' in campus_page._log_view.toPlainText()
    assert '统一日志事件' in log_page._view.toPlainText()


def test_log_page_unsubscribes_on_shutdown(log_page):
    assert log_page.shutdown() is True
    publish('关闭后的事件')
    log_page.drain_events()
    assert '关闭后的事件' not in log_page._view.toPlainText()
