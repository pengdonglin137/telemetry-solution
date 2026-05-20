# Copyright 2025 Arm Limited
# SPDX-License-Identifier: Apache-2.0

from json import load
from pathlib import Path
from types import SimpleNamespace

import pytest

import topdown_tool.cmn_probe.cmn_probe as cmn_probe_module
from topdown_tool.cmn_probe.cmn_database import CmnDatabase
from topdown_tool.cmn_probe.cmn_probe import CmnProbe
from topdown_tool.cmn_probe.common import CmnLocation, CmnProbeFactoryConfig
from topdown_tool.common.telemetry_paths import telemetry_probe_metrics_dir
from topdown_tool.perf.mux_interval import MuxIntervalRequest, mux_interval_path
from topdown_tool.perf.windows_perf import WindowsPerf


class _WindowsPerfFactory:
    @staticmethod
    def get_platform_class():
        return WindowsPerf


class _OtherPerfFactory:
    @staticmethod
    def get_platform_class():
        return object()


class _CmnPerf:
    @staticmethod
    def get_cmn_frequency(_cmn_index):
        return 2_000_000_000

    @staticmethod
    def get_cmn_mux_interval(_cmn_index):
        return 1


class _CmnPerfFactory:
    @staticmethod
    def get_platform_class():
        return _CmnPerf


class _MutableMuxIntervalCmnPerf:
    mux_intervals = {}
    mux_calls = []

    @staticmethod
    def get_cmn_frequency(_cmn_index):
        return 2_000_000_000

    @classmethod
    def get_cmn_mux_interval(cls, cmn_index):
        cls.mux_calls.append(cmn_index)
        return cls.mux_intervals[cmn_index]


class _MutableMuxIntervalCmnPerfFactory:
    @staticmethod
    def get_platform_class():
        return _MutableMuxIntervalCmnPerf


@pytest.fixture
def cmn_db() -> CmnDatabase:
    base_dir = Path(__file__).resolve().parent
    fixtures_dir = base_dir / "fixtures"
    with (fixtures_dir / "topology.json").open(encoding="utf-8") as f:
        topology_json = load(f)
    with (fixtures_dir / "cmn-700.json").open(encoding="utf-8") as f:
        specification_json = load(f)
    return CmnDatabase("700", (0,), topology_json, specification_json)


@pytest.fixture
def cmn_700_db() -> CmnDatabase:
    base_dir = Path(__file__).resolve().parent
    fixtures_dir = base_dir / "fixtures"
    with (fixtures_dir / "topology.json").open(encoding="utf-8") as f:
        topology_json = load(f)
    with (telemetry_probe_metrics_dir("cmn") / "cmn_700_r0p0_pmu.json").open(
        encoding="utf-8"
    ) as f:
        specification_json = load(f)
    return CmnDatabase("700 R0P0", (0,), topology_json, specification_json)


def test_uses_windows_perf(cmn_db: CmnDatabase) -> None:
    conf = CmnProbeFactoryConfig()
    probe = CmnProbe(conf, cmn_db, capture_data=False, base_csv_dir=None, perf_factory_instance=_WindowsPerfFactory())

    assert probe.uses_windows_perf() is True


def test_uses_windows_perf_false(cmn_db: CmnDatabase) -> None:
    conf = CmnProbeFactoryConfig()
    probe = CmnProbe(conf, cmn_db, capture_data=False, base_csv_dir=None, perf_factory_instance=_OtherPerfFactory())

    assert probe.uses_windows_perf() is False


def test_need_capture_transitions(cmn_db: CmnDatabase) -> None:
    conf = CmnProbeFactoryConfig()
    probe = CmnProbe(conf, cmn_db, capture_data=False, base_csv_dir=None, perf_factory_instance=_OtherPerfFactory())

    assert probe.need_capture() is False

    probe.capture_data = True
    probe.captured = False

    assert probe.need_capture() is True
    assert probe.need_capture() is False


