# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Tests covering mux interval wiring in ``topdown_tool.__main__``."""

import argparse
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Optional

import pytest
from rich.console import Console

from topdown_tool import __main__ as main_module
from topdown_tool.perf.perf_factory import PerfFactory


class _DummyProbe:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def output(self) -> None:
        self._events.append("output")


class _OutputFailingProbe(_DummyProbe):
    def output(self) -> None:
        self._events.append("output")
        raise RuntimeError("output failed")


def test_extend_arg_parser_accepts_mux_interval() -> None:
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    main_module.extend_arg_parser(parser, (), ())

    args = parser.parse_args(["--mux-interval", "4"])

    assert args.mux_interval == 4


def test_extend_arg_parser_rejects_non_positive_mux_interval(capsys) -> None:
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    main_module.extend_arg_parser(parser, (), ())

    with pytest.raises(SystemExit):
        parser.parse_args(["--mux-interval", "0"])

    assert "mux interval must be a positive integer" in capsys.readouterr().err


def test_build_shared_context_stores_mux_interval() -> None:
    args = argparse.Namespace(
        csv_output_path="tdt_out",
        mux_interval=7,
    )

    context = main_module.build_shared_context(
        args,
        datetime(2026, 1, 2, 3, 4, 5),
        PerfFactory(),
    )

    assert context.mux_interval_ms == 7


def test_main_propagates_output_exceptions_outside_capture_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    probe = _OutputFailingProbe(events)

    class _FakePerfFactory:
        def add_cli_arguments(self, parser: argparse.ArgumentParser) -> None:
            pass

        def configure_from_cli_arguments(self, args: argparse.Namespace) -> None:
            pass

        def have_perf_privilege(self) -> bool:
            return True

        def is_perf_runnable(self) -> bool:
            return True

        def get_effective_perf_path(self) -> str:
            return "perf"

    class _FakeProbeFactory:
        def name(self) -> str:
            return "CPU"

        def is_available(self, shared_context) -> bool:
            return True

        def add_cli_arguments(self, parser: argparse.ArgumentParser) -> None:
            pass

        def configure_from_cli_arguments(
            self,
            args: argparse.Namespace,
            shared_context,
        ) -> bool:
            return True

        def create(self, capture_data: bool) -> list[_OutputFailingProbe]:
            assert capture_data is True
            return [probe]

        def get_description(self) -> str:
            return "CPU"

    @contextmanager
    def fake_mux_interval_session(
        session_probes,
        *,
        target: Optional[object],
        console: Optional[Console],
    ) -> Iterator[None]:
        assert session_probes == [probe]
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    def fake_capture_systemwide_workload(session_probes, session_target) -> None:
        assert session_probes == [probe]
        assert session_target is None
        events.append("capture")

    monkeypatch.setattr(main_module, "PerfFactory", _FakePerfFactory)
    monkeypatch.setattr(main_module, "PROBE_FACTORY", (_FakeProbeFactory(),))
    monkeypatch.setattr(main_module, "mux_interval_session", fake_mux_interval_session)
    monkeypatch.setattr(
        main_module, "capture_systemwide_workload", fake_capture_systemwide_workload
    )
    monkeypatch.setattr(
        main_module.remote_target_manager, "add_cli_arguments", lambda parser: None
    )
    monkeypatch.setattr(
        main_module.remote_target_manager, "configure_from_args", lambda args: None
    )
    monkeypatch.setattr(
        main_module.remote_target_manager, "get_remote_target", lambda: None
    )

    with pytest.raises(RuntimeError, match="output failed"):
        main_module.main([])

    assert events == ["enter", "capture", "output", "exit"]
