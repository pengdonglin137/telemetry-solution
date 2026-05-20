# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Unit tests for numeric display formatting helpers."""

import math

import pytest

from topdown_tool.common.numeric_format import format_numeric_value


@pytest.mark.parametrize(
    "value,expected",
    [
        (12542.22563, "12,542.226"),
        (1.23456e6, "1,234,560.000"),
        (2.352456246, "2.352"),
        (0.0, "0.000"),
        (-9876543.2, "-9,876,543.200"),
    ],
)
def test_format_numeric_value_fixed_precision_and_grouping(value: float, expected: str) -> None:
    assert format_numeric_value(value) == expected


@pytest.mark.parametrize("value", [None, math.nan, math.inf, -math.inf])
def test_format_numeric_value_none_and_non_finite(value: float) -> None:
    assert format_numeric_value(value) == "❌"


def test_format_numeric_value_custom_decimals() -> None:
    assert format_numeric_value(1234.567, decimals=1) == "1,234.6"
