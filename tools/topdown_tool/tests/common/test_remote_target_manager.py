# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

import argparse
from typing import Optional

import pytest

from topdown_tool.common.remote_target_manager import (
    TARGET_CONFIG_ENV_VAR,
    TARGET_TYPE_ENV_VAR,
    RemoteTargetManager,
)


class _StubTarget:
    def __init__(self, os_name: str = "linux") -> None:
        self.os = os_name

    def disconnect(self) -> None:
        """No-op for test cleanup."""


def _args(
    target_type: Optional[str] = None,
    target_config: Optional[str] = None,
) -> argparse.Namespace:
    return argparse.Namespace(target_type=target_type, target_config=target_config)


def test_configure_from_env_when_cli_not_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = RemoteTargetManager()
    monkeypatch.setenv(TARGET_TYPE_ENV_VAR, "ssh")
    monkeypatch.setenv(
        TARGET_CONFIG_ENV_VAR,
        '{"host": "example.test", "username": "arm", "password": "secret"}',
    )

    seen: list[tuple[str, dict[str, str]]] = []

    def fake_create_target(target_type: str, conn_settings: dict[str, str]) -> _StubTarget:
        seen.append((target_type, conn_settings))
        return _StubTarget()

    monkeypatch.setattr(manager, "_create_target", fake_create_target)

    manager.configure_from_args(_args())

    assert seen == [
        (
            "ssh",
            {"host": "example.test", "username": "arm", "password": "secret"},
        )
    ]
    assert manager.get_target_type() == "ssh"
    assert manager.get_target() is not None


def test_cli_values_override_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = RemoteTargetManager()
    monkeypatch.setenv(TARGET_TYPE_ENV_VAR, "adb")
    monkeypatch.setenv(TARGET_CONFIG_ENV_VAR, '{"device": "env-device"}')

    seen: list[tuple[str, dict[str, str]]] = []

    def fake_create_target(target_type: str, conn_settings: dict[str, str]) -> _StubTarget:
        seen.append((target_type, conn_settings))
        return _StubTarget()

    monkeypatch.setattr(manager, "_create_target", fake_create_target)

    manager.configure_from_args(
        _args(target_type="ssh", target_config='{"host": "cli-host", "username": "cli-user"}')
    )

    assert seen == [("ssh", {"host": "cli-host", "username": "cli-user"})]


def test_uses_cli_type_with_env_config_when_mixed_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = RemoteTargetManager()
    monkeypatch.setenv(TARGET_CONFIG_ENV_VAR, '{"device": "ZX1G22"}')
    seen: list[tuple[str, dict[str, str]]] = []

    def fake_create_target(target_type: str, conn_settings: dict[str, str]) -> _StubTarget:
        seen.append((target_type, conn_settings))
        return _StubTarget(os_name="android")

    monkeypatch.setattr(manager, "_create_target", fake_create_target)
    manager.configure_from_args(_args(target_type="adb"))

    assert seen == [("adb", {"device": "ZX1G22"})]
    assert manager.get_target_os() == "android"


def test_uses_env_type_with_cli_config_when_mixed_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = RemoteTargetManager()
    monkeypatch.setenv(TARGET_TYPE_ENV_VAR, "ssh")
    seen: list[tuple[str, dict[str, str]]] = []

    def fake_create_target(target_type: str, conn_settings: dict[str, str]) -> _StubTarget:
        seen.append((target_type, conn_settings))
        return _StubTarget()

    monkeypatch.setattr(manager, "_create_target", fake_create_target)
    manager.configure_from_args(
        _args(target_config='{"host": "cli-host", "username": "cli-user"}')
    )

    assert seen == [("ssh", {"host": "cli-host", "username": "cli-user"})]


def test_empty_environment_values_are_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = RemoteTargetManager()
    monkeypatch.setenv(TARGET_TYPE_ENV_VAR, " ")
    monkeypatch.setenv(TARGET_CONFIG_ENV_VAR, "\n")

    manager.configure_from_args(_args())

    assert manager.get_target() is None
    assert manager.get_target_type() is None


def test_invalid_target_type_from_environment_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = RemoteTargetManager()
    monkeypatch.setenv(TARGET_TYPE_ENV_VAR, "serial")
    monkeypatch.setenv(TARGET_CONFIG_ENV_VAR, '{"port": "/dev/ttyUSB0"}')

    with pytest.raises(RuntimeError, match="Invalid target-type"):
        manager.configure_from_args(_args())


def test_target_type_without_target_config_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = RemoteTargetManager()
    monkeypatch.setenv(TARGET_TYPE_ENV_VAR, "ssh")
    monkeypatch.delenv(TARGET_CONFIG_ENV_VAR, raising=False)

    with pytest.raises(RuntimeError, match="must be provided together"):
        manager.configure_from_args(_args())


def test_failed_reconfigure_clears_previously_configured_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = RemoteTargetManager()
    monkeypatch.setenv(
        TARGET_CONFIG_ENV_VAR,
        '{"host": "example.test", "username": "arm", "password": "secret"}',
    )
    monkeypatch.setenv(TARGET_TYPE_ENV_VAR, "ssh")

    monkeypatch.setattr(
        manager,
        "_create_target",
        lambda target_type, conn_settings: _StubTarget(),
    )
    manager.configure_from_args(_args())
    assert manager.get_target() is not None
    assert manager.get_target_type() == "ssh"

    with pytest.raises(RuntimeError, match="Invalid target-type"):
        manager.configure_from_args(_args(target_type="serial"))

    assert manager.get_target() is None
    assert manager.get_target_type() is None
