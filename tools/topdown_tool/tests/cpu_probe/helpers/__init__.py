# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 Arm Limited

import os


def get_fixture_dir():
    """
    Return the absolute path of the cpu_probe/fixtures directory.
    """
    # The fixtures directory is cpu_probe/fixtures relative to this helper.py file
    helper_dir = os.path.abspath(os.path.dirname(__file__))
    cpu_probe_dir = os.path.dirname(helper_dir)
    fixtures_dir = os.path.join(cpu_probe_dir, "fixtures")
    return fixtures_dir


def get_fixture_path(*paths):
    """
    Compute the absolute path to a fixture file, relative to the cpu_probe/fixtures directory.
    """
    # The fixtures directory is cpu_probe/fixtures relative to this helper.py file
    fixtures_dir = get_fixture_dir()
    return os.path.join(fixtures_dir, *paths)
