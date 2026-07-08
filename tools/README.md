# telemetry-solution/tools

This folder contains the tools for Telemetry solution and methodologies.

## Python dependency workflow

Use uv for Python tool environments and dependency locking. Each Python tool is locked independently with a `uv.lock` next to that tool's `pyproject.toml`; the repository does not use a root lockfile.

Top-Down's normal installer validates its project lockfile and installs the locked runtime versions and Git commit SHAs into a persistent uv tool. Contributors use `--locked` project commands so stale lockfiles fail rather than being updated at runtime.

### Use Top-Down from this repository

For normal Top-Down use, install the tool as a persistent uv tool from this
checkout. From the repository root, enter the `tools/` directory and run:

```sh
cd tools
git submodule update --init --recursive
uv run --no-project topdown_tool/scripts/install_topdown_tool.py
topdown-tool --help
```

The retained, ignored `topdown_tool/.topdown-tool-install-requirements.txt` is derived from `uv.lock` during installation. Plain `uv tool install ./topdown_tool` is still convenient, but it re-resolves dependencies and is not lock-enforced. Rerun the installer after updating the checkout instead of using `uv tool upgrade`.

### Develop a tool from this repository

Use a local per-tool `uv sync` when contributing changes to, or testing, a
tool in this checkout. Run uv commands from the tool directory. For example:

```sh
cd tools/topdown_tool
uv sync --locked
uv run --locked topdown-tool --help
```

`uv sync --locked` creates or updates the local environment strictly from the
committed lockfile. `uv run --locked` executes a command from that environment.

### Change dependencies

Edit the relevant tool's `pyproject.toml`, then run uv from that tool
directory:

```sh
uv lock
uv lock --check
uv run --locked <command>
```

Commit the updated project-local `uv.lock`; do not edit lockfiles directly.
CI checks every committed per-tool `uv.lock` for freshness.

## topdown_tool

Tool to support the Arm topdown methodology by collecting derived metrics based on Performance Monitoring Unit (PMU) events. The CLI can operate on the host or on remote Linux/Android devices.

The `ustress` validation workload suite resides in `../benchmarks/ustress`.

## ustress_charts

Chart generation tool for metrics for workloads from the ustress suite.

## perf_json_generator

Tool to generate JSON files for Linux perf tool which enable and document Arm PMU events and metrics.

## spe_parser

Tool to parse SPE (Statistical Profiling Extension) raw data and generate a Parquet or CSV file for further processing and analysis.
