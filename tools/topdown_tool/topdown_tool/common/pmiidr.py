# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Helpers for composing CoreSight PMIIDR values."""

import logging
from typing import Protocol, Union

logger = logging.getLogger(__name__)


class PMIIDRFields(Protocol):
    """Minimal interface for PMIIDR composition."""

    @property
    def implementer(self) -> Union[int, str]:
        ...

    @property
    def part_num(self) -> Union[int, str]:
        ...

    @property
    def major_revision(self) -> int:
        ...

    @property
    def minor_revision(self) -> int:
        ...


def _to_int(value: Union[int, str]) -> int:
    """Convert an int/str with base prefixes to int."""
    if isinstance(value, int):
        return value
    return int(str(value), 0)


def compose_pmiidr(
    implementer: Union[int, str],
    part_num: Union[int, str],
    major_revision: int,
    minor_revision: int,
) -> int:
    """Compose a PMIIDR value per CoreSight layout.

    Bit layout (ARM IHI 0091 PMIIDR):
        [31:20] ProductID (part number)
        [19:16] Variant    (major revision)
        [15:12] Revision   (minor revision)
        [11:8]  Implementer[10:7] (JEP106 bank - 1)
        [7]     Reserved (0)
        [6:0]   Implementer[6:0] (JEP106 ID)
    """
    impl_val = _to_int(implementer)
    part_val = _to_int(part_num)

    if impl_val < 0 or impl_val > 0xFFF:
        raise ValueError(f"Implementer out of range: {impl_val:#x}")
    if part_val < 0 or part_val > 0xFFF:
        raise ValueError(f"Part number out of range: {part_val:#x}")
    if major_revision < 0 or major_revision > 0xF:
        raise ValueError(f"Major revision out of range: {major_revision:#x}")
    if minor_revision < 0 or minor_revision > 0xF:
        raise ValueError(f"Minor revision out of range: {minor_revision:#x}")

    upper_impl = (impl_val >> 7) & 0xF
    lower_impl = impl_val & 0x7F
    value = (
        (part_val & 0xFFF) << 20
        | (major_revision & 0xF) << 16
        | (minor_revision & 0xF) << 12
        | upper_impl << 8
        | lower_impl
    )
    logger.debug(
        "Composed PMIIDR: implementer=%s part_num=%s variant=%s revision=%s -> 0x%x",
        implementer,
        part_num,
        major_revision,
        minor_revision,
        value,
    )
    return value


def compose_pmiidr_from_config(config: PMIIDRFields) -> int:
    """Compose a PMIIDR value from an object exposing PMIIDR fields."""

    return compose_pmiidr(
        config.implementer,
        config.part_num,
        config.major_revision,
        config.minor_revision,
    )
