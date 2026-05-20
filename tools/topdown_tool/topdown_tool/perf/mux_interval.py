# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Best-effort perf mux interval application and restoration."""

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import sys
from typing import Iterable, Iterator, Optional, Protocol, Sequence

from rich.console import Console
from topdown_tool.common.devlib_types import Target
from topdown_tool.probe.cli_options import parse_positive_int
from topdown_tool.probe.probe import SharedContext

EVENT_SOURCE_DEVICES_ROOT = "/sys/bus/event_source/devices"
MUX_INTERVAL_FILENAME = "perf_event_mux_interval_ms"
GENERIC_MUX_INTERVAL_MS = 4


class MuxIntervalProbe(Protocol):
    def get_mux_interval_requests(self) -> Sequence["MuxIntervalRequest"]:
        """Return concrete sysfs mux interval requests for this probe."""


@dataclass(frozen=True)
class MuxIntervalRequest:
    path: str
    interval_ms: int


def parse_mux_interval(raw: str) -> int:
    return parse_positive_int(
        raw,
        error_message="mux interval must be a positive integer",
    )


def resolve_probe_mux_interval(
    _probe_name: str,
    probe_interval_ms: Optional[int],
    shared_context: SharedContext,
) -> int:
    if probe_interval_ms is not None:
        return probe_interval_ms
    if shared_context.mux_interval_ms is not None:
        return shared_context.mux_interval_ms
    return GENERIC_MUX_INTERVAL_MS


def mux_interval_path(device_name: str) -> str:
    return f"{EVENT_SOURCE_DEVICES_ROOT}/{device_name}/{MUX_INTERVAL_FILENAME}"


@contextmanager
def mux_interval_session(
    probes: Iterable[MuxIntervalProbe],
    *,
    target: Optional[Target],
    console: Optional[Console] = None,
) -> Iterator[None]:
    requests = _collect_requests(probes)
    if not requests:
        yield
        return

    output = console or Console()
    if not _can_write_mux_intervals(target):
        if target is None and sys.platform == "win32":
            output.print(
                "Warning: Skipping mux interval configuration because it is unsupported on Windows."
            )
        else:
            output.print(
                "Warning: Skipping mux interval configuration because root access is unavailable."
            )
        yield
        return

    applied: list[tuple[str, str]] = []
    try:
        for request in requests:
            original = _read_text(request.path, target)
            if original is None:
                output.print(
                    f"Warning: Failed to read mux interval from {request.path}; leaving it unchanged."
                )
                continue
            if _write_text(request.path, f"{request.interval_ms}\n", target):
                applied.append((request.path, original))
            else:
                output.print(
                    f"Warning: Failed to write mux interval {request.interval_ms} to {request.path}."
                )
        yield
    finally:
        for path, original in reversed(applied):
            if not _write_text(path, original, target):
                output.print(f"Warning: Failed to restore mux interval for {path}.")


def _collect_requests(probes: Iterable[MuxIntervalProbe]) -> tuple[MuxIntervalRequest, ...]:
    by_path: dict[str, MuxIntervalRequest] = {}
    for probe in probes:
        for request in probe.get_mux_interval_requests():
            by_path[request.path] = request
    return tuple(by_path.values())


def _can_write_mux_intervals(target: Optional[Target]) -> bool:
    if target is None:
        if sys.platform == "win32":
            return False
        geteuid = getattr(os, "geteuid", None)
        return bool(geteuid is not None and geteuid() == 0)
    try:
        if getattr(target, "username", None) == "root":
            return True
        out = target.execute("id -u", as_root=True, check_exit_code=False)
        return str(out).strip() == "0"
    except Exception:  # pylint: disable=broad-exception-caught
        return False


def _read_text(path: str, target: Optional[Target]) -> Optional[str]:
    if target is not None:
        return _remote_read_text(target, path)
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def _remote_read_text(target: Target, path: str) -> Optional[str]:
    try:
        out = target.execute(
            f"cat {shlex.quote(path)}",
            check_exit_code=True,
        )
    except Exception:  # pylint: disable=broad-exception-caught
        try:
            out = target.read_value(path)  # type: ignore[attr-defined]
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    if isinstance(out, (bytes, bytearray)):
        return out.decode("utf-8", errors="ignore")
    return str(out)


def _write_text(path: str, text: str, target: Optional[Target]) -> bool:
    if target is not None:
        command = "printf %s " + shlex.quote(text) + " > " + shlex.quote(path)
        try:
            target.execute(command, as_root=True, check_exit_code=True)
            return True
        except Exception:  # pylint: disable=broad-exception-caught
            return False
    try:
        Path(path).write_text(text, encoding="utf-8")
        return True
    except OSError:
        return False
