# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Shared telemetry data path resolution."""

from functools import lru_cache
from importlib.resources import files
from pathlib import Path


def _package_root() -> Path:
    return Path(str(files("topdown_tool")))


@lru_cache(maxsize=1)
def telemetry_root_dir() -> Path:
    """Resolve the telemetry root directory.

    Resolution order:
    1. Packaged data path ``topdown_tool/data/pmu``.
    2. Repository path ``<repo>/data/pmu`` based on this source tree layout.
    """
    packaged_root = _package_root() / "data" / "pmu"
    if packaged_root.is_dir():
        return packaged_root

    repo_root = _package_root().parents[2]
    repo_root_data = repo_root / "data" / "pmu"
    if repo_root_data.is_dir():
        return repo_root_data

    raise FileNotFoundError(
        "Telemetry root directory not found. Checked "
        f"'{packaged_root}' and '{repo_root_data}'."
    )


def telemetry_probe_specifications_dir(probe_name: str) -> Path:
    """Return canonical specifications directory for a probe."""
    return telemetry_root_dir() / probe_name.lower() / "specifications"


def telemetry_probe_schemas_dir(probe_name: str) -> Path:
    """Return canonical schemas directory for a probe."""
    return telemetry_root_dir() / probe_name.lower() / "schemas"


def telemetry_probe_mapping_file(probe_name: str) -> Path:
    """Return canonical mapping.json path for a probe."""
    return telemetry_root_dir() / probe_name.lower() / "mapping.json"
