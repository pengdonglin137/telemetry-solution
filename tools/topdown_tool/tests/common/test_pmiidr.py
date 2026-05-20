# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

import pytest

from topdown_tool.common.pmiidr import compose_pmiidr


def test_compose_pmiidr_core_fields() -> None:
    implementer = (4 << 7) | 0x3B  # bank=5 (bank-1=4), JEP106 ID=0x3B
    part = 0x123
    variant = 0x5
    revision = 0x2

    value = compose_pmiidr(implementer, part, variant, revision)

    assert (value >> 20) & 0xFFF == part
    assert (value >> 16) & 0xF == variant
    assert (value >> 12) & 0xF == revision
    assert (value >> 8) & 0xF == (implementer >> 7) & 0xF
    assert value & 0x7F == implementer & 0x7F
    assert (value >> 7) & 0x1 == 0  # reserved bit


def test_compose_pmiidr_accepts_strings() -> None:
    implementer = hex((3 << 7) | 0x1A)
    part = "0x2AB"
    variant = 0x1
    revision = 0x0

    value = compose_pmiidr(implementer, part, variant, revision)

    assert (value >> 20) & 0xFFF == int(part, 0)
    assert (value >> 8) & 0xF == (int(implementer, 0) >> 7) & 0xF


def test_compose_pmiidr_matches_precomputed_value() -> None:
    """Ensure the composed PMIIDR matches a known reference value."""

    implementer = 0x2AA  # bank=0x5, id=0x2A
    part = 0x789
    variant = 0xA
    revision = 0x4

    value = compose_pmiidr(implementer, part, variant, revision)

    assert value == 0x789A452A


def test_compose_pmiidr_masks_reserved_bit() -> None:
    """Reserved bit [7] must remain 0 even if set in input implementer."""

    implementer = 0xFF  # bit 7 set in input
    value = compose_pmiidr(implementer, 0x1, 0x2, 0x3)

    assert (value >> 7) & 0x1 == 0


def test_compose_pmiidr_raises_on_out_of_range() -> None:
    with pytest.raises(ValueError):
        compose_pmiidr(
            implementer=0x1_000, part_num=0x1, major_revision=0x1, minor_revision=0x1
        )
    with pytest.raises(ValueError):
        compose_pmiidr(
            implementer=0x1, part_num=0x1_000, major_revision=0x1, minor_revision=0x1
        )
    with pytest.raises(ValueError):
        compose_pmiidr(
            implementer=0x1, part_num=0x1, major_revision=0x10, minor_revision=0x1
        )
    with pytest.raises(ValueError):
        compose_pmiidr(
            implementer=0x1, part_num=0x1, major_revision=0x1, minor_revision=0x10
        )
