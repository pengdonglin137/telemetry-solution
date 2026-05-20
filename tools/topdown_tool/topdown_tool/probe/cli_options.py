# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Shared helpers for probe CLI option registration."""

import argparse
from typing import Optional, Sequence

from topdown_tool.common import ArgsError


_DEFAULT_LISTING_HELP = {
    "groups": "List metric groups defined in the {probe} telemetry specification.",
    "metrics": "List metrics defined in the {probe} telemetry specification.",
    "events": "List {probe} PMU events referenced by the {probe} telemetry specification.",
}

_DEFAULT_CSV_OUTPUT_HELP = (
    "Generate {probe} CSV output for one or both: {items} (comma-separated). "
    "Writes CSV under --csv-output-path (default: 'tdt_out')."
)
_DEFAULT_GLOBAL_CSV_OUTPUT_HELP = (
    "Generate CSV output for one or both: {items} (comma-separated) for all probes "
    "that support CSV output. Probe-specific --<probe>-generate-csv options override this."
)


def _default_help_text(probe_name: str, item: str) -> str:
    probe = probe_name.upper()
    template = _DEFAULT_LISTING_HELP.get(
        item,
        "List {probe} {item} from the telemetry specification.",
    )
    return template.format(probe=probe, item=item)


def add_listing_options(
    parser: argparse._ArgumentGroup,
    probe_name: str,
    *,
    items: Sequence[str] = ("groups", "metrics", "events"),
) -> None:
    """Add ``--<probe>-list-<item>`` arguments to parser.

    Args:
        parser: Argument parser or group receiving list options.
        probe_name: Probe name (for example ``CPU``).
        items: Candidate list-items to add.
    """

    probe_prefix = probe_name.lower()
    for item in items:
        parser.add_argument(
            f"--{probe_prefix}-list-{item}",
            action="store_true",
            help=_default_help_text(probe_name, item),
        )


def _csv_items_help_text(items: Sequence[str]) -> str:
    quoted_items = [f"'{item}'" for item in items]
    if len(quoted_items) == 1:
        return quoted_items[0]
    if len(quoted_items) == 2:
        return f"{quoted_items[0]} and/or {quoted_items[1]}"
    return ", ".join(quoted_items[:-1]) + f", or {quoted_items[-1]}"


def _csv_items_metavar(items: Sequence[str]) -> str:
    if not items:
        return "item"
    head, *tail = items
    if not tail:
        return head
    return f"{head}[,{','.join(tail)}]"


def _csv_arg_type(raw: str) -> list[str]:
    return [token.strip().lower() for token in raw.split(",") if token.strip()]


def parse_positive_int(
    raw: str,
    *,
    error_message: str = "must be an integer ≥ 1",
) -> int:
    """Parse a positive integer CLI argument."""

    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(error_message) from exc
    if value <= 0:
        raise argparse.ArgumentTypeError(error_message)
    return value


def add_csv_output_option(
    parser: argparse._ArgumentGroup,
    probe_name: str,
    *,
    items: Sequence[str] = ("metrics", "events"),
    help_text: Optional[str] = None,
) -> None:
    """Add ``--<probe>-generate-csv`` argument to parser.

    Args:
        parser: Argument parser or group receiving csv options.
        probe_name: Probe name (for example ``CPU``).
        items: Candidate CSV output items to allow.
        help_text: Optional full help text override.
    """

    probe_prefix = probe_name.lower()
    if help_text is None:
        help_text = _DEFAULT_CSV_OUTPUT_HELP.format(
            probe=probe_name.upper(),
            items=_csv_items_help_text(items),
        )
    parser.add_argument(
        f"--{probe_prefix}-generate-csv",
        type=_csv_arg_type,
        metavar=_csv_items_metavar(items),
        help=help_text,
    )


def add_global_csv_output_option(parser: argparse._ArgumentGroup) -> None:
    """Add global ``--generate-csv`` argument to parser."""

    items = ("metrics", "events")
    help_text = _DEFAULT_GLOBAL_CSV_OUTPUT_HELP.format(items=_csv_items_help_text(items))

    parser.add_argument(
        "--generate-csv",
        type=_csv_arg_type,
        metavar=_csv_items_metavar(items),
        help=help_text,
    )


def normalize_csv_output_targets(
    values: Optional[Sequence[str]],
    *,
    option_name: str,
    allowed_items: Sequence[str] = ("metrics", "events"),
) -> list[str]:
    """Validate and normalize CSV output targets from CLI values."""

    if not values:
        return []

    allowed = {item.lower() for item in allowed_items}
    normalized: list[str] = []
    seen = set()
    for entry in values:
        value = entry.lower()
        if value not in allowed:
            allowed_text = _csv_items_help_text(allowed_items)
            raise ArgsError(
                f"Invalid value for {option_name}: {entry}. Use {allowed_text}."
            )
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def resolve_csv_output_targets(
    *,
    probe_values: Optional[Sequence[str]],
    global_values: Optional[Sequence[str]],
    probe_option_name: str,
    global_option_name: str = "--generate-csv",
    allowed_items: Sequence[str] = ("metrics", "events"),
) -> list[str]:
    """Resolve effective CSV targets with probe option taking precedence over global."""

    normalized_global = normalize_csv_output_targets(
        global_values,
        option_name=global_option_name,
        allowed_items=allowed_items,
    )
    if probe_values is None:
        return normalized_global

    return normalize_csv_output_targets(
        probe_values,
        option_name=probe_option_name,
        allowed_items=allowed_items,
    )


def validate_csv_output_path(*, requested: bool, csv_output_path: Optional[str]) -> None:
    """Ensure --csv-output-path is provided when CSV output is requested."""

    if requested and not csv_output_path:
        raise ArgsError("CSV output path must be specified with --csv-output-path")
