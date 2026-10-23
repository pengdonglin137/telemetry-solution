# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Tests for scripts/derive_cpu_spec.py and the derived specifications shipped with the tool."""

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from topdown_tool.common.telemetry_paths import (
    telemetry_probe_mapping_file,
    telemetry_probe_schemas_dir,
    telemetry_probe_specifications_dir,
)
from topdown_tool.cpu_probe.cpu_model import TelemetrySpecification

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "derive_cpu_spec.py"
SPECS = telemetry_probe_specifications_dir("cpu")
BASE = SPECS / "cortex" / "cortex_a725_r0p0_pmu.json"


@pytest.fixture(scope="module")
def derive_module():
    spec = importlib.util.spec_from_file_location("derive_cpu_spec", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def base_spec() -> Dict[str, Any]:
    return json.loads(BASE.read_text(encoding="utf-8"))


def _core_events(base: Dict[str, Any], drop=(), rename=None, recode=None) -> Dict[str, Any]:
    """Build an ARM-software/data style event list from the base spec."""
    rename = rename or {}
    recode = recode or {}
    events: List[Dict[str, Any]] = []
    for name, event in base["events"].items():
        if name in drop:
            continue
        code = recode.get(name, int(event["code"], 16))
        events.append({"code": code, "name": rename.get(name, name), "architectural": True})
    return {"_type": "Events", "cpu": "Test-Core", "architecture": "armv9.2-a", "events": events}


def _run(derive_module, tmp_path: Path, core: Dict[str, Any], *extra: str) -> Dict[str, Any]:
    events_path = tmp_path / "core.json"
    events_path.write_text(json.dumps(core), encoding="utf-8")
    output = tmp_path / "out.json"
    argv = [
        "--base", str(BASE), "--events", str(events_path),
        "--product-name", "Test-Core", "--part-num", "0xabc",
        "--schema-dir", str(telemetry_probe_schemas_dir("cpu")),
        "-o", str(output), *extra,
    ]  # fmt: skip
    assert derive_module.main(argv) == 0
    return json.loads(output.read_text(encoding="utf-8"))


def _assert_tree_consistent(spec: Dict[str, Any]) -> None:
    tree = spec["methodologies"]["topdown_methodology"]["decision_tree"]
    groups = set(spec["groups"]["metrics"])
    for name in tree["root_nodes"]:
        assert name in spec["metrics"]
    for node in tree["metrics"]:
        assert node["name"] in spec["metrics"]
        for item in node["next_items"]:
            assert item in spec["metrics"] or item in groups, (node["name"], item)


def test_identical_core_keeps_everything(derive_module, tmp_path, base_spec):
    spec = _run(derive_module, tmp_path, _core_events(base_spec))

    assert set(spec["metrics"]) == set(base_spec["metrics"])
    assert spec["document"]["quality"] == "Development"
    assert spec["product_configuration"]["product_name"] == "Test-Core"
    assert spec["product_configuration"]["part_num"] == "0xabc"
    assert spec["product_configuration"]["num_slots"] == 5


def test_missing_event_drops_metric_and_lifts_tree(derive_module, tmp_path, base_spec):
    spec = _run(derive_module, tmp_path, _core_events(base_spec, drop={"STALL_FRONTEND_FLOW"}))

    assert "STALL_FRONTEND_FLOW" not in spec["events"]
    assert "frontend_core_flow_bound" not in spec["metrics"]
    tree = spec["methodologies"]["topdown_methodology"]["decision_tree"]
    nodes = {node["name"]: node for node in tree["metrics"]}
    assert "frontend_core_flow_bound" not in nodes
    # The removed node's children are attached to its parent.
    assert "Branch_Effectiveness" in nodes["frontend_core_bound"]["next_items"]
    _assert_tree_consistent(spec)


def test_code_mismatch_rejects_event(derive_module, tmp_path, base_spec):
    core = _core_events(base_spec, recode={"STALL_FRONTEND_FLOW": 0x9999})
    spec = _run(derive_module, tmp_path, core)

    # The event table lists the core's own encoding, but metrics written for the base
    # encoding are not trusted.
    assert spec["events"]["STALL_FRONTEND_FLOW"]["code"] == "0x9999"
    assert "frontend_core_flow_bound" not in spec["metrics"]


def test_alias_keeps_metric_with_core_code(derive_module, tmp_path, base_spec):
    core = _core_events(
        base_spec, rename={"STALL_FRONTEND_FLOW": "CORE_FLOW"}, recode={"STALL_FRONTEND_FLOW": 0xE0}
    )
    spec = _run(derive_module, tmp_path, core, "--alias", "STALL_FRONTEND_FLOW=CORE_FLOW")

    assert spec["events"]["STALL_FRONTEND_FLOW"]["code"] == "0x00e0"
    assert "frontend_core_flow_bound" in spec["metrics"]


def test_drop_and_override_metrics(derive_module, tmp_path, base_spec):
    spec = _run(
        derive_module,
        tmp_path,
        _core_events(base_spec),
        "--drop-metric", "frontend_cache_l1i_bound",
        "--override-metric", "backend_mem_cache_bound=STALL_BACKEND_L1D / STALL_BACKEND_MEMBOUND * 100",
    )  # fmt: skip

    assert "frontend_cache_l1i_bound" not in spec["metrics"]
    metric = spec["metrics"]["backend_mem_cache_bound"]
    assert metric["formula"] == "STALL_BACKEND_L1D / STALL_BACKEND_MEMBOUND * 100"
    assert metric["events"] == ["STALL_BACKEND_L1D", "STALL_BACKEND_MEMBOUND"]
    assert "derived/README.md" in metric["description"]
    _assert_tree_consistent(spec)


def test_override_with_unknown_event_fails(derive_module, tmp_path, base_spec):
    with pytest.raises(SystemExit, match="unknown events"):
        _run(
            derive_module,
            tmp_path,
            _core_events(base_spec),
            "--override-metric", "backend_mem_cache_bound=NOT_AN_EVENT / CPU_CYCLES",
        )  # fmt: skip


def test_slot_count_rewrite(derive_module, tmp_path, base_spec):
    with pytest.raises(SystemExit, match="--rewrite-slots"):
        _run(derive_module, tmp_path, _core_events(base_spec), "--num-slots", "4")

    spec = _run(
        derive_module, tmp_path, _core_events(base_spec), "--num-slots", "4", "--rewrite-slots"
    )
    assert spec["product_configuration"]["num_slots"] == 4
    assert spec["metrics"]["backend_bound"]["formula"] == "STALL_SLOT_BACKEND / (4 * CPU_CYCLES) * 100"
    assert "CPU_CYCLES * 4" in spec["metrics"]["retiring"]["formula"]


# Shipped derived specifications --------------------------------------------------------


DERIVED = {
    "0x41d80": ("cortex_a520_derived_pmu", "Cortex-A520", "0xd80", 3),
    "0x41d81": ("cortex_a720_derived_pmu", "Cortex-A720", "0xd81", 5),
    "0x41d82": ("cortex_x4_derived_pmu", "Cortex-X4", "0xd82", 10),
}


@pytest.mark.parametrize("cpu_id", sorted(DERIVED))
def test_shipped_derived_specs_are_mapped_and_valid(cpu_id):
    file_name, product, part_num, slots = DERIVED[cpu_id]
    mapping = json.loads(telemetry_probe_mapping_file("cpu").read_text(encoding="utf-8"))
    assert mapping[cpu_id]["name"] == f"derived/{file_name}"

    path = SPECS / "derived" / f"{file_name}.json"
    spec = TelemetrySpecification.load_from_json_file(
        path, telemetry_probe_schemas_dir("cpu"), duplicate_policy="error"
    )
    assert spec.product_configuration.product_name == product
    assert spec.product_configuration.part_num == part_num

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["document"]["quality"] == "Development"
    assert raw["product_configuration"]["num_slots"] == slots
    assert f"{slots} * CPU_CYCLES" in raw["metrics"]["backend_bound"]["formula"]
    _assert_tree_consistent(raw)
