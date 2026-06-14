from collections.abc import Mapping

import pytest

from netorium.services.ad_client import (
    ActiveDirectoryConfig,
    ActiveDirectoryError,
    test_active_directory_connection as run_ad_connection_test,
)


class FakeConnection:
    def __init__(self, bind_result: bool, result: Mapping[str, object] | None = None) -> None:
        self.bind_result = bind_result
        self.result = result or {}
        self.unbound = False

    def bind(self) -> bool:
        return self.bind_result

    def unbind(self) -> object:
        self.unbound = True
        return None


class FakeFactory:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.calls: list[tuple[str, str, str, float]] = []

    def __call__(self, server: str, user: str, password: str, timeout: float) -> FakeConnection:
        self.calls.append((server, user, password, timeout))
        return self.connection


def test_ad_connection_binds_with_configured_credentials() -> None:
    connection = FakeConnection(True)
    factory = FakeFactory(connection)

    result = run_ad_connection_test(
        ActiveDirectoryConfig(
            server="ldaps://dc01.corp.local/",
            domain="corp.local",
            bind_user="CN=Netorium,CN=Users,DC=corp,DC=local",
            bind_password="secret-password",
        ),
        client_factory=factory,
        timeout=3.0,
    )

    assert result.server == "ldaps://dc01.corp.local"
    assert result.domain == "corp.local"
    assert result.bind_user == "CN=Netorium,CN=Users,DC=corp,DC=local"
    assert result.message == "Bind successful"
    assert connection.unbound is True
    assert factory.calls == [
        (
            "ldaps://dc01.corp.local",
            "CN=Netorium,CN=Users,DC=corp,DC=local",
            "secret-password",
            3.0,
        )
    ]


def test_ad_connection_rejects_placeholder_config_without_network_call() -> None:
    factory = FakeFactory(FakeConnection(True))

    with pytest.raises(ActiveDirectoryError, match="not configured"):
        run_ad_connection_test(
            ActiveDirectoryConfig(
                server="ldap://ad.example.local",
                domain="example.local",
                bind_user="CN=Netorium,CN=Users,DC=example,DC=local",
                bind_password="CHANGE_ME",
            ),
            client_factory=factory,
        )

    assert factory.calls == []


def test_ad_connection_rejects_invalid_server_url() -> None:
    with pytest.raises(ActiveDirectoryError, match="ldap or ldaps URL"):
        run_ad_connection_test(
            ActiveDirectoryConfig(
                server="dc01.corp.local",
                domain="corp.local",
                bind_user="CN=Netorium,CN=Users,DC=corp,DC=local",
                bind_password="secret-password",
            ),
            client_factory=FakeFactory(FakeConnection(True)),
        )


def test_ad_connection_reports_bind_failure_and_unbinds() -> None:
    connection = FakeConnection(False, {"description": "invalidCredentials"})

    with pytest.raises(ActiveDirectoryError, match="invalidCredentials"):
        run_ad_connection_test(
            ActiveDirectoryConfig(
                server="ldap://dc01.corp.local",
                domain="corp.local",
                bind_user="CN=Netorium,CN=Users,DC=corp,DC=local",
                bind_password="secret-password",
            ),
            client_factory=FakeFactory(connection),
        )

    assert connection.unbound is True


def test_ad_connection_reports_factory_error() -> None:
    def fail(server: str, user: str, password: str, timeout: float) -> FakeConnection:
        raise RuntimeError("cannot connect")

    with pytest.raises(ActiveDirectoryError, match="AD connection failed"):
        run_ad_connection_test(
            ActiveDirectoryConfig(
                server="ldap://dc01.corp.local",
                domain="corp.local",
                bind_user="CN=Netorium,CN=Users,DC=corp,DC=local",
                bind_password="secret-password",
            ),
            client_factory=fail,
        )
