# Copyright 2025 Arm Limited
# SPDX-License-Identifier: Apache-2.0

from json import load
from pathlib import Path
from types import SimpleNamespace

import pytest

import topdown_tool.cmn_probe.cmn_probe as cmn_probe_module
from topdown_tool.cmn_probe.cmn_database import CmnDatabase
from topdown_tool.cmn_probe.cmn_probe import CmnProbe
from topdown_tool.cmn_probe.common import (
    CmnLocation,
    CmnProbeFactoryConfig,
    Event,
    MetricDetails,
    NodeLocation,
    PortLocation,
)
from topdown_tool.common.telemetry_paths import telemetry_probe_specifications_dir
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


class _DependencySeedDatabase:
    def __init__(self, base_db: CmnDatabase) -> None:
        self._base_db = base_db
        self.cmn_indices = base_db.cmn_indices

    def __getattr__(self, name):
        return getattr(self._base_db, name)

    def get_collectable_metrics(self, metrics):
        if metrics is None:
            return {}
        return {"Regular Metrics": tuple(self.discard_locations(metrics))}

    @staticmethod
    def get_collectable_groups(_groups):
        return {}

    @staticmethod
    def get_collectable_topdown_metrics(_metrics, _groups):
        return {}, {}

    @staticmethod
    def get_collectable_base_metrics_for_topdown_group(_groups):
        return {}

    @staticmethod
    def get_metrics_with_dependencies(metrics):
        dependencies = list(metrics)
        if (
            "cmn_dependency_seeded_metric" in dependencies
            and "cmn_dependency_metric" not in dependencies
        ):
            dependencies.append("cmn_dependency_metric")
        return tuple(dependencies)

    @staticmethod
    def get_metric_dependencies(metric_name):
        if metric_name == "cmn_dependency_seeded_metric":
            return ("cmn_dependency_metric",)
        return ()

    @staticmethod
    def get_metric_details(metric_name):
        if metric_name == "cmn_dependency_seeded_metric":
            return MetricDetails(
                title="Dependency seeded metric",
                description="Synthetic composite metric used for dependency seeding tests",
                sample_events=frozenset(),
                formula="cmn_dependency_metric",
                units="Synthetic units",
                node_device_id=None,
                port_device_id=0,
            )
        if metric_name == "cmn_dependency_metric":
            return MetricDetails(
                title="Dependency metric",
                description="Synthetic dependency metric used for dependency seeding tests",
                sample_events=frozenset({"dep_event"}),
                formula="dep_event",
                units="Synthetic units",
                node_device_id=None,
                port_device_id=0,
            )
        raise KeyError(metric_name)

    def get_schedulable_events_for_metric(self, metric_name, global_only):
        if metric_name != "cmn_dependency_metric":
            return {}
        if global_only:
            return {
                CmnLocation(cmn_index): [self._global_event(cmn_index)]
                for cmn_index in self.cmn_indices
            }
        return {
            PortLocation(cmn_index, 0x200, 1): [self._local_event(cmn_index)]
            for cmn_index in self.cmn_indices
        }

    @staticmethod
    def get_schedulable_xp_events_for_metric(_metric_name, _global_only):
        return {}

    @staticmethod
    def get_schedulable_watchpoints_for_metric(_metric_name, _global_only, _is_linux):
        return {}

    @staticmethod
    def _global_event(cmn_index: int) -> Event:
        return Event(
            name="dep_event",
            title="Synthetic dependency event",
            description="",
            cmn_index=cmn_index,
            type=4,
            eventid=1,
            occupid=None,
            nodeid=None,
        )

    @staticmethod
    def _local_event(cmn_index: int) -> Event:
        return Event(
            name="dep_event",
            title="Synthetic dependency event",
            description="",
            cmn_index=cmn_index,
            type=4,
            eventid=1,
            occupid=None,
            nodeid=0x204,
            xp_id=0x200,
        )


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
    with (telemetry_probe_specifications_dir("cmn") / "cmn_700_r0p0_pmu.json").open(
        encoding="utf-8"
    ) as f:
        specification_json = load(f)
    return CmnDatabase("700 R0P0", (0,), topology_json, specification_json)


