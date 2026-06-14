from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Mapping, Protocol, cast
from urllib.parse import urlparse

DEFAULT_TIMEOUT_SECONDS = 10.0
PLACEHOLDER_SERVER = "ldap://ad.example.local"
PLACEHOLDER_SECRET = "CHANGE_ME"


class LdapConnection(Protocol):
    result: Mapping[str, object]

    def bind(self) -> bool:
        pass

    def unbind(self) -> object:
        pass


class LdapClientFactory(Protocol):
    def __call__(
        self,
        server: str,
        user: str,
        password: str,
        timeout: float,
    ) -> LdapConnection:
        pass


class ActiveDirectoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActiveDirectoryConfig:
    server: str
    domain: str
    bind_user: str
    bind_password: str


@dataclass(frozen=True)
class ActiveDirectoryTestResult:
    server: str
    domain: str
    bind_user: str
    message: str


def test_active_directory_connection(
    config: ActiveDirectoryConfig,
    client_factory: LdapClientFactory | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ActiveDirectoryTestResult:
    server = _normalize_server(config.server)
    domain = _normalize_required(config.domain, "AD domain")
    bind_user = _normalize_required(config.bind_user, "AD bind_user")
    bind_password = _normalize_required(config.bind_password, "AD bind_password")
    _reject_placeholder_config(server, bind_user, bind_password)

    active_factory = client_factory or _create_ldap_connection
    try:
        connection = active_factory(server, bind_user, bind_password, timeout)
    except Exception as exc:
        raise ActiveDirectoryError("AD connection failed. Check network access and AD settings.") from exc

    try:
        if not connection.bind():
            raise ActiveDirectoryError(f"AD bind failed: {_ldap_error_message(connection.result)}")
    finally:
        connection.unbind()

    return ActiveDirectoryTestResult(
        server=server,
        domain=domain,
        bind_user=bind_user,
        message="Bind successful",
    )


def _create_ldap_connection(
    server: str,
    user: str,
    password: str,
    timeout: float,
) -> LdapConnection:
    try:
        ldap3 = importlib.import_module("ldap3")
    except ImportError as exc:
        raise ActiveDirectoryError("ldap3 is not installed. Reinstall Netorium with dependencies.") from exc

    server_obj = ldap3.Server(server, connect_timeout=timeout, get_info=ldap3.NONE)
    connection = ldap3.Connection(
        server_obj,
        user=user,
        password=password,
        auto_bind=False,
        receive_timeout=timeout,
    )
    return cast(LdapConnection, connection)


def _normalize_server(value: str) -> str:
    server = value.strip().rstrip("/")
    parsed = urlparse(server)
    if parsed.scheme not in ("ldap", "ldaps") or not parsed.netloc:
        raise ActiveDirectoryError("AD server must be an ldap or ldaps URL.")
    return server


def _normalize_required(value: str, label: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise ActiveDirectoryError(f"{label} cannot be empty.")
    return clean_value


def _reject_placeholder_config(server: str, bind_user: str, bind_password: str) -> None:
    if (
        server == PLACEHOLDER_SERVER
        or "example.local" in bind_user.lower()
        or bind_password == PLACEHOLDER_SECRET
    ):
        raise ActiveDirectoryError(
            "AD settings are not configured. Update active_directory.server, bind_user, and bind_password."
        )


def _ldap_error_message(result: Mapping[str, object]) -> str:
    for key in ("description", "message", "result"):
        value = result.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return "bind returned false"
