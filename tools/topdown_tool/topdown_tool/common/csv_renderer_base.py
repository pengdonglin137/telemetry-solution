# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Shared helpers for probe CSV renderers."""

import csv
from pathlib import Path
from typing import Iterable, Sequence, Union

PathLike = Union[str, Path]


def create_dir(directory: PathLike) -> Path:
    """Create the output directory if needed.

    Args:
        directory: Directory path to create (string or Path).

    Returns:
        Path object pointing to the created (or existing) directory.
    """
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_rows(
    directory: PathLike,
    filename: str,
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
) -> Path:
    """Write CSV rows to a file in the specified directory.

    Args:
        directory: Output directory path (string or Path).
        filename: Name of the CSV file to create.
        headers: Column header labels to write as the first row.
        rows: Iterable of row sequences to write to the CSV.

    Returns:
        Path to the CSV file that was written.
    """
    out_dir = create_dir(directory)
    output_path = out_dir / filename
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
    return output_path


__all__ = ["create_dir", "write_rows"]
