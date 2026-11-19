from dataclasses import dataclass
from typing import Protocol

from keyring.backends.Windows import WinVaultKeyring
from PySide6.QtCore import QSettings

SERVICE_NAME = "yyict-toolbox-campus-network"


@dataclass(frozen=True, slots=True)
class CampusSettings:
    account: str = ""
    carrier: str = "cmcc"
    probe_interval: int = 5
    log_level: int = 3

    def validate(self) -> None:
        if not self.account or any(c.isspace() for c in self.account):
            raise ValueError("请填写不含空格的账号")
        if "@" in self.account or "," in self.account:
            raise ValueError("账号只需填写学号或手机号，不含运营商后缀")
        if self.carrier not in {"cmcc", "unicom", "telecom"}:
            raise ValueError("请选择有效运营商")
        if not 1 <= self.probe_interval <= 3600:
            raise ValueError("探针间隔应为 1 至 3600 秒")
        if self.log_level not in {1, 2, 3}:
            raise ValueError("日志等级应为 1、2 或 3")


class CredentialBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


class CredentialStorageError(RuntimeError):
    pass


class CampusSettingsStore:
    def __init__(
        self,
        settings: QSettings | None = None,
        credential_backend: CredentialBackend | None = None,
    ) -> None:
        self._settings = settings or QSettings("YYICT", "CampusToolbox")
        # 固定使用 Windows 凭据库，禁止 keyring 自动回退到明文后端。
        self._credential_backend = credential_backend or WinVaultKeyring()

    def load(self) -> tuple[CampusSettings, str]:
        settings = CampusSettings(
            account=str(self._settings.value("campus/account", "")),
            carrier=str(self._settings.value("campus/carrier", "cmcc")),
            probe_interval=self._settings.value("campus/probe_interval", 60, type=int),
            log_level=self._settings.value("logging/level", 3, type=int),
        )
        password = ""
        if settings.account:
            try:
                password = self._credential_backend.get_password(
                    SERVICE_NAME,
                    self._credential_key(settings.account, settings.carrier),
                ) or ""
            except Exception as error:
                raise CredentialStorageError("无法读取 Windows 凭据库") from error
        return settings, password

    def save(self, settings: CampusSettings, password: str) -> None:
        settings.validate()
        key = self._credential_key(settings.account, settings.carrier)
        try:
            if password:
                self._credential_backend.set_password(SERVICE_NAME, key, password)
            elif self._credential_backend.get_password(SERVICE_NAME, key):
                self._credential_backend.delete_password(SERVICE_NAME, key)
        except Exception as error:
            raise CredentialStorageError("无法保存 Windows 凭据库") from error

        self._settings.setValue("campus/account", settings.account)
        self._settings.setValue("campus/carrier", settings.carrier)
        self._settings.setValue("campus/probe_interval", settings.probe_interval)
        self._settings.setValue("logging/level", settings.log_level)
        self._settings.sync()
        if self._settings.status() != QSettings.Status.NoError:
            raise CredentialStorageError("无法保存应用设置")

    @staticmethod
    def _credential_key(account: str, carrier: str) -> str:
        return f"{carrier}:{account}"
