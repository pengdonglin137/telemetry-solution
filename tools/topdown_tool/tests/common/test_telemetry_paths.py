# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

from topdown_tool.common.telemetry_paths import telemetry_probe_specifications_dir


def test_telemetry_probe_specifications_dir_returns_canonical_path() -> None:
    assert telemetry_probe_specifications_dir("cpu").as_posix().endswith("/data/pmu/cpu/specifications")
    assert telemetry_probe_specifications_dir("cmn").as_posix().endswith("/data/pmu/cmn/specifications")
