# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

import shlex
from pathlib import Path

import pytest
from rich.console import Console

from topdown_tool.perf.mux_interval import (
    GENERIC_MUX_INTERVAL_MS,
    MuxIntervalRequest,
    mux_interval_session,
    parse_mux_interval,
    resolve_probe_mux_interval,
)
from topdown_tool.perf.perf_factory import PerfFactory
from topdown_tool.probe.probe import SharedContext


class _Probe:
    def __init__(self, *requests: MuxIntervalRequest) -> None:
        self._requests = requests

    def get_mux_interval_requests(self):
        return self._requests


def _console(tmp_path: Path) -> Console:
    return Console(
        file=(tmp_path / "console.txt").open("w", encoding="utf-8"), force_terminal=False
    )


def _shared_context(*, mux_interval_ms=None) -> SharedContext:
    return SharedContext(
        perf_factory=PerfFactory(),
        mux_interval_ms=mux_interval_ms,
    )


def test_parse_mux_interval_rejects_non_positive_values() -> None:
    assert parse_mux_interval("4") == 4
    with pytest.raises(Exception, match="positive integer"):
        parse_mux_interval("0")
    with pytest.raises(Exception, match="positive integer"):
        parse_mux_interval("-1")


def test_resolve_probe_mux_interval_precedence() -> None:
    assert resolve_probe_mux_interval("CPU", 12, _shared_context(mux_interval_ms=9)) == 12
    assert resolve_probe_mux_interval("CPU", None, _shared_context(mux_interval_ms=9)) == 9
    assert resolve_probe_mux_interval("CPU", None, _shared_context()) == GENERIC_MUX_INTERVAL_MS


def test_resolve_probe_mux_interval_treats_missing_shared_interval_as_unset() -> None:
    context = SharedContext(perf_factory=PerfFactory())

    assert resolve_probe_mux_interval("CPU", None, context) == GENERIC_MUX_INTERVAL_MS


def test_local_mux_interval_session_applies_and_restores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mux_file = tmp_path / "perf_event_mux_interval_ms"
    mux_file.write_text("100\n", encoding="utf-8")
    monkeypatch.setattr("topdown_tool.perf.mux_interval.os.geteuid", lambda: 0)

    with mux_interval_session(
        [_Probe(MuxIntervalRequest(str(mux_file), 4))],
        target=None,
        console=_console(tmp_path),
    ):
        assert mux_file.read_text(encoding="utf-8") == "4\n"

    assert mux_file.read_text(encoding="utf-8") == "100\n"


def test_local_mux_interval_session_restores_exact_original_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mux_file = tmp_path / "perf_event_mux_interval_ms"
    mux_file.write_text("77", encoding="utf-8")
    monkeypatch.setattr("topdown_tool.perf.mux_interval.os.geteuid", lambda: 0)

    with mux_interval_session(
        [_Probe(MuxIntervalRequest(str(mux_file), 4))],
        target=None,
        console=_console(tmp_path),
    ):
        assert mux_file.read_text(encoding="utf-8") == "4\n"

    assert mux_file.read_text(encoding="utf-8") == "77"


def test_local_mux_interval_session_skips_when_not_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mux_file = tmp_path / "perf_event_mux_interval_ms"
    mux_file.write_text("100\n", encoding="utf-8")
    monkeypatch.setattr("topdown_tool.perf.mux_interval.os.geteuid", lambda: 1000)
    console = _console(tmp_path)

    with mux_interval_session(
        [_Probe(MuxIntervalRequest(str(mux_file), 4))],
        target=None,
        console=console,
    ):
        assert mux_file.read_text(encoding="utf-8") == "100\n"

    assert "Skipping mux interval configuration" in (tmp_path / "console.txt").read_text(
        encoding="utf-8"
    )


def test_local_mux_interval_session_skips_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mux_file = tmp_path / "perf_event_mux_interval_ms"
    mux_file.write_text("100\n", encoding="utf-8")
    monkeypatch.setattr("topdown_tool.perf.mux_interval.sys.platform", "win32")
    monkeypatch.setattr("topdown_tool.perf.mux_interval.os.geteuid", lambda: 0)

    with mux_interval_session(
        [_Probe(MuxIntervalRequest(str(mux_file), 4))],
        target=None,
        console=_console(tmp_path),
    ):
        assert mux_file.read_text(encoding="utf-8") == "100\n"

    assert mux_file.read_text(encoding="utf-8") == "100\n"
    warning = (tmp_path / "console.txt").read_text(encoding="utf-8")
    assert "unsupported on" in warning
    assert "Windows" in warning


