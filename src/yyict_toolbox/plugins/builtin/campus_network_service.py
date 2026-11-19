import ipaddress
import json
import logging
import re
import threading
from dataclasses import dataclass
from email.message import Message
from http.client import HTTPException, HTTPResponse
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from PySide6.QtCore import QThread, Signal

from yyict_toolbox.plugins.builtin.campus_settings import CampusSettings

PORTAL_HOST = "192.168.40.2"
PORTAL_URL = f"http://{PORTAL_HOST}/a79.htm"
PROBE_URLS = (
    ("http://connect.rom.miui.com/generate_204", 204, b""),
    ("http://www.msftconnecttest.com/connecttest.txt", 200, b"Microsoft Connect Test"),
)
REQUEST_TIMEOUT = 8
MAX_LOGIN_FAILURES = 3
USER_AGENT = "YYICT-Toolbox/0.1 (Windows)"
PROVIDER_VERSIONS = {"cmcc": "4571", "unicom": "3270", "telecom": "7451"}
NETWORK_ERRORS = (URLError, TimeoutError, OSError, HTTPException, ValueError)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    online: bool
    user_ip: str | None = None
    ac_name: str = ""


@dataclass(frozen=True, slots=True)
class LoginResult:
    success: bool
    reason: str


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: HTTPResponse, code: int, msg: str,
        headers: Message, newurl: str,
    ) -> None:
        # 认证 URL 带密码，不能跟随门户的任意重定向。
        return None


class CampusNetworkClient:
    """固定校园门户协议；不记录请求 URL 或服务器返回的原文。"""

    def __init__(self, timeout: int = REQUEST_TIMEOUT) -> None:
        self._timeout = timeout
        # 内网认证和直连探针不经系统代理，避免代理在线掩盖校园网离线。
        self._opener = build_opener(ProxyHandler({}), NoRedirect())

    def _get(self, url: str, *, login: bool = False) -> tuple[int, str, bytes]:
        headers = {"User-Agent": USER_AGENT, "Cache-Control": "no-cache"}
        if login:
            headers.update({"Accept": "*/*", "Referer": f"http://{PORTAL_HOST}/"})
        request = Request(url, headers=headers)
        try:
            response = self._opener.open(request, timeout=self._timeout)
        except HTTPError as error:
            response = error
        with response:
            # 有限读取避免误返回下载文件时占用无限内存。
            body = response.read(65537)
            location = urljoin(url, response.headers.get("Location", ""))
            return response.code, location, body

    def probe(self) -> ProbeResult:
        portal = ProbeResult(False)
        for url, expected_status, expected_body in PROBE_URLS:
            try:
                status, location, body = self._get(url)
            except NETWORK_ERRORS:
                continue
            if status == expected_status and body == expected_body:
                return ProbeResult(True)
            if status in (301, 302, 303, 307, 308):
                candidate = self._portal_context(location)
                if candidate.user_ip:
                    portal = candidate
        return portal

    def login(
        self, settings: CampusSettings, password: str, user_ip: str | None,
        ac_name: str = "",
    ) -> LoginResult:
        try:
            if user_ip is None:
                status, location, body = self._get(PORTAL_URL)
                context = self._portal_context(location)
                user_ip, ac_name = context.user_ip, context.ac_name
                if not user_ip and status == 200:
                    # 页面变量只作为文本读取，绝不执行页面脚本。
                    page = body.decode("gb18030", errors="replace")
                    match = re.search(r"\b(?:v46ip|ss5)\s*=\s*['\"]([\d.]+)\s*['\"]", page)
                    user_ip = match[1] if match else None
            if user_ip is None:
                return LoginResult(False, "未从校园门户获得设备 IP")
            ipaddress.IPv4Address(user_ip)
            settings.validate()
            version = PROVIDER_VERSIONS[settings.carrier]
            parameters = [
                ("callback", "dr1003"), ("login_method", "1"),
                ("user_account", f",0,{settings.account}@{settings.carrier}"),
                ("user_password", password), ("wlan_user_ip", user_ip),
                ("wlan_user_ipv6", ""), ("wlan_user_mac", "000000000000"),
                ("wlan_ac_ip", ""), ("wlan_ac_name", ac_name),
                ("jsVersion", "4.2"), ("terminal_type", "1"),
                ("lang", "zh-cn"), ("v", version),
                ("lang", "zh"),
            ]
            url = f"http://{PORTAL_HOST}:801/eportal/portal/login?{urlencode(parameters)}"
            status, _, body = self._get(url, login=True)
            if status != 200:
                return LoginResult(False, f"认证服务器返回 HTTP {status}")
            return self._parse_login_response(body.decode("utf-8", errors="replace"))
        except NETWORK_ERRORS:
            return LoginResult(False, "认证请求失败或设备 IP 无效")

    @staticmethod
    def _portal_context(url: str) -> ProbeResult:
        parsed = urlparse(url)
        if parsed.hostname != PORTAL_HOST:
            return ProbeResult(False)
        query = parse_qs(parsed.query)
        candidate = query.get("wlanuserip", [None])[0]
        try:
            if candidate:
                return ProbeResult(
                    False, str(ipaddress.IPv4Address(candidate)),
                    query.get("wlanacname", [""])[0],
                )
        except ipaddress.AddressValueError:
            pass
        return ProbeResult(False)

    @staticmethod
    def _parse_login_response(payload: str) -> LoginResult:
        text = payload.strip()
        if text.startswith("dr1003("):
            match = re.fullmatch(r"dr1003\((.*)\)\s*;?", text, flags=re.DOTALL)
            if not match:
                return LoginResult(False, "认证服务器响应格式无效")
            text = match[1]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return LoginResult(False, "认证服务器响应格式无效")
        if not isinstance(data, dict):
            return LoginResult(False, "认证服务器响应格式无效")
        if data.get("result") in (1, "1"):
            return LoginResult(True, "认证成功")
        return LoginResult(False, "认证未通过，请检查账号、密码及运营商")


