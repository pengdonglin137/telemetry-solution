# Copyright 2025-2026 Arm Limited
# SPDX-License-Identifier: Apache-2.0

import argparse
from types import SimpleNamespace

import pytest

from topdown_tool.cmn_probe.cmn_factory import (
    CmnProbeFactory,
    CmnProbeFactoryCliConfigBuilder,
)
from topdown_tool.cmn_probe.common import CmnProbeFactoryConfig
from topdown_tool.common import ArgsError
from topdown_tool.perf.event_scheduler import CollectBy
from topdown_tool.perf.perf_factory import PerfFactory
from topdown_tool.probe.probe import SharedContext
import topdown_tool.cmn_probe.cmn_factory as cmn_factory_module


def _base_args() -> argparse.Namespace:
    return argparse.Namespace(
        cmn_generate_csv=None,
        csv_output_path=None,
        cmn_list=False,
        cmn_list_devices=False,
        cmn_list_groups=None,
        cmn_list_metrics=None,
        cmn_list_events=None,
        cmn_collect_by=CollectBy.METRIC,
        cmn_metrics=None,
        cmn_metric_groups=None,
        cmn_capture_per_device_id=False,
        cmn_group_capture_time_multiplier=1,
        cmn_print_descriptions=False,
        cmn_show_sample_events=False,
        cmn_debug_path=None,
        cmn_indices=None,
        cmn_mesh_layout_input=None,
        cmn_mesh_layout_output=None,
        cmn_specification=None,
        cmn_mux_interval=None,
    )


def _shared_context(perf_factory=None, base_csv_dir=None, mux_interval_ms=None) -> SharedContext:
    return SharedContext(
        perf_factory=perf_factory or PerfFactory(),
        base_csv_dir=base_csv_dir,
        mux_interval_ms=mux_interval_ms,
    )


@pytest.mark.parametrize(
    "version, expected",
    [
        ("CMN-700", "700"),
        ("CMN_650", "650"),
        ("CMN700", "700"),
        ("CMN--X1", "X1"),
    ],
)
def test_parse_cmn_version(version: str, expected: str) -> None:
    assert CmnProbeFactory.parse_cmn_version(version) == expected


@pytest.mark.parametrize(
    "config, expected",
    [
        (CmnProbeFactoryConfig(), True),
        (CmnProbeFactoryConfig(cmn_list=True), False),
        (CmnProbeFactoryConfig(cmn_list_devices=True), False),
        (CmnProbeFactoryConfig(cmn_list_groups=[]), False),
        (CmnProbeFactoryConfig(cmn_list_metrics=[]), False),
        (CmnProbeFactoryConfig(cmn_list_events=[]), False),
    ],
)
def test_configure_returns_capture_flag(config: CmnProbeFactoryConfig, expected: bool) -> None:
    factory = CmnProbeFactory()
    assert factory.configure(config, _shared_context()) is expected


def test_process_cli_arguments_csv_without_output_path_allowed() -> None:
    factory = CmnProbeFactory()
    builder = CmnProbeFactoryCliConfigBuilder(factory)
    args = _base_args()
    args.cmn_generate_csv = ["metrics"]

    config = builder.build_config_from_cli_arguments(args, _shared_context())

    assert config.cmn_generate_metrics_csv is True
    assert config.cmn_generate_events_csv is False


def test_process_cli_arguments_populates_config() -> None:
    factory = CmnProbeFactory()
    builder = CmnProbeFactoryCliConfigBuilder(factory)
    args = _base_args()
    args.cmn_generate_csv = ["metrics", "events"]
    args.cmn_list = True
    args.cmn_metrics = ["m1", "m2"]
    args.cmn_metric_groups = ["g1"]
    args.cmn_collect_by = CollectBy.NONE
    args.cmn_group_capture_time_multiplier = 2

    config = builder.build_config_from_cli_arguments(args, _shared_context(base_csv_dir="/tmp"))

    assert config.cmn_generate_metrics_csv is True
    assert config.cmn_generate_events_csv is True
    assert config.cmn_list is True
    assert config.metrics == ["m1", "m2"]
    assert config.groups == ["g1"]
    assert config.collect_by == CollectBy.NONE
    assert config.cmn_group_capture_time_multiplier == 2


