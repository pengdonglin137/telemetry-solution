# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Ctrl-C handling while polling a remote target.

devlib can swallow the exception raised by a SIGINT inside one of its calls and surface an
unrelated error instead (seen on Android: ``AttributeError``). Polling loops must still stop.
"""

import os
import signal
import threading

import pytest

from topdown_tool.common.pidwatch.remote_linux import RemoteLinuxPidWatcher
from topdown_tool.common.remote_utils import InterruptGuard, remote_wait_for_pid_state


class _SwallowingTarget:
    """Fake target whose file_exists swallows any exception, like devlib does."""

    def __init__(self, interrupt_after: int) -> None:
        self.calls = 0
        self._interrupt_after = interrupt_after

    def file_exists(self, _path: str) -> bool:
        self.calls += 1
        try:
            if self.calls == self._interrupt_after:
                os.kill(os.getpid(), signal.SIGINT)
        except BaseException:  # pylint: disable=broad-exception-caught
            pass
        # devlib then reports an unrelated failure.
        raise AttributeError("'NoneType' object has no attribute 'items'")

    def execute(self, _cmd: str, **_kwargs) -> str:
        return ""

    def list_directory(self, _path: str):
        return []


@pytest.fixture(autouse=True)
def _restore_sigint():
    previous = signal.getsignal(signal.SIGINT)
    yield
    signal.signal(signal.SIGINT, previous)


def test_pid_watcher_stops_on_swallowed_sigint() -> None:
    target = _SwallowingTarget(interrupt_after=3)
    watcher = RemoteLinuxPidWatcher({1234}, target, poll_interval=0.0)

    with pytest.raises(InterruptedError):
        watcher.wait_next()
    assert target.calls == 3


def test_wait_for_pid_state_stops_on_swallowed_sigint() -> None:
    # The PID keeps "existing" (shell fallback succeeds), so polling continues until SIGINT.
    target = _SwallowingTarget(interrupt_after=2)

    with pytest.raises(InterruptedError):
        remote_wait_for_pid_state(
            target, 1234, present=False, timeout=5, as_root=False, poll_interval=0.01
        )
    assert target.calls == 2


def test_guard_restores_previous_handler() -> None:
    sentinel = signal.getsignal(signal.SIGINT)
    guard = InterruptGuard()
    with guard.active():
        assert signal.getsignal(signal.SIGINT) is not sentinel
        guard.check()  # no interrupt recorded
    assert signal.getsignal(signal.SIGINT) is sentinel


def test_guard_is_noop_outside_main_thread() -> None:
    result = {}

    def run() -> None:
        guard = InterruptGuard()
        with guard.active():
            result["handler"] = signal.getsignal(signal.SIGINT)

    before = signal.getsignal(signal.SIGINT)
    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    assert result["handler"] is before