def test_get_mux_interval_requests_uses_cmn_indices() -> None:
    conf = CmnProbeFactoryConfig(mux_interval_ms=6)
    database = SimpleNamespace(cmn_indices=(0, 2), get_version=lambda: "700")
    probe = CmnProbe(
        conf,
        database,
        capture_data=False,
        base_csv_dir=None,
        perf_factory_instance=_OtherPerfFactory(),
    )
    probe.capture_data = True

    assert probe.get_mux_interval_requests() == (
        MuxIntervalRequest(mux_interval_path("arm_cmn_0"), 6),
        MuxIntervalRequest(mux_interval_path("arm_cmn_2"), 6),
    )


def test_get_mux_interval_requests_is_empty_when_capture_disabled(cmn_db: CmnDatabase) -> None:
    conf = CmnProbeFactoryConfig(mux_interval_ms=6)

    probe = CmnProbe(
        conf,
        cmn_db,
        capture_data=False,
        base_csv_dir=None,
        perf_factory_instance=_OtherPerfFactory(),
    )

    assert probe.get_mux_interval_requests() == ()


def test_start_capture_refreshes_cmn_mux_interval_before_thread_func(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_dir = Path(__file__).resolve().parent
    fixtures_dir = base_dir / "fixtures"
    with (fixtures_dir / "topology.json").open(encoding="utf-8") as f:
        topology_json = load(f)
    with (telemetry_probe_metrics_dir("cmn") / "cmn_700_r0p0_pmu.json").open(
        encoding="utf-8"
    ) as f:
        specification_json = load(f)
    database = CmnDatabase("700 R0P0", (0, 1), topology_json, specification_json)
    _MutableMuxIntervalCmnPerf.mux_intervals = {0: 1, 1: 2}
    _MutableMuxIntervalCmnPerf.mux_calls = []

    conf = CmnProbeFactoryConfig(
        metrics=["cmn_hns_bw"],
        debug_path=str(tmp_path / "capture"),
    )
    probe = CmnProbe(
        conf,
        database,
        capture_data=True,
        base_csv_dir=None,
        perf_factory_instance=_MutableMuxIntervalCmnPerfFactory(),
    )
    assert _MutableMuxIntervalCmnPerf.mux_calls == []

    captured_mux_intervals = []

    def record_mux_interval_at_thread_start(self):
        captured_mux_intervals.append(self.max_mux_interval)
        self.first_capture_started.set()

    class SynchronousThread:
        def __init__(self, target):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(CmnProbe, "thread_func", record_mux_interval_at_thread_start)
    monkeypatch.setattr(cmn_probe_module, "Thread", SynchronousThread)

    _MutableMuxIntervalCmnPerf.mux_intervals = {0: 7, 1: 11}
    probe.start_capture()

    assert _MutableMuxIntervalCmnPerf.mux_calls == [0, 1]
    assert captured_mux_intervals == [11]


def test_write_regular_metrics_to_csv_hides_composite_dependencies(tmp_path: Path) -> None:
    probe = CmnProbe.__new__(CmnProbe)
    probe.base_csv_dir = str(tmp_path)
    probe.conf = CmnProbeFactoryConfig(cmn_generate_metrics_csv=True)
    probe.used_cmns = (0,)
    probe.version = "700 R0P0"
    probe.metrics_to_display = {"Regular Metrics": ("cmn_hns_bw",)}
    probe.group_data = {
        "Regular Metrics": {
            "topdown_group": False,
            "metrics_values": {
                "cmn_hns_bw": {CmnLocation(cmn_index=0): 1.25},
                "cmn_hns_rxreq_noretries_rate": {CmnLocation(cmn_index=0): 10.0},
            },
        }
    }
    probe.metrics_details = {
        "cmn_hns_bw": SimpleNamespace(units="GBytes per second"),
        "cmn_hns_rxreq_noretries_rate": SimpleNamespace(units="Requests per 1K clks"),
    }

    probe.write_regular_metrics_to_csv()

    cmn0_csv = tmp_path / "cmn" / "cmn_700_r0p0_index_0_metrics.csv"

    csv_text = cmn0_csv.read_text(encoding="utf-8")
    assert "cmn_hns_bw" in csv_text
    assert "cmn_hns_rxreq_noretries_rate" not in csv_text
