# Copyright 2025-2026 Arm Limited
# SPDX-License-Identifier: Apache-2.0

"""
This module provides the factory for creating CMN probe instances used in telemetry data capture.
It defines the CmnProbeFactory class, which is responsible for processing CLI arguments specific to
CMN probing, loading CMN topology and loading telemetry specifications, and creating CmnProbe
objects accordingly.
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path
from re import sub
from subprocess import PIPE, run
from typing import Dict, List, Optional, Tuple, Union, cast

from rich import get_console
from rich.table import Table

import topdown_tool.probe as Base
from topdown_tool.cmn_probe.cmn_database import CmnDatabase
from topdown_tool.cmn_probe.cmn_model import _validate_file
from topdown_tool.cmn_probe.cmn_probe import CmnProbe
from topdown_tool.cmn_probe.common import CmnProbeFactoryConfig
from topdown_tool.cmn_probe.windows_perf_parser import WindowsPerfParser
from topdown_tool.common import ArgsError, range_decode
from topdown_tool.common.telemetry_paths import (
    telemetry_probe_mapping_file,
    telemetry_probe_specifications_dir,
    telemetry_probe_schemas_dir,
)
from topdown_tool.perf import PerfFactory
from topdown_tool.perf.event_scheduler import CollectBy
from topdown_tool.perf.mux_interval import parse_mux_interval, resolve_probe_mux_interval
from topdown_tool.probe.cli_options import parse_positive_int, resolve_csv_output_targets


class CmnProbeFactoryCliConfigBuilder(
    Base.ProbeFactoryCliConfigBuilder[CmnProbeFactoryConfig]
):
    """Build CmnProbeFactoryConfig from CLI arguments."""

    def __init__(self, factory: "CmnProbeFactory") -> None:
        self._factory = factory

    # pylint: disable=line-too-long
    def add_cli_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Register CMN-probing command-line arguments to the parser.

        Args:
            parser (argparse.ArgumentParser): The argument parser where CMN-specific options are
            added.

        The registered options include specifying CMN description and topology files, and options to
        list available CMNs, metric groups, metrics, or events.
        """
        parser.add_argument(
            "--cmn-specification",
            "--cmn",
            help="CMN specification file name. CMN name is auto-detected and specification file is automatically chosen, if this option is not provided.",
        )
        parser.add_argument(
            "--cmn-mesh-layout-input",
            help="Use previously generated CMN mesh layout. This file can include user defined node labels.",
        )
        parser.add_argument(
            "--cmn-mesh-layout-output", help="Save generated CMN mesh layout to a file"
        )
        parser.add_argument(
            "--cmn-indices",
            type=range_decode,
            help="Count only on the list of CMN indices provided. Multiple CMNs can be provided as a comma-separated list with no space.",
        )
        parser.add_argument("--cmn-list", action="store_true", help="List available CMNs and exit")
        parser.add_argument(
            "--cmn-list-devices",
            action="store_true",
            help="List devices described in CMN JSON specification",
        )
        parser.add_argument(
            "--cmn-list-groups",
            type=lambda x: x.split(","),
            nargs="?",
            const=[],
            help="List available CMN metric groups and exit",
        )
        parser.add_argument(
            "--cmn-list-metrics",
            type=lambda x: x.split(","),
            nargs="?",
            const=[],
            help="List available CMN metrics and exit",
        )
        parser.add_argument(
            "--cmn-list-events",
            type=lambda x: x.split(","),
            nargs="?",
            const=[],
            help="List available CMN events and exit",
        )
        parser.add_argument(
            "--cmn-collect-by",
            type=CollectBy.from_string,
            choices=[CollectBy.NONE, CollectBy.METRIC],
            default=CollectBy.METRIC,
            help='When multiplexing, collect events grouped by "none" or "metric" (default). This can avoid comparing data collected during different time periods.',
        )
        parser.add_argument(
            "--cmn-metrics",
            type=lambda x: x.split(","),
            help="Comma separated list of metrics to collect. See --cmn-list-metrics for available metrics",
        )
        parser.add_argument(
            "--cmn-metric-group",
            "--cmn-metric-groups",
            dest="cmn_metric_groups",
            type=lambda x: x.split(","),
            help="Comma separated list of metric groups to collect. See --cmn-list-groups for available groups",
        )
        parser.add_argument(
            "--cmn-capture-per-device-id",
            action="store_true",
            help="Collect and display metrics for each CMN node/device individually, rather than only globally. For large meshes it will print very large tables. Not meaningful for collection of topdown metrics.",
        )
        parser.add_argument(
            "--cmn-group-capture-time-multiplier",
            type=parse_positive_int,
            default=1,
            help="Capture groups for multiplied amount of minimum necessary time",
        )
        parser.add_argument(
            "--cmn-descriptions",
            "--cmn-print-descriptions",
            action="store_true",
            dest="cmn_print_descriptions",
            help="Show group/metric descriptions"
        )
        parser.add_argument(
            "--cmn-show-sample-events", action="store_true", help="Show sample events for metrics"
        )
        parser.add_argument(
            "--cmn-generate-csv",
            type=lambda s: [x.strip().lower() for x in s.split(",") if x.strip()],
            metavar="metrics[,events]",
            help=(
                "Generate CSV output for one or both: 'metrics' and/or 'events' "
                "(comma-separated). Writes CSV under --csv-output-path (default: "
                "'tdt_out')."
            ),
        )
        parser.add_argument(
            "--cmn-debug-path",
            help="Output directory for perf artefacts (command and output, Linux only)",
        )
        parser.add_argument(
            "--cmn-mux-interval",
            type=parse_mux_interval,
            metavar="MS",
            help="CMN perf event mux interval in milliseconds.",
        )

    # pylint: disable=too-many-locals
    def build_config_from_cli_arguments(
        self,
        args: argparse.Namespace,
        _shared_context: Base.SharedContext,
    ) -> CmnProbeFactoryConfig:
        """Process and validate command-line arguments for CMN probing. This method updates internal
        configuration based on CLI input.

        Args:
            args (argparse.Namespace): Parsed command-line arguments.
            _shared_context (Base.SharedContext): Invocation-scoped shared
                context.

        Returns:
            CmnProbeFactoryConfig: Configuration derived from the CLI
                namespace.

        Raises:
            ArgsError: If required argument combinations are missing.
        """
        effective_generate_csv = resolve_csv_output_targets(
            probe_values=args.cmn_generate_csv,
            global_values=getattr(args, "generate_csv", None),
            probe_option_name="--cmn-generate-csv",
        )
        cmn_generate_metrics_csv = "metrics" in effective_generate_csv
        cmn_generate_events_csv = "events" in effective_generate_csv
        cmn_list = args.cmn_list
        cmn_list_devices = args.cmn_list_devices
        cmn_list_groups = args.cmn_list_groups
        cmn_list_metrics = args.cmn_list_metrics
        cmn_list_events = args.cmn_list_events
        collect_by = args.cmn_collect_by
        metrics = args.cmn_metrics
        groups = args.cmn_metric_groups
        capture_per_device_id = args.cmn_capture_per_device_id
        cmn_group_capture_time_multiplier = args.cmn_group_capture_time_multiplier
        descriptions = args.cmn_print_descriptions
        show_sample_events = args.cmn_show_sample_events
        debug_path = args.cmn_debug_path
        cmn_index = args.cmn_indices
        cmn_mesh_layout_input = args.cmn_mesh_layout_input
        cmn_mesh_layout_output = args.cmn_mesh_layout_output
        cmn_specification = args.cmn_specification
        return CmnProbeFactoryConfig(
            cmn_generate_metrics_csv=cmn_generate_metrics_csv,
            cmn_generate_events_csv=cmn_generate_events_csv,
            cmn_list=cmn_list,
            cmn_list_devices=cmn_list_devices,
            cmn_list_groups=cmn_list_groups,
            cmn_list_metrics=cmn_list_metrics,
            cmn_list_events=cmn_list_events,
            collect_by=collect_by,
            metrics=metrics,
            groups=groups,
            capture_per_device_id=capture_per_device_id,
            cmn_group_capture_time_multiplier=cmn_group_capture_time_multiplier,
            descriptions=descriptions,
            show_sample_events=show_sample_events,
            debug_path=debug_path,
            cmn_index=cmn_index,
            cmn_mesh_layout_input=cmn_mesh_layout_input,
            cmn_mesh_layout_output=cmn_mesh_layout_output,
            cmn_specification=cmn_specification,
            mux_interval_ms=resolve_probe_mux_interval(
                "CMN", getattr(args, "cmn_mux_interval", None), _shared_context
            ),
        )


