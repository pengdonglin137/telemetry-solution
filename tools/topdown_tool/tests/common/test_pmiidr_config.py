# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

from dataclasses import dataclass

from topdown_tool.common.pmiidr import PMIIDRFields, compose_pmiidr_from_config


@dataclass
class _DummyConfig(PMIIDRFields):
    implementer_value: str
    part_num_value: str
    major_revision_value: int
    minor_revision_value: int

    @property
    def implementer(self) -> str:
        return self.implementer_value

    @property
    def part_num(self) -> str:
        return self.part_num_value

    @property
    def major_revision(self) -> int:
        return self.major_revision_value

    @property
    def minor_revision(self) -> int:
        return self.minor_revision_value


def test_compose_pmiidr_from_config() -> None:
    cfg = _DummyConfig("0x43B", "0x123", 1, 2)
    value = compose_pmiidr_from_config(cfg)
    assert (value >> 20) & 0xFFF == 0x123
    assert (value >> 16) & 0xF == 0x1
    assert (value >> 12) & 0xF == 0x2
