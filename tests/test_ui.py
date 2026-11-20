import logging
import os
from queue import Queue

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel, QSystemTrayIcon

from yyict_toolbox.plugins.builtin.campus_settings import (
    CampusSettings,
    CampusSettingsStore,
    CredentialStorageError,
)
from yyict_toolbox.plugins.manager import create_plugin_manager
from yyict_toolbox.ui.campus_network_page import CampusNetworkPage
from yyict_toolbox.ui.main_window import MainWindow


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
    manager = create_plugin_manager(store, Queue(), logging.getLogger('test-ui'))
    window = MainWindow(manager.get_tools())
    yield window
    window.shutdown()
    window.wait_for_shutdown()
    window._shutdown_timer.stop()
    window._tray_icon.hide()
    window.hide()
    window.deleteLater()
    app.processEvents()


def test_main_window_displays_campus_network_configuration(window):
    page = window._pages['campus-network-login']
    assert isinstance(page, CampusNetworkPage)
    assert page._interval_input.value() == 60
    assert page._carrier_input.count() == 3
    assert page._level_input.count() == 3


@pytest.mark.parametrize('level, expected', [
    (1, ['错误']), (2, ['警告', '错误']), (3, ['详细', '正常', '警告', '错误']),
])
def test_log_level_filter(window, level, expected):
    page = window._pages['campus-network-login']
    for severity, message in [(logging.DEBUG, '详细'), (logging.INFO, '正常'),
                              (logging.WARNING, '警告'), (logging.ERROR, '错误')]:
        page._log_queue.put(logging.LogRecord('test', severity, '', 0, message, (), None))
    page._level_input.setCurrentIndex(page._level_input.findData(level))
    page._drain_log_queue()
    content = page._log_view.toPlainText()
    for message in ['详细', '正常', '警告', '错误']:
        assert (message in content) == (message in expected)


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
