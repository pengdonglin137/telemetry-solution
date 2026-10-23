# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Tests for the platform adaptation layer (data/pmu/cpu/platforms)."""

import json
from pathlib import Path

import pytest

from topdown_tool.common.telemetry_paths import (
    telemetry_probe_mapping_file,
    telemetry_probe_platforms_dir,
    telemetry_probe_schemas_dir,
    telemetry_probe_specifications_dir,
)
from topdown_tool.cpu_probe.cpu_detector import (
    CpuDetector,
    PlatformInfo,
    _features_from_cpuinfo,
)
from topdown_tool.cpu_probe.cpu_model import TelemetrySpecification
from topdown_tool.cpu_probe.platform_adaptation import (
    PlatformAdaptation,
    PlatformDataError,
    load_profiles,
)
from topdown_tool.cpu_probe.spec_pruning import remove_metrics

PLATFORMS = telemetry_probe_platforms_dir("cpu")
SPECS = telemetry_probe_specifications_dir("cpu")
SCHEMAS = telemetry_probe_schemas_dir("cpu")

XRING_O3 = PlatformInfo(
    android_properties={
        "ro.soc.manufacturer": "XRing",
        "ro.soc.model": "O3",
        "ro.board.platform": "xring_o3_asic_cdc",
    },
    dt_compatible=("XiaoMi,Xring_o3-o801-auto",),
)
# Snapdragon 8 Gen 3 test device (adapted before the adaptation layer existed).
SM8650 = PlatformInfo(android_properties={"ro.soc.model": "SM8650"})

# Features reported by the XRing O3 cores (no SME) and by an SME2-capable core.
NO_SME = frozenset("fp asimd sve sve2 i8mm bf16".split())
WITH_SME = NO_SME | {"sme", "sme2"}


def _load(relative: str) -> TelemetrySpecification:
    return TelemetrySpecification.load_from_json_file(SPECS / relative, SCHEMAS)


def _all_shipped_specs():
    mapping = json.loads(telemetry_probe_mapping_file("cpu").read_text(encoding="utf-8"))
    seen = {}
    for cpu_id, entry in mapping.items():
        seen.setdefault(entry["name"], int(cpu_id, 16) & 0xFFFFF)
    return sorted(seen.items())


def _cpu_id(midr_short: int) -> int:
    # mapping.json keys are either short ids (0x41d8b) or full MIDRs (0x411fd8b2).
    if midr_short > 0xFFFFF:
        return CpuDetector.cpu_id(midr_short)
    return midr_short


# Shipped data ----------------------------------------------------------------------------


def test_shipped_platform_data_loads() -> None:
    adaptation = PlatformAdaptation.load(PLATFORMS, XRING_O3)
    assert adaptation.profile is not None
    assert adaptation.profile.name == "XRing O3"
    assert adaptation.use_cycle_counter is True
    assert [rule.feature for rule in adaptation.feature_rules] == ["sme"]
    assert load_profiles(PLATFORMS / "soc")


@pytest.mark.parametrize("name, cpu_id", _all_shipped_specs())
def test_no_profile_and_no_missing_feature_changes_nothing(name, cpu_id) -> None:
    # The adaptation layer must be a no-op on platforms without a profile when the cores
    # have every feature: this is the behaviour before the layer existed.
    adaptation = PlatformAdaptation.load(PLATFORMS, SM8650)
    assert adaptation.profile is None
    assert adaptation.use_cycle_counter is False
    spec = _load(name + ".json")
    assert adaptation.adapt(spec, _cpu_id(cpu_id), WITH_SME) is spec
    assert adaptation.adapt(spec, _cpu_id(cpu_id), None) is spec


@pytest.mark.parametrize(
    "name", ["derived/cortex_x4_derived_pmu", "derived/cortex_a720_derived_pmu", "derived/cortex_a520_derived_pmu"]
)
def test_sm8650_specs_unchanged_with_real_features(name) -> None:
    # SM8650 cores report no 'sme'; their specs contain no SME events, so nothing changes.
    adaptation = PlatformAdaptation.load(PLATFORMS, SM8650)
    spec = _load(name + ".json")
    assert adaptation.adapt(spec, 0x41D80, NO_SME) is spec


