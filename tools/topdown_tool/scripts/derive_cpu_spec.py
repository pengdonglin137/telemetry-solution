#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Derive a CPU telemetry specification for a core that has no official one.

Arm publishes telemetry specifications (events, metrics and the topdown decision tree) for a
subset of CPUs. Many Android SoCs use cores without one (e.g. Cortex-A520/A720/X4). Those cores
usually share their PMU event encoding and topdown methodology with a close sibling that *does*
have a specification (C1-Nano, Cortex-A725 and Cortex-X925 respectively).

This script builds a specification for the target core by:

1. taking the sibling ("base") specification,
2. keeping only the events that the target core implements, according to the per-core PMU event
   list published in https://github.com/ARM-software/data (``pmu/<core>.json``), and rejecting
   any event whose code differs between the two,
3. dropping metrics that need unavailable events (optionally replacing them with a same-name
   metric from a fallback specification whose events are all available),
4. pruning the decision tree: removed nodes are replaced by their children so the remaining
   subtree stays reachable,
5. validating the result with the topdown-tool specification loader.

The output is marked ``quality: Development``. It is not an official Arm specification; verify
``num_slots`` on hardware (see ``data/pmu/cpu/specifications/derived/README.md``).

Example::

    uv run python scripts/derive_cpu_spec.py \\
        --base ../../data/pmu/cpu/specifications/cortex/cortex_a725_r0p0_pmu.json \\
        --events cortex-a720.json --product-name Cortex-A720 --part-num 0xd81 \\
        -o ../../data/pmu/cpu/specifications/derived/cortex_a720_derived_pmu.json
