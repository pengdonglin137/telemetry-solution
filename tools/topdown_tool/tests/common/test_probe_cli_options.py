# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

import argparse

import pytest

from topdown_tool.common import ArgsError
from topdown_tool.cpu_probe.cpu_factory import CpuProbeFactory
from topdown_tool.probe.cli_options import (
    add_csv_output_option,
    add_global_csv_output_option,
    add_listing_options,
    normalize_csv_output_targets,
    parse_positive_int,
    resolve_csv_output_targets,
    validate_csv_output_path,
)


def test_add_listing_options_adds_default_flags() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_argument_group("listing")
    add_listing_options(group, probe_name="TESTPROBE")

    args = parser.parse_args(["--testprobe-list-events"])

    assert args.testprobe_list_groups is False
    assert args.testprobe_list_metrics is False
    assert args.testprobe_list_events is True


def test_add_listing_options_supports_selective_items() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_argument_group("listing")
    add_listing_options(
        group,
        probe_name="TESTPROBE_BETA",
        items=("groups",),
    )

    args = parser.parse_args(["--testprobe_beta-list-groups"])
    assert args.testprobe_beta_list_groups is True
    with pytest.raises(SystemExit):
        parser.parse_args(["--testprobe_beta-list-metrics"])


def test_add_listing_options_default_help_uses_probe_name_pattern() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_argument_group("listing")
    add_listing_options(group, probe_name="TESTPROBE_GAMMA")

    assert (
        parser._option_string_actions["--testprobe_gamma-list-groups"].help
        == "List metric groups defined in the TESTPROBE_GAMMA telemetry specification."
    )
    assert (
        parser._option_string_actions["--testprobe_gamma-list-metrics"].help
        == "List metrics defined in the TESTPROBE_GAMMA telemetry specification."
    )
    assert (
        parser._option_string_actions["--testprobe_gamma-list-events"].help
        == "List TESTPROBE_GAMMA PMU events referenced by the TESTPROBE_GAMMA telemetry specification."
    )


def test_add_csv_output_option_adds_expected_flag() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_argument_group("csv")
    add_csv_output_option(group, probe_name="TESTPROBE")

    args = parser.parse_args(["--testprobe-generate-csv", "metrics"])
    assert args.testprobe_generate_csv == ["metrics"]


def test_add_csv_output_option_supports_selective_items() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_argument_group("csv")
    add_csv_output_option(group, probe_name="TESTPROBE", items=("metrics",))

    args = parser.parse_args(["--testprobe-generate-csv", "metrics"])
    assert args.testprobe_generate_csv == ["metrics"]


def test_add_global_csv_output_option_adds_expected_flag() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_argument_group("csv")
    add_global_csv_output_option(group)

    args = parser.parse_args(["--generate-csv", "metrics,events"])
    assert args.generate_csv == ["metrics", "events"]


def test_normalize_csv_output_targets_validates_and_deduplicates() -> None:
    normalized = normalize_csv_output_targets(
        ["metrics", "events", "metrics"],
        option_name="--testprobe-generate-csv",
    )
    assert normalized == ["metrics", "events"]

    with pytest.raises(ArgsError, match="--testprobe-generate-csv"):
        normalize_csv_output_targets(
            ["bad-option"],
            option_name="--testprobe-generate-csv",
        )


def test_resolve_csv_output_targets_uses_global_when_probe_missing() -> None:
    normalized = resolve_csv_output_targets(
        probe_values=None,
        global_values=["metrics", "events"],
        probe_option_name="--testprobe-generate-csv",
    )
    assert normalized == ["metrics", "events"]


def test_resolve_csv_output_targets_probe_specific_takes_precedence() -> None:
    normalized = resolve_csv_output_targets(
        probe_values=["metrics"],
        global_values=["metrics", "events"],
        probe_option_name="--testprobe-generate-csv",
    )
    assert normalized == ["metrics"]


def test_resolve_csv_output_targets_rejects_invalid_global_even_with_probe_override() -> None:
    with pytest.raises(ArgsError, match="--generate-csv"):
        resolve_csv_output_targets(
            probe_values=["metrics"],
            global_values=["bogus"],
            probe_option_name="--testprobe-generate-csv",
        )


def test_validate_csv_output_path_requires_output_dir() -> None:
    with pytest.raises(ArgsError, match="--csv-output-path"):
        validate_csv_output_path(requested=True, csv_output_path=None)

    validate_csv_output_path(requested=False, csv_output_path=None)


def test_parse_positive_int_rejects_non_positive_values() -> None:
    assert parse_positive_int("4") == 4
    with pytest.raises(argparse.ArgumentTypeError, match="integer ≥ 1"):
        parse_positive_int("0")
    with pytest.raises(argparse.ArgumentTypeError, match="integer ≥ 1"):
        parse_positive_int("-1")


@pytest.mark.parametrize(
    "factory_cls,supported_options,unsupported_options",
    [
        (
            CpuProbeFactory,
            ("--cpu-list-groups", "--cpu-list-metrics", "--cpu-list-events"),
            ("--cpu-list-unknown",),
        ),
    ],
)
def test_real_probe_listing_option_availability(
    factory_cls, supported_options: tuple[str, ...], unsupported_options: tuple[str, ...]
) -> None:
    parser = argparse.ArgumentParser(add_help=False)
    factory = factory_cls()
    factory.add_cli_arguments(parser)

    for option in supported_options:
        parser.parse_args([option])

    for option in unsupported_options:
        with pytest.raises(SystemExit):
            parser.parse_args([option])