@pytest.fixture
def cmn_multi_cmn_db() -> CmnDatabase:
    base_dir = Path(__file__).resolve().parent
    fixtures_dir = base_dir / "fixtures"
    with (fixtures_dir / "topology.json").open(encoding="utf-8") as f:
        topology_json = load(f)
    with (fixtures_dir / "cmn-700.json").open(encoding="utf-8") as f:
        specification_json = load(f)
    return CmnDatabase("700", (0, 1), topology_json, specification_json)


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


def test_composite_regular_metric_seeds_locations_from_dependencies(
    cmn_db: CmnDatabase,
) -> None:
    conf = CmnProbeFactoryConfig(metrics=["cmn_dependency_seeded_metric"])
    probe = CmnProbe(
        conf,
        _DependencySeedDatabase(cmn_db),
        capture_data=True,
        base_csv_dir=None,
        perf_factory_instance=_CmnPerfFactory(),
    )

    assert probe.metrics_to_display == {"Regular Metrics": ("cmn_dependency_seeded_metric",)}
    assert "cmn_dependency_metric" in probe.metrics_to_collect["Regular Metrics"]
    assert CmnLocation(cmn_index=0) in probe.group_data["Regular Metrics"]["metrics_values"][
        "cmn_dependency_seeded_metric"
    ]
    assert len(probe.group_data["Regular Metrics"]["events_for_perf"]) > 0


def test_location_filter_limits_dependency_seeded_regular_metric_locations(
    cmn_multi_cmn_db: CmnDatabase,
) -> None:
    conf = CmnProbeFactoryConfig(
        metrics=["cmn_dependency_seeded_metric@(CMN=0)"],
        capture_per_device_id=True,
    )

    probe = CmnProbe(
        conf,
        _DependencySeedDatabase(cmn_multi_cmn_db),
        capture_data=True,
        base_csv_dir=None,
        perf_factory_instance=_CmnPerfFactory(),
    )

    metric_locations = probe.group_data["Regular Metrics"]["metrics_values"][
        "cmn_dependency_seeded_metric"
    ]

    assert metric_locations
    assert {location.cmn_index for location in metric_locations} == {0}


def test_metric_location_filter_propagates_to_dependencies(cmn_db: CmnDatabase) -> None:
    metric_name = "cmn_dependency_seeded_metric"
    dependency_name = "cmn_dependency_metric"
    expected_location = PortLocation(0, 0x200, 1)

    conf = CmnProbeFactoryConfig(
        metrics=[f"{metric_name}@(CMN=0;XP=0x200;Port=1)"],
    )
    probe = CmnProbe(
        conf,
        _DependencySeedDatabase(cmn_db),
        capture_data=True,
        base_csv_dir=None,
        perf_factory_instance=_CmnPerfFactory(),
    )

    metric_locations = probe.group_data["Regular Metrics"]["metrics_values"][metric_name]
    dependency_locations = probe.group_data["Regular Metrics"]["original_metrics"][
        dependency_name
    ]

    assert set(metric_locations.keys()) == {expected_location}
    assert set(dependency_locations.keys()) == {expected_location}


def test_metric_location_filter_removes_global_location(cmn_db: CmnDatabase) -> None:
    metric_name = "cmn_hni_axi_ar_stall_rate"
    node_id = 0
    xp_id, port = cmn_db.get_xp_port_of_node(0, node_id)

    conf = CmnProbeFactoryConfig(
        metrics=[f"{metric_name}@(CMN=0;Node=0x{node_id:X})"],
    )
    probe = CmnProbe(
        conf,
        cmn_db,
        capture_data=True,
        base_csv_dir=None,
        perf_factory_instance=_CmnPerfFactory(),
    )

    located_metrics = probe.group_data["Regular Metrics"]["original_metrics"][metric_name]

    assert CmnLocation(cmn_index=0) not in located_metrics
    assert set(located_metrics.keys()) == {NodeLocation(0, xp_id, port, node_id)}


