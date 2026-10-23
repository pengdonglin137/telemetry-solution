# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Platform adaptation layer for CPU telemetry specifications.

Telemetry specifications describe a CPU core. Some SoCs integrate a core in a way that makes
part of its specification wrong or useless: an optional unit is absent (e.g. no SME2 unit), a
vendor driver reserves PMU counters, or an event behaves differently in that integration. Such
differences are described as data under ``data/pmu/cpu/platforms`` and applied here, so that
adapting a new SoC never changes the behaviour on SoCs that are already supported:

* ``features.json``: rules keyed on a CPU feature flag (Linux HWCAP name from
  ``/proc/cpuinfo``). When a core lacks the feature, metrics that need the listed events are
  removed. A rule only affects specifications that contain those events.
* ``soc/*.json``: one profile per SoC, matched on Android properties and/or device-tree
  ``compatible`` strings. Only a matching profile applies its adjustments. Without a match,
  specifications and capture are left unchanged.

Profile format::

    {
      "name": "XRing O3",
      "match": {
        "android_properties": {"ro.soc.manufacturer": "XRing", "ro.soc.model": "O3"},
        "dt_compatible": ["xiaomi,xring_o3"]
      },
      "cycle_counter": true,
      "cpus": {
        "0x41d8b": {"drop_metrics": ["backend_cache_l1d_bound"], "reason": "..."}
      }
    }

All ``match`` criteria that are present must hold (strings compared case-insensitively;
``dt_compatible`` matches if any listed entry equals or prefixes a device compatible string).
``cpus`` keys are CPU ids as used in ``mapping.json`` (implementer << 12 | part number).
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Set, Tuple, Union

from topdown_tool.cpu_probe.cpu_detector import PlatformInfo
from topdown_tool.cpu_probe.cpu_model import TelemetrySpecification
from topdown_tool.cpu_probe.spec_pruning import remove_metrics

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


@dataclass(frozen=True)
class FeatureRule:
    """Metrics that need ``events`` are removed on cores without ``feature``."""

    feature: str
    events: FrozenSet[str]
    description: str = ""


@dataclass(frozen=True)
class CpuAdjustment:
    """SoC-specific change for one core type."""

    drop_metrics: Tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class PlatformProfile:
    """Adjustments for one SoC."""

    name: str
    path: str
    android_properties: Mapping[str, str] = field(default_factory=dict)
    dt_compatible: Tuple[str, ...] = ()
    cycle_counter: bool = False
    cpus: Mapping[int, CpuAdjustment] = field(default_factory=dict)

    def matches(self, info: PlatformInfo) -> bool:
        """Return whether ``info`` satisfies every match criterion of the profile."""
        if not self.android_properties and not self.dt_compatible:
            return False
        for key, expected in self.android_properties.items():
            actual = info.android_properties.get(key)
            if actual is None or actual.strip().lower() != expected.strip().lower():
                return False
        if self.dt_compatible:
            device = [entry.lower() for entry in info.dt_compatible]
            wanted = [entry.lower() for entry in self.dt_compatible]
            if not any(dev.startswith(want) for want in wanted for dev in device):
                return False
        return True


class PlatformDataError(ValueError):
    """Raised when a platform data file is malformed."""


def _expect_keys(data: Mapping[str, Any], allowed: Set[str], where: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise PlatformDataError(f"{where}: unknown key(s) {sorted(unknown)}")


def _load_feature_rules(path: Path) -> Tuple[FeatureRule, ...]:
    if not path.is_file():
        return ()
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    _expect_keys(data, {"description", "rules"}, str(path))
    rules = []
    for index, rule in enumerate(data.get("rules", [])):
        where = f"{path} rule #{index}"
        _expect_keys(rule, {"feature", "events", "description"}, where)
        if not rule.get("feature") or not rule.get("events"):
            raise PlatformDataError(f"{where}: 'feature' and 'events' are required")
        rules.append(
            FeatureRule(
                feature=str(rule["feature"]),
                events=frozenset(rule["events"]),
                description=str(rule.get("description", "")),
            )
        )
    return tuple(rules)


def _load_profile(path: Path) -> PlatformProfile:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    _expect_keys(data, {"name", "description", "match", "cycle_counter", "cpus"}, str(path))
    match = data.get("match") or {}
    _expect_keys(match, {"android_properties", "dt_compatible"}, f"{path} match")
    cpus: Dict[int, CpuAdjustment] = {}
    for key, value in (data.get("cpus") or {}).items():
        where = f"{path} cpus[{key}]"
        _expect_keys(value, {"name", "drop_metrics", "reason"}, where)
        try:
            cpu_id = int(key, 16)
        except ValueError as exc:
            raise PlatformDataError(f"{where}: key must be a hex CPU id") from exc
        cpus[cpu_id] = CpuAdjustment(
            drop_metrics=tuple(value.get("drop_metrics", [])),
            reason=str(value.get("reason", "")),
        )
    profile = PlatformProfile(
        name=str(data.get("name") or path.stem),
        path=str(path),
        android_properties=dict(match.get("android_properties") or {}),
        dt_compatible=tuple(match.get("dt_compatible") or ()),
        cycle_counter=bool(data.get("cycle_counter", False)),
        cpus=cpus,
    )
    if not profile.android_properties and not profile.dt_compatible:
        raise PlatformDataError(f"{path}: 'match' needs android_properties or dt_compatible")
    return profile


def load_profiles(directory: PathLike) -> Tuple[PlatformProfile, ...]:
    """Load every SoC profile under ``directory`` (sorted by file name)."""
    root = Path(directory)
    if not root.is_dir():
        return ()
    return tuple(_load_profile(path) for path in sorted(root.glob("*.json")))


class PlatformAdaptation:
    """Adjust specifications and capture settings for the detected platform."""

    def __init__(
        self,
        profile: Optional[PlatformProfile] = None,
        feature_rules: Iterable[FeatureRule] = (),
    ) -> None:
        self.profile = profile
        self.feature_rules = tuple(feature_rules)

    @classmethod
    def disabled(cls) -> "PlatformAdaptation":
        """Adaptation that changes nothing."""
        return cls()

    @classmethod
    def load(cls, platforms_dir: PathLike, info: PlatformInfo) -> "PlatformAdaptation":
        """Load feature rules and select the SoC profile matching ``info``."""
        root = Path(platforms_dir)
        rules = _load_feature_rules(root / "features.json")
        matching = [p for p in load_profiles(root / "soc") if p.matches(info)]
        if len(matching) > 1:
            logger.warning(
                "Several platform profiles match this device (%s); using %s",
                ", ".join(p.name for p in matching),
                matching[0].name,
            )
        profile = matching[0] if matching else None
        if profile is not None:
            logger.info("Using platform profile %s (%s)", profile.name, profile.path)
        else:
            logger.info("No platform profile matches this device")
        return cls(profile, rules)

    @property
    def use_cycle_counter(self) -> bool:
        """Whether the SoC profile allows CPU_CYCLES on the dedicated cycle counter."""
        return bool(self.profile and self.profile.cycle_counter)

    def metrics_to_drop(
        self,
        spec: TelemetrySpecification,
        cpu_id: int,
        features: Optional[FrozenSet[str]],
    ) -> Dict[str, str]:
        """Return ``{metric: reason}`` for the metrics to remove from ``spec``."""
        drop: Dict[str, str] = {}
        if features is not None:
            for rule in self.feature_rules:
                if rule.feature in features:
                    continue
                for name, metric in spec.metrics.items():
                    if set(metric.events) & rule.events:
                        drop.setdefault(name, f"core has no '{rule.feature}'")
        if self.profile is not None:
            adjustment = self.profile.cpus.get(cpu_id)
            if adjustment is not None:
                for name in adjustment.drop_metrics:
                    if name in spec.metrics:
                        drop.setdefault(name, f"{self.profile.name}: {adjustment.reason}")
        return drop

    def adapt(
        self,
        spec: TelemetrySpecification,
        cpu_id: int,
        features: Optional[FrozenSet[str]],
    ) -> TelemetrySpecification:
        """Return ``spec`` adjusted for this platform (``spec`` itself when unchanged)."""
        drop = self.metrics_to_drop(spec, cpu_id, features)
        if not drop:
            return spec
        by_reason: Dict[str, List[str]] = {}
        for name, reason in drop.items():
            by_reason.setdefault(reason, []).append(name)
        for reason, names in by_reason.items():
            logger.info(
                "%s: hiding %d metric(s) (%s): %s",
                spec.product_configuration.product_name,
                len(names),
                reason,
                ", ".join(sorted(names)),
            )
        return remove_metrics(spec, drop)


__all__ = [
    "CpuAdjustment",
    "FeatureRule",
    "PlatformAdaptation",
    "PlatformDataError",
    "PlatformProfile",
    "load_profiles",
]