class _Target:
    def __init__(self) -> None:
        self.username = "root"
        self.files = {"/sys/dev/file": "77\n"}
        self.exec_calls = []

    def execute(self, cmd: str, **kwargs) -> str:
        self.exec_calls.append((cmd, kwargs))
        if cmd == "id -u":
            return "0\n"
        if cmd.startswith("printf"):
            parts = shlex.split(cmd)
            value = parts[2]
            path = parts[4]
            self.files[path] = value
            return ""
        if cmd.startswith("cat "):
            return self.files[cmd[4:]]
        return ""

    def read_value(self, path: str) -> str:
        return self.files[path]


class _StrippingReadValueTarget(_Target):
    def read_value(self, path: str) -> str:
        return self.files[path].strip()


def test_remote_mux_interval_session_applies_and_restores(tmp_path: Path) -> None:
    target = _Target()

    with mux_interval_session(
        [_Probe(MuxIntervalRequest("/sys/dev/file", 4))],
        target=target,
        console=_console(tmp_path),
    ):
        assert target.files["/sys/dev/file"] == "4\n"

    assert target.files["/sys/dev/file"] == "77\n"


def test_remote_mux_interval_session_restores_exact_original_text(tmp_path: Path) -> None:
    target = _Target()
    target.files["/sys/dev/file"] = "77"

    with mux_interval_session(
        [_Probe(MuxIntervalRequest("/sys/dev/file", 4))],
        target=target,
        console=_console(tmp_path),
    ):
        assert target.files["/sys/dev/file"] == "4\n"

    assert target.files["/sys/dev/file"] == "77"


def test_remote_mux_interval_session_prefers_exact_cat_over_read_value(
    tmp_path: Path,
) -> None:
    target = _StrippingReadValueTarget()
    target.files["/sys/dev/file"] = "77\n"

    with mux_interval_session(
        [_Probe(MuxIntervalRequest("/sys/dev/file", 4))],
        target=target,
        console=_console(tmp_path),
    ):
        assert target.files["/sys/dev/file"] == "4\n"

    assert target.files["/sys/dev/file"] == "77\n"


def test_mux_interval_session_restores_when_body_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mux_file = tmp_path / "perf_event_mux_interval_ms"
    mux_file.write_text("100\n", encoding="utf-8")
    monkeypatch.setattr("topdown_tool.perf.mux_interval.os.geteuid", lambda: 0)

    with pytest.raises(RuntimeError, match="capture failed"):
        with mux_interval_session(
            [_Probe(MuxIntervalRequest(str(mux_file), 4))],
            target=None,
            console=_console(tmp_path),
        ):
            raise RuntimeError("capture failed")

    assert mux_file.read_text(encoding="utf-8") == "100\n"


def test_mux_interval_session_warns_when_restore_fails_without_hiding_body_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mux_file = tmp_path / "perf_event_mux_interval_ms"
    mux_file.write_text("100\n", encoding="utf-8")
    monkeypatch.setattr("topdown_tool.perf.mux_interval.os.geteuid", lambda: 0)

    def fake_write_text(path: str, text: str, target) -> bool:
        assert path == str(mux_file)
        assert target is None
        if text == "100\n":
            return False
        mux_file.write_text(text, encoding="utf-8")
        return True

    monkeypatch.setattr("topdown_tool.perf.mux_interval._write_text", fake_write_text)

    with pytest.raises(RuntimeError, match="capture failed"):
        with mux_interval_session(
            [_Probe(MuxIntervalRequest(str(mux_file), 4))],
            target=None,
            console=_console(tmp_path),
        ):
            assert mux_file.read_text(encoding="utf-8") == "4\n"
            raise RuntimeError("capture failed")

    assert "Failed to restore mux interval" in (tmp_path / "console.txt").read_text(
        encoding="utf-8"
    )


def test_mux_interval_session_deduplicates_last_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mux_file = tmp_path / "perf_event_mux_interval_ms"
    mux_file.write_text("100\n", encoding="utf-8")
    monkeypatch.setattr("topdown_tool.perf.mux_interval.os.geteuid", lambda: 0)

    with mux_interval_session(
        [
            _Probe(MuxIntervalRequest(str(mux_file), 4)),
            _Probe(MuxIntervalRequest(str(mux_file), 8)),
        ],
        target=None,
        console=_console(tmp_path),
    ):
        assert mux_file.read_text(encoding="utf-8") == "8\n"
