# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Remove metrics from a CPU telemetry specification while keeping it consistent.

Used by ``scripts/derive_cpu_spec.py`` (offline) and by the platform adaptation layer
(:mod:`topdown_tool.cpu_probe.platform_adaptation`) at runtime. Removing a metric also:

* removes it from metric groups, and drops groups that become empty;
* removes empty groups from the methodology stages;
* replaces removed decision-tree nodes by their children, so the rest of the tree stays
  reachable.
"""

import copy
from typing import Any, Dict, Iterable, List, Optional, Set

from topdown_tool.cpu_probe.cpu_model import TelemetrySpecification

SpecDict = Dict[str, Any]


def prune_spec(  # pylint: disable=too-many-locals
    spec: SpecDict, events: Optional[Set[str]] = None
) -> List[str]:
    """Make ``spec`` consistent after metrics (and optionally events) were removed.

    ``spec["metrics"]`` must already contain only the metrics to keep. The function edits
    ``spec`` in place.

    Args:
        spec: Specification as a JSON-compatible dict.
        events: When given, the event names to keep; function groups and decision-tree sample
            events are filtered to these.

    Returns:
        Human-readable report lines describing the changes.
    """
    report: List[str] = []
    metrics = spec["metrics"]
    groups = spec["groups"]

    if events is not None:
        for group in groups.get("function", {}).values():
            if group.get("events") is not None:
                group["events"] = [e for e in group["events"] if e in events]
        groups["function"] = {
            name: group
            for name, group in groups.get("function", {}).items()
            if group.get("events") or group.get("metrics")
        }

    metric_groups: Dict[str, Any] = {}
    for name, group in groups.get("metrics", {}).items():
        kept = [m for m in group.get("metrics") or [] if m in metrics]
        if kept:
            group["metrics"] = kept
            metric_groups[name] = group
        else:
            report.append(f"dropped empty metric group: {name}")
    groups["metrics"] = metric_groups

    topdown = spec["methodologies"]["topdown_methodology"]
    grouping = topdown.get("metric_grouping", {})
    for stage, names in grouping.items():
        grouping[stage] = [name for name in names if name in metric_groups]

    tree = topdown["decision_tree"]
    nodes = {node["name"]: node for node in tree["metrics"]}
    removed = {name for name in nodes if name not in metrics}

    def expand(items: Iterable[str], seen: Set[str]) -> List[str]:
        result: List[str] = []
        for item in items:
            if item in removed:
                if item in seen:
                    continue
                child_items = nodes[item]["next_items"] if item in nodes else []
                result.extend(expand(child_items, seen | {item}))
            elif item in metrics or item in metric_groups:
                result.append(item)
        return list(dict.fromkeys(result))

    new_nodes = []
    for node in tree["metrics"]:
        if node["name"] in removed:
            continue
        new_node = copy.deepcopy(node)
        new_node["next_items"] = [
            item for item in expand(node["next_items"], {node["name"]}) if item != node["name"]
        ]
        if events is not None:
            new_node["sample_events"] = [e for e in node.get("sample_events", []) if e in events]
        new_nodes.append(new_node)
    tree["metrics"] = new_nodes
    tree["root_nodes"] = [name for name in expand(tree["root_nodes"], set()) if name in metrics]

    lifted = sorted(removed)
    if lifted:
        report.append("tree nodes replaced by their children: " + ", ".join(lifted))
    return report


def remove_metrics(
    spec: TelemetrySpecification, names: Iterable[str]
) -> TelemetrySpecification:
    """Return a copy of ``spec`` without the metrics in ``names``.

    Names that are not in the specification are ignored. Returns ``spec`` itself when nothing
    is removed.
    """
    to_remove = set(names) & set(spec.metrics)
    if not to_remove:
        return spec
    data = spec.model_dump(by_alias=True)
    data["metrics"] = {k: v for k, v in data["metrics"].items() if k not in to_remove}
    prune_spec(data)
    return TelemetrySpecification.model_validate(data)


__all__ = ["prune_spec", "remove_metrics"]