"""

import argparse
import copy
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

ARM_DATA_URL = "https://raw.githubusercontent.com/ARM-software/data/master/pmu/{}.json"

Spec = Dict[str, Any]


def _code(value: Any) -> int:
    return int(value, 16) if isinstance(value, str) else int(value)


def load_json(source: str) -> Any:
    """Load JSON from a path, an http(s) URL or an ARM-software/data core name."""
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=30) as response:  # nosec - user supplied
            return json.load(response)
    path = Path(source)
    if not path.exists() and re.fullmatch(r"[\w.-]+", source):
        return load_json(ARM_DATA_URL.format(source))
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_core_events(source: str) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """Return ``{event name: event}`` from an ARM-software/data PMU JSON and its header."""
    data = load_json(source)
    events = {event["name"]: event for event in data["events"] if "name" in event}
    header = {key: value for key, value in data.items() if key != "events"}
    return events, header


def parse_aliases(values: Iterable[str]) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for value in values:
        base_name, sep, core_name = value.partition("=")
        if not sep or not base_name or not core_name:
            raise SystemExit(f"Invalid --alias {value!r}; expected BASE_EVENT=CORE_EVENT")
        aliases[base_name] = core_name
    return aliases


def parse_overrides(values: Iterable[str]) -> Dict[str, str]:
    overrides: Dict[str, str] = {}
    for value in values:
        name, sep, formula = value.partition("=")
        if not sep or not name.strip() or not formula.strip():
            raise SystemExit(f"Invalid --override-metric {value!r}; expected METRIC=FORMULA")
        overrides[name.strip()] = formula.strip()
    return overrides


class SpecBuilder:  # pylint: disable=too-many-instance-attributes
    """Build the derived specification and keep a human readable report."""

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def __init__(
        self,
        base: Spec,
        core_events: Dict[str, Dict[str, Any]],
        aliases: Dict[str, str],
        fallbacks: List[Spec],
        drop_metrics: Iterable[str] = (),
    ) -> None:
        self.base = base
        self.core_events = core_events
        self.aliases = aliases
        self.fallbacks = fallbacks
        self.drop_metrics = set(drop_metrics)
        unknown = self.drop_metrics - set(base["metrics"])
        if unknown:
            raise SystemExit(f"--drop-metric: unknown metric(s) {sorted(unknown)}")
        self.report: List[str] = []
        self.available: Set[str] = set()
        self.events: Dict[str, Any] = {}
        self.metrics: Dict[str, Any] = {}

    # Events ----------------------------------------------------------------
    def build_events(self) -> None:
        core_by_code = {_code(event["code"]): name for name, event in self.core_events.items()}
        rejected: List[str] = []
        for name, event in self.base["events"].items():
            core_name = self.aliases.get(name, name)
            core_event = self.core_events.get(core_name)
            if core_event is None:
                continue
            new_event = copy.deepcopy(event)
            base_code = _code(event["code"])
            core_code = _code(core_event["code"])
            if name in self.aliases:
                new_event["code"] = f"0x{core_code:04x}"
                self.report.append(
                    f"alias: {name} -> {core_name} (code 0x{base_code:x} -> 0x{core_code:x})"
                )
            elif base_code != core_code:
                rejected.append(f"{name} (base 0x{base_code:x}, core 0x{core_code:x})")
                continue
            self.events[name] = new_event
            self.available.add(name)

        used_core_names = {self.aliases.get(name, name) for name in self.events}
        extra = 0
        for core_name, core_event in sorted(
            self.core_events.items(), key=lambda kv: _code(kv[1]["code"])
        ):
            if core_name in used_core_names or core_name in self.events:
                continue
            code = _code(core_event["code"])
            if core_by_code.get(code) != core_name:
                continue
            architectural = bool(core_event.get("architectural", False))
            self.events[core_name] = {
                "code": f"0x{code:04x}",
                "title": core_name.replace("_", " ").capitalize(),
                "description": core_event.get("description", core_name),
                "accesses": ["PMU"],
                "architecture_defined": architectural,
                "product_defined": not architectural,
            }
            extra += 1
        if rejected:
            self.report.append("rejected (code mismatch): " + ", ".join(rejected))
        self.report.append(
            f"events: {len(self.available)} kept from base, {extra} added from core event list"
        )

    # Metrics ---------------------------------------------------------------
    def _metric_usable(self, metric: Dict[str, Any], known_metrics: Set[str]) -> bool:
        if any(event not in self.available for event in metric.get("events", [])):
            return False
        if any(event not in self.available for event in metric.get("sample_events", [])):
            return False
        return all(name in known_metrics for name in metric.get("metrics", []))

    def build_metrics(self, slots: Optional[Tuple[int, int]]) -> None:
        candidates: Dict[str, Tuple[Dict[str, Any], str]] = {}
        for name, metric in self.base["metrics"].items():
            if name in self.drop_metrics:
                continue
            candidates[name] = (metric, "base")

        # Resolve iteratively so metrics depending on other metrics are handled.
        known: Set[str] = set()
        changed = True
        while changed:
            changed = False
            for name, (metric, _origin) in candidates.items():
                if name not in known and self._metric_usable(metric, known | set(candidates)):
                    known.add(name)
                    changed = True

        dropped: List[str] = []
        for name, (metric, _origin) in candidates.items():
            if name in known:
                self.metrics[name] = copy.deepcopy(metric)
                continue
            replacement = self._fallback_metric(name, known)
            if replacement is not None:
                self.metrics[name] = replacement
                continue
            dropped.append(name)

        if slots is not None:
            self._rewrite_slots(*slots)

        if self.drop_metrics:
            self.report.append(
                "dropped on request (--drop-metric): " + ", ".join(sorted(self.drop_metrics))
            )
        if dropped:
            self.report.append(f"dropped metrics ({len(dropped)}): " + ", ".join(sorted(dropped)))
        self.report.append(f"metrics: {len(self.metrics)}/{len(self.base['metrics'])} kept")

    def apply_overrides(self, overrides: Dict[str, str]) -> None:
        """Replace metric formulas; the event list is recomputed from the formula."""
        for name, formula in overrides.items():
            metric = self.metrics.get(name)
            if metric is None:
                raise SystemExit(f"--override-metric: metric {name!r} is not in the derived spec")
            symbols = set(re.findall(r"[A-Za-z_]\w*", formula))
            unknown = sorted(s for s in symbols if s not in self.events)
            if unknown:
                raise SystemExit(f"--override-metric {name}: unknown events {unknown}")
            metric["formula"] = formula
            metric["events"] = sorted(symbols)
            metric["sample_events"] = [e for e in metric.get("sample_events", []) if e in symbols]
            metric["description"] = (
                metric["description"].rstrip()
                + " Derived specification: formula adjusted for this core, see"
                " data/pmu/cpu/specifications/derived/README.md."
            )
            self.report.append(f"override: {name} = {formula}")

    def _fallback_metric(self, name: str, known: Set[str]) -> Optional[Dict[str, Any]]:
        for index, fallback in enumerate(self.fallbacks):
            metric = fallback["metrics"].get(name)
            if metric is None or not self._metric_usable(metric, known):
                continue
            # Fallback metrics may reference events missing from the base event table.
            for event in metric.get("events", []) + metric.get("sample_events", []):
                if event not in self.events and event in fallback["events"]:
                    self.events[event] = copy.deepcopy(fallback["events"][event])
            product = fallback["product_configuration"]["product_name"]
            self.report.append(
                f"fallback metric from {product} (#{index}): {name} = {metric['formula']}"
            )
            return copy.deepcopy(metric)
        return None

    def _rewrite_slots(self, old: int, new: int) -> None:
        if old == new:
            return
        pattern_a = re.compile(rf"\b{old}\s*\*\s*CPU_CYCLES\b")
        pattern_b = re.compile(rf"\bCPU_CYCLES\s*\*\s*{old}\b")
        for name, metric in self.metrics.items():
            if not any(event.startswith("STALL_SLOT") for event in metric.get("events", [])):
                continue
            formula = pattern_a.sub(f"{new} * CPU_CYCLES", metric["formula"])
            formula = pattern_b.sub(f"CPU_CYCLES * {new}", formula)
            if formula != metric["formula"]:
                self.report.append(f"slots {old}->{new}: {name} = {formula}")
                metric["formula"] = formula

    # Groups / methodology ----------------------------------------------------
    def build_groups(self) -> Dict[str, Any]:
        groups = copy.deepcopy(self.base["groups"])
        for group in groups.get("function", {}).values():
            if group.get("events") is not None:
                group["events"] = [e for e in group["events"] if e in self.events]
        groups["function"] = {
            name: group
            for name, group in groups.get("function", {}).items()
            if group.get("events") or group.get("metrics")
        }
        metric_groups = {}
        for name, group in groups.get("metrics", {}).items():
            metrics = [m for m in group.get("metrics") or [] if m in self.metrics]
            if metrics:
                group["metrics"] = metrics
                metric_groups[name] = group
            else:
                self.report.append(f"dropped empty metric group: {name}")
        groups["metrics"] = metric_groups
        return groups

    def build_methodologies(self, metric_groups: Set[str]) -> Dict[str, Any]:
        methodologies = copy.deepcopy(self.base["methodologies"])
        topdown = methodologies["topdown_methodology"]
        grouping = topdown.get("metric_grouping", {})
        for stage, names in grouping.items():
            grouping[stage] = [name for name in names if name in metric_groups]

        tree = topdown["decision_tree"]
        nodes = {node["name"]: node for node in tree["metrics"]}
        removed = {name for name in nodes if name not in self.metrics}

        def expand(items: Iterable[str], seen: Set[str]) -> List[str]:
            result: List[str] = []
            for item in items:
                if item in removed:
                    if item in seen:
                        continue
                    child_items = nodes[item]["next_items"] if item in nodes else []
                    result.extend(expand(child_items, seen | {item}))
                elif item in self.metrics or item in metric_groups:
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
            new_node["sample_events"] = [
                e for e in node.get("sample_events", []) if e in self.events
            ]
            new_nodes.append(new_node)
        tree["metrics"] = new_nodes
        tree["root_nodes"] = expand(tree["root_nodes"], set())
        tree["root_nodes"] = [name for name in tree["root_nodes"] if name in self.metrics]
        lifted = sorted(removed & set(nodes))
        if lifted:
            self.report.append("tree nodes replaced by their children: " + ", ".join(lifted))
        return methodologies


# pylint: disable=too-many-locals
def derive(args: argparse.Namespace) -> Tuple[Spec, List[str]]:
    base = load_json(args.base)
    core_events, header = load_core_events(args.events)
    fallbacks = [load_json(path) for path in args.fallback]
    builder = SpecBuilder(
        base, core_events, parse_aliases(args.alias), fallbacks, drop_metrics=args.drop_metric
    )

    base_conf = base["product_configuration"]
    base_slots = int(base_conf.get("num_slots", 0))
    num_slots = args.num_slots if args.num_slots is not None else base_slots
    if num_slots != base_slots and not args.rewrite_slots:
        raise SystemExit(
            f"--num-slots {num_slots} differs from the base spec ({base_slots}); "
            "pass --rewrite-slots to rewrite the topdown formulas."
        )

    builder.build_events()
    builder.build_metrics((base_slots, num_slots) if args.rewrite_slots else None)
    builder.apply_overrides(parse_overrides(args.override_metric))
    groups = builder.build_groups()
    methodologies = builder.build_methodologies(set(groups["metrics"]))

    product_conf = copy.deepcopy(base_conf)
    product_conf.update(
        {
            "product_name": args.product_name,
            "part_num": args.part_num,
            "major_revision": str(args.major_revision),
            "minor_revision": str(args.minor_revision),
            "num_slots": num_slots,
        }
    )
    architecture = header.get("architecture")
    if isinstance(architecture, str):
        product_conf["architecture"] = architecture.removesuffix("-a")

    base_doc = base.get("document", {})
    base_name = base_conf.get("product_name", "base")
    sources = f"{base_name} specification (sha1 {base_doc.get('sha1', 'n/a')})"
    if fallbacks:
        sources += ", fallback metrics from " + ", ".join(
            f["product_configuration"]["product_name"] for f in fallbacks
        )
    document = {
        "timestamp": datetime.now(timezone.utc).strftime("%d %b %H:%M:%S %Y"),
        "copyright": base_doc.get("copyright", "Copyright Arm Ltd."),
        "confidential": False,
        "quality": "Development",
        "license": base_doc.get("license", "Apache-2.0"),
        "description": (
            f"Derived telemetry specification for {args.product_name}. Generated by "
            f"scripts/derive_cpu_spec.py from the {sources} and the {header.get('cpu', 'core')} "
            "PMU event list (ARM-software/data). Not an official Arm release."
        ),
        "revision": f"derived-from:{Path(args.base).name}",
    }

    spec: Spec = {"$schema": base.get("$schema", "v1.2.schema.json"), "document": document}
    spec["product_configuration"] = product_conf
    spec["events"] = builder.events
    spec["metrics"] = builder.metrics
    spec["groups"] = groups
    spec["methodologies"] = methodologies
    return spec, builder.report


def validate(path: Path, schema_dir: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    # pylint: disable=import-outside-toplevel
    from topdown_tool.cpu_probe.cpu_model import TelemetrySpecification

    TelemetrySpecification.load_from_json_file(path, schema_dir, duplicate_policy="error")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--base", required=True, help="Sibling telemetry specification JSON.")
    parser.add_argument(
        "--events",
        required=True,
        help="Target core PMU event list: path, URL, or ARM-software/data name (e.g. cortex-a720).",
    )
    parser.add_argument("--product-name", required=True)
    parser.add_argument("--part-num", required=True, help="MIDR part number, e.g. 0xd81.")
    parser.add_argument("--major-revision", type=int, default=0)
    parser.add_argument("--minor-revision", type=int, default=0)
    parser.add_argument("--num-slots", type=int, help="Pipeline slots (default: from base).")
    parser.add_argument(
        "--rewrite-slots",
        action="store_true",
        help="Rewrite 'N * CPU_CYCLES' in STALL_SLOT formulas when --num-slots differs.",
    )
    parser.add_argument(
        "--alias",
        action="append",
        default=[],
        metavar="BASE_EVENT=CORE_EVENT",
        help="Use CORE_EVENT (and its code) for BASE_EVENT. Only for identical semantics.",
    )
    parser.add_argument(
        "--fallback",
        action="append",
        default=[],
        help="Additional spec providing same-name metrics when the base one is unusable.",
    )
    parser.add_argument(
        "--drop-metric",
        action="append",
        default=[],
        metavar="METRIC",
        help="Remove a base metric whose formula does not hold on the target core.",
    )
    parser.add_argument(
        "--override-metric",
        action="append",
        default=[],
        metavar="METRIC=FORMULA",
        help="Replace a metric formula (e.g. when event semantics differ on the target core).",
    )
    parser.add_argument("--schema-dir", type=Path, help="Schema directory used for validation.")
    parser.add_argument("--output", "-o", type=Path, required=True)
    args = parser.parse_args(argv)

    spec, report = derive(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(spec, handle, indent=4)
        handle.write("\n")

    schema_dir = args.schema_dir or Path(args.base).resolve().parents[2] / "schemas"
    validate(args.output, schema_dir)

    print(f"Wrote {args.output} ({args.product_name}, num_slots={spec['product_configuration']['num_slots']})")
    for line in report:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
