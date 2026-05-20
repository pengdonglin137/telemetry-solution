# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Small helpers for reading environment variables consistently."""

import os
from typing import Optional


def get_env_value(name: str) -> Optional[str]:
    """Read an environment variable and treat empty/whitespace values as unset."""

    value = os.environ.get(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized if normalized else None


__all__ = ["get_env_value"]
