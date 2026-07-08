#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited
"""Install topdown-tool as a persistent uv tool from the locked runtime graph."""

import argparse
import subprocess
from collections.abc import Callable
from pathlib import Path


REQUIREMENTS_FILENAME = ".topdown-tool-install-requirements.txt"


def install(
    project_dir: Path,
    remote: bool,
    run: Callable[..., object] = subprocess.run,
) -> None:
    requirements_path = project_dir / REQUIREMENTS_FILENAME
    staging_path = requirements_path.with_suffix(".txt.tmp")
    export_command = [
        "uv",
        "export",
        "--quiet",
        "--locked",
        "--no-default-groups",
        "--no-emit-project",
        "--format",
        "requirements.txt",
        "--output-file",
        str(staging_path),
    ]
    if remote:
        export_command.extend(["--extra", "remote"])

    staging_path.unlink(missing_ok=True)
    try:
        run(export_command, cwd=project_dir, check=True)
    except Exception:
        staging_path.unlink(missing_ok=True)
        raise
    staging_path.replace(requirements_path)

    run(
        ["uv", "tool", "install", "--with-requirements", str(requirements_path), "."],
        cwd=project_dir,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install topdown-tool from its locked runtime dependency graph."
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Include the optional remote target dependencies.",
    )
    args = parser.parse_args()
    install(project_dir=Path(__file__).resolve().parents[1], remote=args.remote)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
