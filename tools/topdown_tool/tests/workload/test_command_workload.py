# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Arm Limited

import os
import sys

import pytest

from topdown_tool.workload import CommandWorkload

pytestmark = pytest.mark.skipif(
    sys.platform not in ("linux", "win32"),
    reason="CommandWorkload local runner is only implemented on Linux and Windows.",
)


def test_command_valid():
    command = ["true"]
    with CommandWorkload(command) as workload:
        workload.start()
        pid = workload.wait()
        assert pid is not None and pid > 0


def test_command_nonexisting(tmp_path):
    command = [f"{tmp_path}/testperf"]

    assert not os.path.exists(command[0])

    with pytest.raises(OSError):
        with CommandWorkload(command) as workload:
            workload.start()


def test_command_permissionerror(tmp_path):
    command = [f"{tmp_path}/testperf"]

    with open(command[0], "w") as f:
        f.write("test content")

    assert os.path.exists(command[0])
    assert not os.access(command[0], os.X_OK)

    with pytest.raises(OSError):
        with CommandWorkload(command) as workload:
            workload.start()