class CmnProbeFactory(Base.ProbeFactory):
    """Factory class for creating CMN probe instances.
    Processes command line arguments related to CMN probing, detects CMN topology, and creates
    CmnProbe instances configured with the appropriate telemetry specification.
    """

    METRICS_DIR = str(telemetry_probe_specifications_dir("cmn"))
    SCHEMAS_DIR = str(telemetry_probe_schemas_dir("cmn"))
    MAPPING_FILE = str(telemetry_probe_mapping_file("cmn"))

    @staticmethod
    def parse_cmn_version(version: str) -> str:
        """Remove "CMN" from the beginning of a string with reported CMN version. Also, remove any
        non-alphanumeric characters from the version string.

        Args:
            version (str): CMN version string

        Returns:
            str: processed CMN version string
        """
        version = version.upper()
        if version.startswith("CMN"):
            version = version[3:]
        return sub(r"^[^A-Za-z0-9]*", "", version)

    def __init__(self) -> None:
        """Initialize a CmnProbeFactory instance. Sets up the default configuration and mappings for
        CMN descriptions.
        """
        super().__init__()
        self.conf = CmnProbeFactoryConfig()
        self.cmns: Dict[int, Union[int, str]] = {}
        self._perf_factory: Optional[PerfFactory] = None

    def name(self) -> str:
        """Return the name of the probe.

        Returns:
            str: The string "CMN".
        """
        return "CMN"

    def is_available(self, shared_context: Base.SharedContext) -> bool:
        """Check if CMN probing is available on the current system.

        Returns:
            bool: If there is at least one CMN present
        """
        self._perf_factory = shared_context.perf_factory
        try:
            self.cmns = self._perf_factory.get_cmn_version()
        except RuntimeError:
            return False
        return len(self.cmns) > 0

    def _get_config_builder(
        self,
    ) -> Base.ProbeFactoryCliConfigBuilder[CmnProbeFactoryConfig]:
        """Construct the CMN probe CLI config builder."""

        return CmnProbeFactoryCliConfigBuilder(self)

    def _configure(
        self,
        config: CmnProbeFactoryConfig,
        **kwargs: object,
    ) -> bool:
        """Apply a configuration for the CMN probe factory.

        Args:
            config (CmnProbeFactoryConfig): CMN probe configuration values.
            **kwargs: Supported keyword-only arguments:
                cmn_detector (Optional[CmnDetector]): Preconfigured detector to reuse instead
                of creating a new one.

        Returns:
            bool: True if telemetry capture should proceed, False when only
                informational listing is required.
        """
        shared_context = self.shared_context
        self._perf_factory = shared_context.perf_factory
        try:
            self.cmns = self._perf_factory.get_cmn_version()
        except RuntimeError:
            self.cmns = {}
        if config.mux_interval_ms is None:
            config = replace(
                config,
                mux_interval_ms=resolve_probe_mux_interval("CMN", None, shared_context),
            )
        self.conf = config
        return not (
            self.conf.cmn_list
            or self.conf.cmn_list_devices
            or self.conf.cmn_list_groups is not None
            or self.conf.cmn_list_metrics is not None
            or self.conf.cmn_list_events is not None
        )

    # pylint: disable=raise-missing-from, broad-exception-raised
    @staticmethod
    def discover_cmn_json_linux() -> dict:
        """Run CMN topology discovery tool and return a dict from loaded and parsed JSON file.

        Returns:
            dict: parsed topology JSON file

        Raises:
            json.JSONDecodeError: If JSON couldn't be loaded due to no access to /proc/iomem or
            /dev/mem or not running as root
            Exception: If git modules are uninitialized
        """
        discovery_tool_path = os.path.join(
            os.path.abspath(os.path.dirname(__file__)), "cmn-tools", "src", "cmn_discover.py"
        )
        if not os.path.isfile(discovery_tool_path):
            raise Exception("Uninitialized git submodules")

        read_end, write_end = os.pipe2(0)  # type: ignore[attr-defined]  # pylint: disable=no-member
        pid = os.fork()
        if pid == 0:
            os.close(read_end)

            null_fd = os.open("/dev/null", os.O_RDONLY)
            os.dup2(null_fd, 0)
            os.close(null_fd)

            null_fd = os.open("/dev/null", os.O_WRONLY)
            os.dup2(null_fd, 1)
            os.dup2(null_fd, 2)
            os.close(null_fd)

            os.execl(
                sys.executable,
                os.path.basename(sys.executable),
                discovery_tool_path,
                "--cmn-loc-no-cache",
                "--overwrite",
                "-o",
                "/proc/self/fd/" + str(write_end),
            )

            os.close(write_end)
            sys.exit(1)

        os.close(write_end)

        json_pipe = os.fdopen(read_end)
        try:
            topology_json = json.load(json_pipe)
        except json.JSONDecodeError:
            raise Exception(
                "CMN topology detection failed, check if topdown-tool runs as root and check access to /proc/iomem and /dev/mem"
            )
        os.waitpid(pid, 0)
        json_pipe.close()

        return topology_json

    def discover_cmn_json_windows(self, perf_factory_instance: PerfFactory) -> dict:
        """Run CMN topology discovery tool and return a dict from loaded and parsed JSON file.

        Returns:
            dict: parsed topology JSON file
        """
        result = run(
            [
                perf_factory_instance.get_effective_perf_path(),
                "cmninfo",
                "--json",
            ],
            stdout=PIPE,
            check=True,
            text=True,
        )
        topology_json = json.loads(result.stdout)
        versions_iterator = iter(self.cmns.values())
        for cmn in topology_json["elements"]:
            cmn["version"] = next(versions_iterator)
        return topology_json

    def discover_cmn(self, perf_factory_instance: PerfFactory) -> dict:
        if sys.platform == "linux":
            return self.discover_cmn_json_linux()
        if sys.platform == "win32":
            return self.discover_cmn_json_windows(perf_factory_instance)
        raise RuntimeError(f"CMN topology retrieval not supported on {sys.platform}")

    # pylint: disable=too-many-locals, too-many-branches, arguments-differ, too-many-statements, too-many-nested-blocks
    def create(
        self,
        capture_data: bool = True,
    ) -> Tuple["CmnProbe", ...]:
        """Create CmnProbe instances based on CLI configuration and detected CMNs.

        Args:
            capture_data (bool, optional): Flag indicating whether telemetry capture should be
                performed.
                Defaults to True.
        Returns:
            Tuple[CmnProbe, ...]: A tuple of instantiated CmnProbe objects.
        """
        shared_context = self.shared_context
        perf_factory_instance = self._perf_factory or shared_context.perf_factory
        base_csv_dir = (
            shared_context.get_or_create_base_csv_dir()
            if self.conf.cmn_generate_metrics_csv or self.conf.cmn_generate_events_csv
            else None
        )

        if self.conf.cmn_index is not None and set(self.conf.cmn_index) - set(self.cmns.keys()):
            raise ArgsError("CMN indices to collect must be present on the system")

        if sys.platform == "win32":
            perf_factory_instance.register_parser_for_class(CmnProbe, WindowsPerfParser)

        # Instantiate CmnProbes
        topology_json: dict

        if self.conf.cmn_mesh_layout_input is not None:
            with open(self.conf.cmn_mesh_layout_input, encoding="utf-8") as topology_file:
                topology_json = json.load(topology_file)
        else:
            topology_json = self.discover_cmn(perf_factory_instance)

            if self.conf.cmn_mesh_layout_output is not None:
                with open(self.conf.cmn_mesh_layout_output, "w", encoding="utf-8") as topology_file:
                    json.dump(topology_json, topology_file, ensure_ascii=False, indent=4)

        # Load mapping file
        mapping_json: dict
        with open(self.MAPPING_FILE, encoding="utf-8") as mapping_file:
            mapping_json = json.load(mapping_file)
        cmn_version_mapping: Dict[int, str] = {cmn_data["product_version"]: cmn_version for cmn_version, cmn_data in mapping_json.items()}
        current_cmn_indices = tuple(self.cmns.keys())
        for cmn_index in current_cmn_indices:
            identifier = self.cmns[cmn_index]
            version: Optional[str] = None
            revision: Optional[str] = None
            if isinstance(identifier, int):
                numeric_version = (identifier & 0xFFF00) >> 8
                numeric_revision = identifier & 0xFF
                try:
                    version = cmn_version_mapping[numeric_version]
                except KeyError:
                    logging.warning("Unknown CMN numeric version 0x%X at index %d", numeric_version, cmn_index)
                    del self.cmns[cmn_index]
                    continue
                try:
                    revision = mapping_json[version]["revisions"][numeric_revision]
                except IndexError:
                    logging.warning("Unknown CMN-%s numeric revision %d at index %d", version, numeric_revision, cmn_index)
                    del self.cmns[cmn_index]
                    continue
            elif isinstance(identifier, str):
                version = self.parse_cmn_version(identifier)
                if version not in mapping_json:
                    logging.warning("Unknown CMN version %s at index %d", version, cmn_index)
                    del self.cmns[cmn_index]
                    continue
                revision = mapping_json[version]["windows_revision"]
                if revision is None:
                    logging.warning("CMN-%s unsupported on Windows", version)
                    del self.cmns[cmn_index]
                    continue
            if revision is None:
                logging.warning("Unknown CMN-%s revision %d at index %d", version, numeric_revision, cmn_index)
            if version is None or revision is None:
                del self.cmns[cmn_index]
                continue
            self.cmns[cmn_index] = f"cmn_{version.lower()}_{revision.lower()}"

        # CMNs requested to capture
        cmn_indices_by_version: Dict[str, List[int]] = {}
        for cmn_index, cmn in enumerate(topology_json["elements"]):
            if cmn_index not in self.cmns:
                logging.warning("Skipping CMN #%d due to undetected version/revision", cmn_index)
                continue
            if self.conf.cmn_index is not None and cmn_index not in self.conf.cmn_index:
                continue
            cmn_version = self.cmns[cmn_index]
            cmn_json_version = "cmn_" + self.parse_cmn_version(cmn["version"]).lower()
            assert isinstance(cmn_version, str) and cmn_version.startswith(cmn_json_version)
            cmn_indices_by_version.setdefault(cmn_version, []).append(cmn_index)

        # List available CMNs
        if self.conf.cmn_list:
            console = get_console()
            table = Table(title="Available CMNs")
            for column in ("Version", "Index"):
                table.add_column(column)
            for cmn_version, cmn_indices in cmn_indices_by_version.items():
                v1, v2, v3 = cmn_version.upper().split("_", 2)
                table.add_row(f"{v1}-{v2} {v3}", ", ".join(map(str, cmn_indices)))
            console.print(table)

        # Default mapping of CMN version to a JSON description file
        cmns_json_files_in_use: Dict[str, Dict[str, Optional[str]]] = {}
        for cmn_version in cmn_indices_by_version:
            attempt_filename = os.path.join(self.METRICS_DIR, f"{cmn_version}_pmu.json")
            cmns_json_files_in_use[cmn_version] = {
                "path": attempt_filename if os.path.isfile(attempt_filename) else None,
                "content": None,
            }

        # User overridden mapping of CMN version to a JSON description file
        if self.conf.cmn_specification is not None:
            cmn_filename = self.conf.cmn_specification
            json_correct, error = _validate_file(Path(cmn_filename), Path(self.SCHEMAS_DIR))
            if not json_correct:
                raise Exception(error)
            with open(cmn_filename, encoding="utf-8") as cmn_specification_file:
                cmn_description_json = json.load(cmn_specification_file)
            product_version = self.parse_cmn_version(cmn_description_json["product_configuration"]["product_name"]).lower()
            major_revision = cmn_description_json["product_configuration"]["major_revision"]
            minor_revision = cmn_description_json["product_configuration"]["minor_revision"]
            full_version = f"cmn_{product_version}_r{major_revision}p{minor_revision}"
            if full_version in cmns_json_files_in_use:
                cmns_json_files_in_use[full_version]["path"] = cmn_filename
                cmns_json_files_in_use[full_version]["content"] = cmn_description_json

        # Load default JSON files
        for cmn_file in cmns_json_files_in_use.values():
            if cmn_file["content"] is None and cmn_file["path"] is not None:
                cmn_path = cast(str, cmn_file["path"])
                json_correct, error = _validate_file(Path(cmn_path), Path(self.SCHEMAS_DIR))
                if not json_correct:
                    raise Exception(error)
                with open(cmn_path, encoding="utf-8") as cmn_specification_file:
                    cmn_file["content"] = json.load(cmn_specification_file)

        cmns_dbs: Dict[str, CmnDatabase] = {}
        for cmn_version, cmn_indices in cmn_indices_by_version.items():
            v1, v2, v3 = cmn_version.upper().split("_", 2)
            friendly_version = f"{v1}-{v2} {v3}"
            db_friendly_version = f"{v2} {v3}"
            if cmns_json_files_in_use[cmn_version]["content"] is None:
                logging.warning("Skipping capture for %s on indices #%s because there is no default JSON specification and custom JSON wasn't provided by the user", friendly_version, ", #".join(str(cmn_index) for cmn_index in cmn_indices))
                continue
            methodology_json: dict = cast(dict, cmns_json_files_in_use[cmn_version]["content"])
            cmns_dbs[cmn_version] = CmnDatabase(
                db_friendly_version, cmn_indices, topology_json, methodology_json
            )

        # Use JSON files for CMNs present on the system
        return tuple(
            CmnProbe(
                self.conf, cmn_db, capture_data, base_csv_dir, perf_factory_instance
            )
            for cmn_db in cmns_dbs.values()
        )

    def get_description(self) -> str:
        """Return a short description of the CMN probe.

        Returns:
            str: a short description of the CMN probe
        """
        return "Collect Top-down CMN metrics; advanced options for specification inspection and targeted capture."