class CampusNetworkMonitor(QThread):
    status_changed = Signal(str)

    def __init__(
        self, settings: CampusSettings, password: str, logger: logging.Logger,
        client: CampusNetworkClient | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._password = password
        self._logger = logger
        self._client = client or CampusNetworkClient()
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def _probe(self) -> ProbeResult:
        self._logger.info("网络探针：开始检查互联网连接")
        result = self._client.probe()
        if result.online:
            self._logger.info("网络探针：互联网连接正常")
        else:
            self._logger.warning("网络探针：无法访问互联网")
        return result

    def run(self) -> None:
        failures = 0
        final_status = "监控已停止"
        self._logger.info("监控已启动，探针间隔 %d 秒", self._settings.probe_interval)
        try:
            while not self._stop_event.is_set():
                self.status_changed.emit("正在检查网络")
                probe = self._probe()
                if self._stop_event.is_set():
                    break
                if probe.online:
                    failures = 0
                    self.status_changed.emit("网络正常，等待下一次探针")
                else:
                    self.status_changed.emit("正在登录校园网")
                    self._logger.info("校园网登录：开始第 %d 次尝试", failures + 1)
                    result = self._client.login(
                        self._settings, self._password, probe.user_ip, probe.ac_name,
                    )
                    if self._stop_event.is_set():
                        self._logger.info("校园网登录：请求已结束，监控停止，不再重试")
                        break
                    self._logger.info("校园网登录：%s", result.reason)
                    # 门户接受认证不等于互联网已恢复，重新探测后才能重置计数。
                    verified = self._probe().online if result.success else False
                    if self._stop_event.is_set():
                        break
                    if verified:
                        failures = 0
                        self._logger.info("校园网登录成功，互联网连接已恢复")
                        self.status_changed.emit("登录成功，等待下一次探针")
                    else:
                        failures += 1
                        reason = "认证后网络仍不可用" if result.success else result.reason
                        self._logger.error("校园网登录失败（连续 %d 次）：%s", failures, reason)
                        self.status_changed.emit(f"登录失败（连续 {failures} 次），等待重试")
                        if failures > MAX_LOGIN_FAILURES:
                            final_status = "连续登录失败超过 3 次，已自动停止"
                            self._logger.error(final_status)
                            break
                if self._stop_event.wait(self._settings.probe_interval):
                    break
        except Exception as error:  # noqa: BLE001 -- 线程边界必须停止并隐藏异常中的凭据。
            # 不写异常文本/回溯，第三方异常可能携带带凭据的完整 URL。
            self._logger.error("监控异常，已停止（%s）", type(error).__name__)
            final_status = "监控异常，已停止"
        finally:
            self._password = ""
            self._logger.info("监控已停止")
            self.status_changed.emit(final_status)
