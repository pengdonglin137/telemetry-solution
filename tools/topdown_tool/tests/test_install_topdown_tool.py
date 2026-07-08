# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "install_topdown_tool.py"
GITIGNORE_PATH = SCRIPT_PATH.parents[1] / ".gitignore"


def _load_installer_module():
    spec = importlib.util.spec_from_file_location("install_topdown_tool", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_help_describes_remote_installation() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--remote" in result.stdout


def test_default_install_exports_locked_runtime_requirements_then_installs_tool(
    tmp_path: Path,
) -> None:
    installer = _load_installer_module()
    calls: list[list[str]] = []
    requirements_path = tmp_path / ".topdown-tool-install-requirements.txt"
    staging_path = requirements_path.with_suffix(".txt.tmp")

    def run(command: list[str], *, cwd: Path, check: bool) -> None:
        assert cwd == tmp_path
        assert check is True
        calls.append(command)
        if command[1] == "export":
            staging_path.write_text("rich==14.1.0\n", encoding="utf-8")

    installer.install(project_dir=tmp_path, remote=False, run=run)

    assert len(calls) == 2
    assert calls[0][:2] == ["uv", "export"]
    assert "--locked" in calls[0]
    assert "--no-default-groups" in calls[0]
    assert "--no-emit-project" in calls[0]
    assert calls[0][calls[0].index("--output-file") + 1] == str(staging_path)
    assert calls[1] == [
        "uv",
        "tool",
        "install",
        "--with-requirements",
        str(requirements_path),
        ".",
    ]
    assert requirements_path.read_text(encoding="utf-8") == "rich==14.1.0\n"
    assert not staging_path.exists()


def test_remote_install_exports_remote_extra_without_unpinned_project_extra(tmp_path: Path) -> None:
    installer = _load_installer_module()
    calls: list[list[str]] = []
    requirements_path = tmp_path / ".topdown-tool-install-requirements.txt"
    staging_path = requirements_path.with_suffix(".txt.tmp")

    def run(command: list[str], *, cwd: Path, check: bool) -> None:
        assert cwd == tmp_path
        assert check is True
        calls.append(command)
        if command[1] == "export":
            staging_path.write_text("devlib @ git+https://example.invalid/devlib\n", encoding="utf-8")

    installer.install(project_dir=tmp_path, remote=True, run=run)

    assert "--extra" in calls[0]
    assert calls[0][calls[0].index("--extra") + 1] == "remote"
    assert calls[1][-1] == "."


def test_export_failure_does_not_install_or_replace_last_valid_requirements(tmp_path: Path) -> None:
    installer = _load_installer_module()
    calls: list[list[str]] = []
    requirements_path = tmp_path / ".topdown-tool-install-requirements.txt"
    staging_path = requirements_path.with_suffix(".txt.tmp")
    requirements_path.write_text("rich==14.1.0\n", encoding="utf-8")
    staging_path.write_text("partial export\n", encoding="utf-8")

    def run(command: list[str], *, cwd: Path, check: bool) -> None:
        assert cwd == tmp_path
        assert check is True
        calls.append(command)
        raise subprocess.CalledProcessError(returncode=1, cmd=command)

    with pytest.raises(subprocess.CalledProcessError):
        installer.install(project_dir=tmp_path, remote=False, run=run)

    assert len(calls) == 1
    assert calls[0][1] == "export"
    assert requirements_path.read_text(encoding="utf-8") == "rich==14.1.0\n"
    assert not staging_path.exists()


def test_install_failure_retains_successfully_exported_requirements(tmp_path: Path) -> None:
    installer = _load_installer_module()
    requirements_path = tmp_path / ".topdown-tool-install-requirements.txt"
    staging_path = requirements_path.with_suffix(".txt.tmp")

    def run(command: list[str], *, cwd: Path, check: bool) -> None:
        assert cwd == tmp_path
        assert check is True
        if command[1] == "export":
            staging_path.write_text("rich==14.1.0\n", encoding="utf-8")
            return
        raise subprocess.CalledProcessError(returncode=1, cmd=command)

    with pytest.raises(subprocess.CalledProcessError):
        installer.install(project_dir=tmp_path, remote=False, run=run)

    assert requirements_path.read_text(encoding="utf-8") == "rich==14.1.0\n"
    assert not staging_path.exists()


def test_main_installs_remote_tool_from_script_project_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    installer = _load_installer_module()
    calls: list[tuple[Path, bool]] = []

    def install(project_dir: Path, remote: bool) -> None:
        calls.append((project_dir, remote))

    monkeypatch.setattr(installer, "install", install)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH), "--remote"])

    assert installer.main() == 0
    assert calls == [(SCRIPT_PATH.parents[1], True)]


def test_retained_install_requirements_are_gitignored() -> None:
    ignored_paths = GITIGNORE_PATH.read_text(encoding="utf-8").splitlines()

    assert "/.topdown-tool-install-requirements.txt" in ignored_paths
    assert "/.topdown-tool-install-requirements.txt.tmp" in ignored_paths
