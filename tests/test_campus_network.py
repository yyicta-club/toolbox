import logging
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pytest

from yyict_toolbox.plugins.builtin.campus_network_service import (
    PROBE_URLS,
    CampusNetworkClient,
    CampusNetworkMonitor,
    LoginResult,
    ProbeResult,
)
from yyict_toolbox.plugins.builtin.campus_settings import CampusSettings


class FakeResponse:
    def __init__(self, code=200, payload=b'', location=''):
        self.code = code
        self.payload = payload
        self.headers = {'Location': location}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size):
        return self.payload[:size]


def client_with_responses(monkeypatch, responses):
    client = CampusNetworkClient()
    requests = []
    replies = iter(responses)

    def open_request(request, timeout):
        requests.append(request)
        assert timeout == 8
        response = next(replies)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(client._opener, 'open', open_request)
    return client, requests


def test_probe_accepts_only_expected_content_and_uses_fallback(monkeypatch):
    client, requests = client_with_responses(monkeypatch, [
        FakeResponse(200, b'<html>login</html>'),
        FakeResponse(200, b'Microsoft Connect Test'),
    ])
    assert client.probe() == ProbeResult(True)
    assert len(requests) == 2


def test_probe_accepts_empty_204(monkeypatch):
    client, requests = client_with_responses(monkeypatch, [FakeResponse(204)])
    assert client.probe().online
    assert len(requests) == 1


def test_probe_extracts_ip_from_redirect_without_following_it(monkeypatch):
    redirect = 'http://192.168.40.2/a79.htm?wlanuserip=10.0.0.8&wlanacname=test-ac'
    error = HTTPError(PROBE_URLS[0][0], 302, 'redirect', {'Location': redirect}, BytesIO())
    client, requests = client_with_responses(monkeypatch, [error, URLError('timeout')])
    assert client.probe() == ProbeResult(False, '10.0.0.8', 'test-ac')
    assert len(requests) == 2


@pytest.mark.parametrize('url', [
    'http://example.com/?wlanuserip=10.0.0.8',
    'http://192.168.40.2/?wlanuserip=invalid',
    'http://192.168.40.2/?wlanuserip=::1',
])
def test_untrusted_or_invalid_portal_context_rejected(url):
    assert CampusNetworkClient._portal_context(url).user_ip is None


@pytest.mark.parametrize('carrier', ['cmcc', 'unicom', 'telecom'])
def test_login_encodes_provider_password_and_current_ip(monkeypatch, carrier):
    client, requests = client_with_responses(monkeypatch, [
        FakeResponse(payload=b'dr1003({"result":1});'),
    ])
    result = client.login(CampusSettings(account='test-user', carrier=carrier),
                          'p&+?#密码', '10.0.0.8', 'test-ac')
    query = parse_qs(urlparse(requests[0].full_url).query, keep_blank_values=True)
    assert result.success
    assert query['user_account'] == [f',0,test-user@{carrier}']
    assert query['user_password'] == ['p&+?#密码']
    assert query['wlan_user_ip'] == ['10.0.0.8']
    assert query['wlan_ac_name'] == ['test-ac']
    assert query['v'] == [{'cmcc': '4571', 'unicom': '3270', 'telecom': '7451'}[carrier]]
    assert query['wlan_user_mac'] == ['000000000000']
    assert query['lang'] == ['zh-cn', 'zh']
    assert requests[0].headers['Referer'] == 'http://192.168.40.2/'


def test_login_reads_dynamic_ip_from_page_when_probe_times_out(monkeypatch):
    client, requests = client_with_responses(monkeypatch, [
        FakeResponse(payload=b"v46ip='10.0.0.9    ';"),
        FakeResponse(payload=b'dr1003({"result":"1"});'),
    ])
    assert client.login(CampusSettings(account='test-user'), 'fake-password', None).success
    assert parse_qs(urlparse(requests[-1].full_url).query)['wlan_user_ip'] == ['10.0.0.9']


def test_no_ip_does_not_submit_credentials(monkeypatch):
    client, requests = client_with_responses(monkeypatch, [FakeResponse(payload=b'no context')])
    assert not client.login(CampusSettings(account='test-user'), 'fake-password', None).success
    assert len(requests) == 1
    assert 'user_password' not in requests[0].full_url


@pytest.mark.parametrize('payload', ['[]', '<html>error</html>', 'dr1003({bad});',
                                    'other({"result":1});', 'dr1003({"result":0});'])
def test_malformed_or_rejected_response_is_failure(payload):
    assert not CampusNetworkClient._parse_login_response(payload).success


def test_login_redirect_is_failure(monkeypatch):
    client, requests = client_with_responses(monkeypatch, [
        FakeResponse(302, location='http://example.com/'),
    ])
    assert not client.login(CampusSettings(account='test-user'), 'fake-password', '10.0.0.8').success
    assert len(requests) == 1


class ScriptedClient:
    def __init__(self, probes=None, logins=None):
        self.probes = iter(probes or [])
        self.logins = iter(logins or [])
        self.login_count = 0

    def probe(self):
        return ProbeResult(next(self.probes, False), '10.0.0.8')

    def login(self, *args):
        self.login_count += 1
        return LoginResult(next(self.logins, False), '测试响应')


def make_monitor(client):
    return CampusNetworkMonitor(CampusSettings(account='test-user', probe_interval=0),
                                'fake-password', logging.getLogger('monitor-test'), client)


def test_monitor_stops_after_four_failures(caplog):
    client = ScriptedClient()
    monitor = make_monitor(client)
    with caplog.at_level(logging.INFO):
        monitor.run()
    assert client.login_count == 4
    assert '超过 3 次' in caplog.text
    assert 'fake-password' not in caplog.text
    assert 'test-user' not in caplog.text
    assert monitor._password == ''


def test_success_followed_by_online_resets_failure_counter():
    client = ScriptedClient(probes=[False, False, False, True], logins=[False, False, True])
    make_monitor(client).run()
    assert client.login_count == 7


def test_false_success_does_not_reset_counter():
    client = ScriptedClient(logins=[True] * 4)
    make_monitor(client).run()
    assert client.login_count == 4


def test_stop_during_probe_does_not_start_login():
    client = ScriptedClient()
    monitor = make_monitor(client)

    def probe_and_stop():
        monitor.stop()
        return ProbeResult(False, '10.0.0.8')

    client.probe = probe_and_stop
    monitor.run()
    assert client.login_count == 0


def test_unexpected_exception_is_sanitized(caplog):
    client = ScriptedClient()

    def broken_probe():
        raise RuntimeError('user_password=fake-password')

    client.probe = broken_probe
    make_monitor(client).run()
    assert 'RuntimeError' in caplog.text
    assert 'fake-password' not in caplog.text


def test_stop_interrupts_interval_wait():
    import threading

    entered = threading.Event()
    client = ScriptedClient()

    def online_probe():
        entered.set()
        return ProbeResult(True)

    client.probe = online_probe
    monitor = CampusNetworkMonitor(CampusSettings(), 'fake-password',
                                   logging.getLogger('monitor-test'), client)
    monitor.start()
    try:
        assert entered.wait(2)
        monitor.stop()
        assert monitor.wait(1000)
        assert client.login_count == 0
    finally:
        monitor.stop()
        monitor.wait()


def test_actual_http_redirect_does_not_forward_request():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(302)
            self.send_header('Location', '/unexpected')
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, _ = CampusNetworkClient()._get(
            f'http://127.0.0.1:{server.server_port}/login?user_password=fake', login=True,
        )
        assert status == 302
        assert seen == ['/login?user_password=fake']
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