def test_group_location_filter_limits_metric_locations(cmn_db: CmnDatabase) -> None:
    metric_name = "cmn_rnf_txreq_rate"
    located_metrics = cmn_db.get_schedulable_events_for_metric(metric_name, False)
    port_location = next(
        location
        for location in located_metrics
        if isinstance(location, PortLocation)
    )

    group_name = "RNF_CHI_Egress_Traffic"
    conf = CmnProbeFactoryConfig(
        groups=[
            f"{group_name}@(CMN={port_location.cmn_index};XP=0x{port_location.xp_id:X};Port={port_location.port})"
        ],
    )
    probe = CmnProbe(
        conf,
        cmn_db,
        capture_data=True,
        base_csv_dir=None,
        perf_factory_instance=_CmnPerfFactory(),
    )

    group_metrics = probe.group_data[group_name]["original_metrics"][metric_name]

    assert CmnLocation(cmn_index=port_location.cmn_index) not in group_metrics
    assert set(group_metrics.keys()) == {port_location}


def test_location_filter_limits_topdown_group_locations(
    cmn_multi_cmn_db: CmnDatabase,
) -> None:
    group_name = "CMN_Requestor_Target_Characterization_Level_One"
    conf = CmnProbeFactoryConfig(
        groups=[f"{group_name}@(CMN=0)"],
    )

    probe = CmnProbe(
        conf,
        cmn_multi_cmn_db,
        capture_data=True,
        base_csv_dir=None,
        perf_factory_instance=_CmnPerfFactory(),
    )

    assert probe.used_cmns == (0,)
    for metric in probe.group_data[group_name]["topdown_metrics_values"].values():
        assert set(metric) == {CmnLocation(0)}


def test_topdown_group_rejects_non_global_location(cmn_db: CmnDatabase) -> None:
    conf = CmnProbeFactoryConfig(
        groups=["CMN_Requestor_Target_Characterization_Level_One@(CMN=0;XP=0x200)"],
    )

    with pytest.raises(ValueError, match="Topdown metrics only support CMN-level location filters"):
        CmnProbe(
            conf,
            cmn_db,
            capture_data=True,
            base_csv_dir=None,
            perf_factory_instance=_CmnPerfFactory(),
        )


def test_topdown_metric_rejects_non_global_location(cmn_db: CmnDatabase) -> None:
    conf = CmnProbeFactoryConfig(
        metrics=["cmn_bw_rnf@(CMN=0;XP=0x200)"],
    )

    with pytest.raises(ValueError, match="Topdown metrics only support CMN-level location filters"):
        CmnProbe(
            conf,
            cmn_db,
            capture_data=True,
            base_csv_dir=None,
            perf_factory_instance=_CmnPerfFactory(),
        )


def test_node_location_filter_rejected_for_port_metric(cmn_db: CmnDatabase) -> None:
    metric_name = "cmn_rnf_txreq_rate"

    conf = CmnProbeFactoryConfig(
        metrics=[f"{metric_name}@(CMN=0;Node=0x0)"],
    )

    with pytest.raises(ValueError, match="Node location filter is not valid for port metric"):
        CmnProbe(
            conf,
            cmn_db,
            capture_data=True,
            base_csv_dir=None,
            perf_factory_instance=_CmnPerfFactory(),
        )


def test_node_location_filter_rejected_for_port_metric_group(cmn_db: CmnDatabase) -> None:
    group_name = "RNF_CHI_Egress_Traffic"

    conf = CmnProbeFactoryConfig(
        groups=[f"{group_name}@(CMN=0;Node=0x0)"],
    )

    with pytest.raises(ValueError, match="Node location filter is not valid for port metric"):
        CmnProbe(
            conf,
            cmn_db,
            capture_data=True,
            base_csv_dir=None,
            perf_factory_instance=_CmnPerfFactory(),
        )


def test_start_capture_refreshes_cmn_mux_interval_before_thread_func(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_dir = Path(__file__).resolve().parent
    fixtures_dir = base_dir / "fixtures"
    with (fixtures_dir / "topology.json").open(encoding="utf-8") as f:
        topology_json = load(f)
    with (telemetry_probe_specifications_dir("cmn") / "cmn_700_r0p0_pmu.json").open(
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
