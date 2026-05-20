# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Helpers for stable, human-readable numeric rendering."""

from __future__ import annotations

import math
from typing import Optional


def format_numeric_value(
    value: Optional[float],
    *,
    decimals: int = 3,
) -> str:
    """Render numeric values with fixed decimals and thousands separators."""
    if value is None:
        return "❌"
    if not math.isfinite(value):
        return "❌"
    return f"{value:,.{decimals}f}"