def test_sme_rule_hides_cme_metrics_on_cores_without_sme() -> None:
    adaptation = PlatformAdaptation.load(PLATFORMS, XRING_O3)
    spec = _load("lumex/arm_c1_ultra_r0p0_pmu.json")

    adapted = adaptation.adapt(spec, 0x41D8C, NO_SME)

    removed = set(spec.metrics) - set(adapted.metrics)
    assert "backend_core_cme_bound" in removed and "sme_percentage" in removed
    assert len(removed) == 14
    assert "Topdown_CME" not in adapted.groups.metrics
    assert "Topdown_CME" not in adapted.methodologies.topdown_methodology.metric_grouping.stage_1
    # Same core with SME keeps everything.
    assert adaptation.adapt(spec, 0x41D8C, WITH_SME) is spec


def test_xring_profile_only_touches_c1_pro() -> None:
    adaptation = PlatformAdaptation.load(PLATFORMS, XRING_O3)
    pro = _load("lumex/arm_c1_pro_r1p2_pmu.json")
    ultra = _load("lumex/arm_c1_ultra_r0p0_pmu.json")

    pro_adapted = adaptation.adapt(pro, 0x41D8B, WITH_SME)
    ultra_adapted = adaptation.adapt(ultra, 0x41D8C, WITH_SME)

    assert set(pro.metrics) - set(pro_adapted.metrics) == {
        "backend_cache_l1d_bound",
        "backend_cache_l2d_bound",
    }
    assert ultra_adapted is ultra
    # The parent node keeps the groups that were below the removed nodes.
    nodes = {n.name: n for n in pro_adapted.methodologies.topdown_methodology.decision_tree.metrics}
    assert "L1D_Cache_Effectiveness" in nodes["backend_mem_cache_bound"].next_items


@pytest.mark.parametrize(
    "info, matches",
    [
        (XRING_O3, True),
        (PlatformInfo(android_properties={"ro.soc.manufacturer": "xring", "ro.soc.model": "o3"}), True),
        (PlatformInfo(android_properties={"ro.soc.manufacturer": "XRing", "ro.soc.model": "O1"}), False),
        (SM8650, False),
        (PlatformInfo(), False),
    ],
)
def test_xring_profile_matching(info, matches) -> None:
    profile = next(p for p in load_profiles(PLATFORMS / "soc") if p.name == "XRing O3")
    assert profile.matches(info) is matches


# Loader behaviour -----------------------------------------------------------------------


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_profile_with_dt_compatible_prefix(tmp_path) -> None:
    _write(
        tmp_path / "soc" / "board.json",
        {"name": "Board", "match": {"dt_compatible": ["vendor,soc"]}, "cycle_counter": True},
    )
    info = PlatformInfo(dt_compatible=("Vendor,SoC-evb", "vendor,soc"))
    assert PlatformAdaptation.load(tmp_path, info).use_cycle_counter is True
    assert PlatformAdaptation.load(tmp_path, PlatformInfo(dt_compatible=("other",))).profile is None


@pytest.mark.parametrize(
    "data",
    [
        {"name": "x", "match": {}},
        {"name": "x", "match": {"android_properties": {"a": "b"}}, "typo": 1},
        {"name": "x", "match": {"android_properties": {"a": "b"}}, "cpus": {"zz": {}}},
    ],
)
def test_invalid_profiles_are_rejected(tmp_path, data) -> None:
    _write(tmp_path / "soc" / "bad.json", data)
    with pytest.raises(PlatformDataError):
        load_profiles(tmp_path / "soc")


def test_missing_platform_directory_is_noop(tmp_path) -> None:
    adaptation = PlatformAdaptation.load(tmp_path / "missing", XRING_O3)
    assert adaptation.profile is None and adaptation.feature_rules == ()


# Helpers -----------------------------------------------------------------------------------


def test_features_from_cpuinfo() -> None:
    cpuinfo = (
        "processor\t: 0\nFeatures\t: fp asimd sve\nCPU part\t: 0xd8b\n\n"
        "processor\t: 1\nFeatures\t: fp asimd sve sme\nCPU part\t: 0xd8c\n"
    )
    assert _features_from_cpuinfo(cpuinfo, 0) == {"fp", "asimd", "sve"}
    assert "sme" in _features_from_cpuinfo(cpuinfo, 1)
    assert _features_from_cpuinfo(cpuinfo, 5) is None


def test_remove_metrics_keeps_spec_valid() -> None:
    spec = _load("cortex/cortex_a725_r0p0_pmu.json")
    adapted = remove_metrics(spec, ["backend_core_bound", "not_a_metric"])
    tree = adapted.methodologies.topdown_methodology.decision_tree
    nodes = {n.name: n for n in tree.metrics}
    assert "backend_core_bound" not in adapted.metrics
    assert "backend_core_rename_bound" in nodes["backend_bound"].next_items
    assert remove_metrics(spec, ["not_a_metric"]) is spec
