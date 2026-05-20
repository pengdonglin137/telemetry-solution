# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

import csv
from pathlib import Path

from topdown_tool.common.csv_renderer_base import create_dir, write_rows


def _read_csv_rows(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


def test_write_rows_creates_dir_and_returns_path(tmp_path: Path) -> None:
    output_dir = tmp_path / "nested" / "csv"
    output_path = write_rows(
        output_dir,
        "events.csv",
        ["col1", "col2"],
        [[1, 2]],
    )

    assert output_dir.exists()
    assert output_path.exists()
    assert output_path.name == "events.csv"


def test_write_rows_writes_header_and_rows(tmp_path: Path) -> None:
    output_path = write_rows(
        tmp_path,
        "metrics.csv",
        ["a", "b"],
        [[1, 2], [3, 4]],
    )

    assert _read_csv_rows(output_path) == [["a", "b"], ["1", "2"], ["3", "4"]]


def test_write_rows_with_empty_rows_writes_header_only(tmp_path: Path) -> None:
    output_path = write_rows(
        tmp_path,
        "empty.csv",
        ["x", "y"],
        [],
    )

    assert _read_csv_rows(output_path) == [["x", "y"]]


def test_create_dir_is_idempotent(tmp_path: Path) -> None:
    output_dir = tmp_path / "once" / "twice"
    first = create_dir(output_dir)
    second = create_dir(output_dir)

    assert first == second
    assert first.exists()
