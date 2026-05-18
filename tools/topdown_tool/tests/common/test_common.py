# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 Arm Limited

import importlib
import sys

import pytest

from topdown_tool.common import range_encode
from topdown_tool.common.remote_target_manager import RemoteTargetManager


def test_empty_list():
    assert range_encode([]) is None


def test_single_value():
    assert range_encode([5]) == "5"


def test_all_consecutive():
    assert range_encode([0, 1, 2, 3]) == "0-3"


def test_non_consecutive_start():
    assert range_encode([0, 2, 3, 4]) == "0,2-4"


def test_multiple_ranges():
    assert range_encode([0, 2, 3, 4, 6, 7, 9]) == "0,2-4,6-7,9"


def test_unsorted_input():
    # Function sorts the list automatically.
    assert range_encode([3, 2, 1, 0, 5, 4]) == "0-5"


def test_missing_devlib_error_points_to_uv_remote_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "devlib", None)
    manager = RemoteTargetManager()

    with pytest.raises(RuntimeError) as exc_info:
        manager._create_target("ssh", {})  # pylint: disable=protected-access

    message = str(exc_info.value)
    assert "uv run --no-project scripts/install_topdown_tool.py --remote" in message
    assert "uv sync --locked --extra remote --no-dev" in message
    assert "pip" not in message


def test_probe_entry_point_failure_points_to_uv(monkeypatch, capsys):
    import topdown_tool.probe.probe as probe_module  # pylint: disable=import-outside-toplevel

    monkeypatch.delitem(sys.modules, "topdown_tool.__main__", raising=False)

    def _raise_on_load():
        raise RuntimeError("entry point failure")

    monkeypatch.setattr(probe_module, "load_probe_factories", _raise_on_load)

    with pytest.raises(SystemExit) as exc_info:
        importlib.import_module("topdown_tool.__main__")

    assert exc_info.value.code == 1
    message = capsys.readouterr().out
    assert "uv run --no-project scripts/install_topdown_tool.py" in message
    assert "uv sync --locked" in message
    assert "pip" not in message
    monkeypatch.delitem(sys.modules, "topdown_tool.__main__", raising=False)