def test_parser_accepts_cmn_mux_interval() -> None:
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    CmnProbeFactory().add_cli_arguments(parser)

    args = parser.parse_args(["--cmn-mux-interval", "12"])

    assert args.cmn_mux_interval == 12


def test_parser_rejects_non_positive_cmn_mux_interval(capsys) -> None:
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    CmnProbeFactory().add_cli_arguments(parser)

    with pytest.raises(SystemExit):
        parser.parse_args(["--cmn-mux-interval", "0"])

    assert "mux interval must be a positive integer" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("probe_interval_ms", "shared_context", "expected_interval_ms"),
    [
        (
            12,
            _shared_context(mux_interval_ms=9),
            12,
        ),
        (
            None,
            _shared_context(mux_interval_ms=9),
            9,
        ),
        (
            None,
            _shared_context(),
            4,
        ),
    ],
)
def test_build_config_resolves_cmn_mux_interval_precedence(
    probe_interval_ms,
    shared_context,
    expected_interval_ms,
) -> None:
    args = _base_args()
    args.cmn_mux_interval = probe_interval_ms
    builder = CmnProbeFactory()._get_config_builder()

    config = builder.build_config_from_cli_arguments(args, shared_context)

    assert config.mux_interval_ms == expected_interval_ms


def test_configure_resolves_cmn_mux_interval_for_direct_config() -> None:
    factory = CmnProbeFactory()
    perf_factory = SimpleNamespace(get_cmn_version=lambda: {0: "700"})
    config = CmnProbeFactoryConfig()

    factory.configure(config, _shared_context(perf_factory=perf_factory))

    assert config.mux_interval_ms is None
    assert factory.conf.mux_interval_ms == 4


def test_is_available_uses_perf_factory(monkeypatch) -> None:
    factory = CmnProbeFactory()
    perf_factory = SimpleNamespace(get_cmn_version=lambda: {})

    assert factory.is_available(_shared_context(perf_factory)) is False

    monkeypatch.setattr(
        perf_factory,
        "get_cmn_version",
        lambda: {0: "700"},
    )
    assert factory.is_available(_shared_context(perf_factory)) is True


def test_create_rejects_unknown_indices() -> None:
    factory = CmnProbeFactory()
    shared_context = _shared_context(SimpleNamespace(get_cmn_version=lambda: {0: "700"}))
    factory.configure(CmnProbeFactoryConfig(cmn_index=[1]), shared_context)

    with pytest.raises(ArgsError):
        factory.create(capture_data=False)


def test_discover_cmn_unsupported_platform(monkeypatch) -> None:
    factory = CmnProbeFactory()
    monkeypatch.setattr(cmn_factory_module.sys, "platform", "darwin")

    with pytest.raises(RuntimeError):
        factory.discover_cmn(SimpleNamespace())


def test_discover_cmn_json_windows_sets_versions(monkeypatch) -> None:
    factory = CmnProbeFactory()
    factory.cmns = {0: "700", 1: "650"}

    class _Result:
        stdout = '{"elements": [{}, {}]}'

    monkeypatch.setattr(cmn_factory_module, "run", lambda *args, **kwargs: _Result())

    topology_json = factory.discover_cmn_json_windows(
        SimpleNamespace(get_effective_perf_path=lambda: "wperf")
    )

    assert topology_json["elements"][0]["version"] == "700"
    assert topology_json["elements"][1]["version"] == "650"


def test_discover_cmn_json_linux_missing_submodule(monkeypatch) -> None:
    monkeypatch.setattr(cmn_factory_module.os.path, "isfile", lambda _path: False)

    with pytest.raises(Exception, match="Uninitialized git submodules"):
        CmnProbeFactory.discover_cmn_json_linux()
