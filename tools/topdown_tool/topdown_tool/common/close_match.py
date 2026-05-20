# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Shared close-match and suggestion text helpers."""

from difflib import get_close_matches
from typing import Mapping, Optional, Sequence, Tuple

from topdown_tool.common import normalize_str


def get_close_name_match(
    requested: str,
    normalized_to_canonical: Mapping[str, str],
) -> Optional[str]:
    """Return the closest canonical match for a requested name."""

    matches = get_close_matches(normalize_str(requested), list(normalized_to_canonical.keys()), 1)
    if not matches:
        return None
    return normalized_to_canonical[matches[0]]


def format_did_you_mean(suggestion: Optional[str]) -> str:
    """Return a standard 'did you mean ...?' phrase or an empty string."""

    return f'did you mean "{suggestion}"?' if suggestion else ""


def format_unknown_names_with_suggestions(
    unknown: Sequence[Tuple[str, Optional[str]]],
) -> str:
    """Format unknown names with optional suggestions for compact warning text."""

    return ", ".join(
        f'"{name}" ({format_did_you_mean(suggestion)})' if suggestion else f'"{name}"'
        for name, suggestion in unknown
    )


def format_unknown_metric_groups_warning(
    probe_name: str,
    entity_id: str,
    unknown: Sequence[Tuple[str, Optional[str]]],
) -> str:
    """Format a shared unknown-metric-group warning across probes."""

    return (
        f"{probe_name} {entity_id}: ignoring unknown metric group values: "
        f"{format_unknown_names_with_suggestions(unknown)}"
    )


def format_invalid_group_error(group_name: str, suggestion: Optional[str]) -> str:
    """Format a standard invalid-group message with optional suggestion text."""

    phrase = format_did_you_mean(suggestion)
    suffix = f" {phrase}" if phrase else ""
    return f'"{group_name}" is not a valid group.{suffix}'
