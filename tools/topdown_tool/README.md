# Arm Top-Down tool
Arm Top-Down tool runs top down performance analysis on supported Arm CPUs.

For each supported CPU Arm distributes a telemetry specification JSON file which describes topdown metrics to compute.

Arm Top-Down tool captures PMU events for the required metrics using [`perf stat` on Linux](https://perf.wiki.kernel.org/index.php/Main_Page) on Linux and [WindowsPerf](https://gitlab.com/Linaro/WindowsPerf/windowsperf) on Microsoft Windows.

# Requirements
* A working [Linux Perf](https://perf.wiki.kernel.org/index.php/Main_Page) or [WindowsPerf](https://gitlab.com/Linaro/WindowsPerf/windowsperf) (3.3.3 or later) setup.
* Python 3.10 or later.
* [uv](https://docs.astral.sh/uv/) for Python dependency installation and locking.
* Under Linux: `inotifywait` from `inotify-tools` package

Platform prerequisites quickstart:

## Linux

The following commands target Ubuntu 22.04 LTS and newer. On other Linux distributions, install the equivalent packages (Git, Python 3, and inotify-tools) using your distribution’s package manager. Install uv using your approved local method.
```sh
sudo apt-get update
sudo apt-get install -y git python3 inotify-tools
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Windows
```sh
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
winget install WindowsPerf
```
For more details, see the WindowsPerf documentation.

# Install

For normal use from a telemetry repository checkout, initialize submodules so the packaged CMN tools are present, then install the CLI from `tools/topdown_tool`. Once installed, `topdown-tool` is available from any directory:
```sh
cd tools/topdown_tool
git submodule update --init --recursive
uv run --no-project scripts/install_topdown_tool.py
topdown-tool --help
```

The installer first validates `uv.lock`, then installs the locked runtime package versions and Git commit SHAs into a persistent uv tool environment. The generated `.topdown-tool-install-requirements.txt` is retained locally for inspection and is ignored by Git. It does not enforce distribution artifact hashes.

Plain `uv tool install .` remains an isolated persistent install, but re-resolves dependencies from `pyproject.toml` rather than using this project's lockfile. To update the locked persistent installation after updating the checkout, rerun the installer command above; do not use `uv tool upgrade`.

## Develop from a repository checkout

This workflow is for contributors working on a repository checkout; it is not needed for normal installation. From the repository root, initialize submodules and create the locked runtime environment:
```sh
cd tools/topdown_tool
git submodule update --init --recursive
uv sync --locked --no-dev
uv run --locked topdown-tool --help
```

> [!note] Linux
> If you see:
> ```sh
> Error: Insufficient privilege. This tool requires either perf_event_paranoid=-1, CAP_PERFMON, or CAP_SYS_ADMIN.
> ```
> set the required permissions as described in the Permissions section below.


# Usage

## Permissions

### Linux

Arm Top-Down tool needs to access performance monitoring counters (PMUs) in system-wide mode.
This requires elevated permissions. There are a few ways you can satisfy this requirement:

- **Changing `/proc/sys/kernel/perf_event_paranoid` to `-1` (recommended for most cases):** This is the quickest and most practical method, especially on a single-user machine or in a throwaway environment.

```sh
sudo sh -c 'echo -1 > /proc/sys/kernel/perf_event_paranoid'
```

- Granting your user the `CAP_PERFMON` capability.
- Running as root (not recommended unless in a throwaway environment or for quick experiments).

If you are on a system with SELinux enabled, you may find performance monitoring is blocked. In such cases you might also need to run:

```sh
sudo setenforce 0
```

to temporarily disable enforcement.

Once the permissions are set, you can run `topdown-tool` as your normal user.

If you encounter additional issues on Linux, see [Known Issues](#known-issues).

### Windows

On Windows, run `topdown-tool` from an Administrator Command Prompt or an Administrator PowerShell terminal. This ensures the tool has sufficient privileges to access performance counters.



## Verify installation and view CLI help
Use the command below to validate the installation and display the CLI help (usage and options):

```sh
topdown-tool --help
```

## Version information

Use `topdown-tool --version` to print the build identifier (base version with the short Git SHA, and the branch name when not on main). Add `--verbose` to emit structured metadata including branch, SHA, dirty/editable flags, and build timestamp. If git is available and the stamped metadata lacks branch/SHA, the tool will attempt to fill them from git.

## Remote targets (devlib)

The tool can collect metrics from a remote Linux or Android target through [devlib](https://gitlab.arm.com/tooling/workload-automation/devlib). From the same `tools/topdown_tool` checkout directory, install the optional remote extra:

```bash
uv run --no-project scripts/install_topdown_tool.py --remote
```

Contributors who are working from a repository checkout can sync the optional remote dependency into the locked development environment:

```bash
uv sync --locked --extra remote --no-dev
```

The extra pulls devlib from its GitLab repository. The resolved Git commit is
captured in `uv.lock`; authentication, if required by your environment, must be
provided through your normal Git or CI credential configuration outside this
repository.

Then run remote commands directly, for example:

```bash
topdown-tool --target-type ssh --target-config ssh.json -- ./a.out
```

### Use a remote target

If you need a newer perf than the one bundled in devlib, copy your preferred `perf` into the relevant `devlib/bin/<abi>/` directory.

Once the dependencies are installed, provide the remote type with `--target-type` and the connection details with `--target-config`. The configuration argument accepts either an inline JSON object or a path to a JSON file. Supported target types are:
- `ssh` for Linux hosts reachable over SSH.
- `adb` for Android devices attached through the Android Debug Bridge.
You can also configure remote targets through environment variables `TOPDOWN_TOOL_TARGET_TYPE` and `TOPDOWN_TOOL_TARGET_CONFIG`. Each value can come from either configuration option; command-line arguments take precedence.

### Configuration schema

- **SSH targets** (`--target-type ssh`): the JSON must include `host` and `username`. Add either `password` or a `keyfile` path; optional fields such as `port`, `password`, and `keyfile_password` are forwarded directly to devlib.
- **ADB targets** (`--target-type adb`): provide the Android `device` identifier as shown by `adb devices`. Optional keys like `adb_server_host` and `adb_server_port` are also supported.

Refer to the [devlib connection documentation](https://devlib.readthedocs.io/en/latest/connection.html) for the full list of available keys. The devlib source repository lives at https://gitlab.arm.com/tooling/workload-automation/devlib.

> [!note]
> The optional `remote` extra installs devlib from its GitLab repository. It is not included in the default install, CI test runs, or BlackDuck runtime dependency export.

### Examples

Connect to an SSH target:
```sh
topdown-tool --target-type ssh --target-config '{"host": "192.0.2.10", "username": "ubuntu", "password": "secret"}' -- ./a.out
```

Connect to an Android device using its ADB serial:
```sh
topdown-tool --target-type adb --target-config '{"device": "SERIAL"}' --probe CPU -- ./a.out
```

You may also store the JSON in a file (for example `ssh.json`) and pass its path:
```sh
topdown-tool --target-type ssh --target-config ssh.json -- ./a.out
```

The remote options must be supplied on each invocation and they replace the local perf runner with the remote implementation.

## Choosing what to monitor

Arm Top-Down tool lets you fine-tune what is being monitored:

- The `--core` or `-C` options let you restrict monitoring to specific CPU cores. For instance, to monitor only cores 0 and 1:

```sh
topdown-tool --core 0,1 myapp
```
- If you want the monitored application itself to be scheduled on specific cores, combine topdown-tool with `taskset`, like so:
```sh
topdown-tool --core 0,1 taskset -c 0,1 myapp
```
This runs your application (`myapp`) on cores 0 and 1, and ensures measurements are also limited to those cores.


### Launch and monitor an application

```sh
topdown-tool -- ./a.out
```

Note that you can use "--" to separate topdown-tool options from the command you want to run.


### Monitor a running application
> :warning: This is not currently supported on Windows.

> :warning: On Linux due to limitations of perf command, collection happens system-wide for the duration of monitored processes. When last process terminates, collection stops.

You can specify one or more process IDs to monitor:
```sh
$ topdown-tool -p 289156
Monitoring PID: 289156. Hit Ctrl-C to stop.
...
```
```sh
$ topdown-tool --pid 289156,289153
Monitoring PIDs: 289153,289156. Hit Ctrl-C to stop.
...
```

### System-wide monitoring
If no application or process ID is specified, then system-wide monitoring will be performed (for all CPUs/cores)

```sh
$ topdown-tool
Starting system-wide profiling. Hit Ctrl-C to stop. (See --help for usage information.)
...
```

## Probe selection

Arm Top-Down tool is extensible and can load one or more "probes" that monitor your system's subsystems. The CPU probe is selected by default.

- List available probes:
```sh
topdown-tool --probe-list
```

- Select probes explicitly (comma-separated or repeatable):
```sh
topdown-tool --probe CPU -- ./a.out
```

Each probe has its own quickstart:
- CPU: [README.CPU.md](./README.CPU.md)
- CMN: [README.CMN.md](./README.CMN.md)

## CSV output overview

You can export results to CSV for post-processing:
- Enable CSV globally with `--generate-csv metrics[,events]` (applies to all CSV-capable probes).
- Optionally override per probe with `--<probe>-generate-csv ...` (probe-specific wins).
- Output directory defaults to `tdt_out` when `--csv-output-path` is omitted.
- Optionally sample periodically with `-I` (interval in ms).

Example:
```sh
topdown-tool --generate-csv metrics --csv-output-path out -I 1000 -- sleep 10
```

See [README.CPU.md](./README.CPU.md) and [README.CMN.md](./README.CMN.md) for CSV file names, folder layout, and column details.

First, install and configure [Linux Perf](https://perf.wiki.kernel.org/index.php/Main_Page) or [WindowsPerf](https://gitlab.com/Linaro/WindowsPerf/windowsperf).

## Choosing which metrics to measure (per probe)

Metric selection is probe-specific. For the CPU probe, see [README.CPU.md](./README.CPU.md) for:
- Listing available metric groups and metrics
- Topdown stages (1, 2) and the combined view
- Selecting metric groups, stages, and methodology nodes
- Examples with output and CSV guidance
For CMN, see [README.CMN.md](./README.CMN.md).


## Other options
See `topdown-tool --help` for full usage information.

### Embedding via the Python API

You can drive the tool programmatically without invoking the CLI. The
``topdown_tool`` package re-exports the core probe interfaces so you can load
factories, configure them, create probes, and manage capture lifecycles
directly. It also exposes the optional devlib ``Target`` helpers to integrate
with remote devices. **This API surface is experimental and will evolve.**

- ``load_probe_factories()`` returns the available probe factories discovered via entry points.
- ``ProbeFactory.configure(config, **kwargs)`` applies a configuration object and indicates
  whether capture is required.
- ``ProbeFactory.create(capture_data=True, base_csv_dir=None, **kwargs)`` builds the probe
  instances for the configured factory.
- ``Probe`` instances expose ``start_capture``, ``stop_capture``, ``need_capture``, and ``output``.
- ``Target`` plus ``set_remote_target()/get_remote_target()`` allow embedding scenarios to supply a
  pre-configured devlib target.

Basic embedding example:

```python
from topdown_tool import Target
from topdown_tool.cpu_probe import CpuProbeFactory, CpuProbeFactoryConfig
from topdown_tool.perf import PerfFactoryConfig, perf_factory

# Configure perf first (optional overrides shown here).
perf_factory.configure(PerfFactoryConfig(perf_path="/usr/bin/perf"))

# Optionally provide a devlib target:
# from topdown_tool import set_remote_target
# set_remote_target(my_devlib_target)

# Configure the CPU probe factory programmatically.
factory = CpuProbeFactory()
config = CpuProbeFactoryConfig()  # override fields as needed
should_capture_data = factory.configure(config)
probes = factory.create(capture_data=should_capture_data, base_csv_dir="output")

# Drive capture lifecycle around your workload.
for probe in probes:
    if probe.need_capture():
        probe.start_capture()

# ... run workload here ...

for probe in probes:
    probe.stop_capture()
    probe.output()
```

Factories may expose additional helpers such as
``CpuProbeFactoryConfigBuilder.config_from_namespace`` when you want to reuse
CLI parsing logic. Refer to [README.CPU.md](./README.CPU.md#programmatic-configuration-reference)
for detailed configuration options.

# Known Issues

## General

### Reduced PMU counter availability for non-metal AWS/EC2 instances
When running non-metal instances on Amazon's Elastic Compute Cloud, not all hardware event counters are available to the end user (even when reserving all cores on a node).

This results in fewer events being monitored simultaneously, which can increase negative effects associated with counter multiplexing.

In some cases, this can prevent all events within a single metric from being scheduled together, which will trigger an error.

#### Possible workarounds:
* Use a metal instance.
* It is possible to schedule events within a metric independently by specifying `--cpu-collect-by=none`, although note that this can lead to unusual/invalid data for all but the most homogeneous workloads.

### Contributors: command not found after `uv sync`
When developing from a repository checkout, `uv sync` installs console scripts into `.venv/bin`. Run the command through uv:

```sh
uv run --locked topdown-tool --help
```

This avoids relying on an activated environment or a globally installed command.

### Remote extra fails to resolve

The `remote` extra resolves devlib from GitLab. If this fails, confirm that your
environment has network access and any required Git credentials for:

```sh
https://gitlab.arm.com/tooling/workload-automation/devlib.git
```

Default installs do not include the `remote` extra, so this issue affects any
installation or workflow that requests the remote extra. Rerun the installer
without `--remote` to return the persistent tool to its default dependency set.

# Development

Whether you’re fixing a bug, exploring the code, or adding your own performance probe, this section will help you get started quickly and effectively.

## Requirements & Environment

Run all commands in this section from `tools/topdown_tool`. uv creates and
manages the local `.venv` environment from `pyproject.toml` and `uv.lock`.

```sh
uv sync --locked --extra test --group lint --group type --group tox --group pkg-meta
```

## Running from the Repository

Run the CLI through uv so dependencies are synced from the lockfile:
```sh
uv run --locked topdown-tool --help
```

If you make local changes to the source code, they’ll immediately be picked up.


## Setting Up Pre-Commit and Code Quality Tools

For a smoother development experience, we recommend enabling pre-commit hooks and using our formatting/linting toolchain.
Run the following commands from `tools/topdown_tool`:

```sh
uv run --locked --group lint pre-commit install -c ../../.pre-commit-config.yaml --hook-type commit-msg
uv run --locked --group lint pre-commit install -c .pre-commit-config.yaml
```

This will ensure checks for formatting (black), linting (flake8, pylint) and commit-message validation run automatically before each commit.

The commit message should have the following format:

```sh
<scope>: <summary>
<empty line>
<detailed explanation, possibly multiple lines>
```

The list of valid scopes are in the [.ci/commit-msg-scopes](../../.ci/commit-msg-scopes) file.

## Running Common Tasks

- **Code style and linting:**
   ```sh
   uv run --locked --group tox tox -e codestyle
   ```
- **Type checking:**
   ```sh
   uv run --locked --group tox tox -e mypy
   ```
- **Unit tests:**
   ```sh
   uv run --locked --group tox tox -e py312
   ```
- **Package metadata checks:**
   ```sh
   uv run --locked --group tox tox -e pkg_meta
   ```

## Regenerating and Diffing Test Fixtures

We maintain golden (“reference”) outputs for some CLI and probe tests. If a test fails because output changed intentionally, you can update reference outputs:

- To view a diff of changes without overwriting:
   ```sh
   uv run --locked --extra test pytest --regen-reference=dryrun --tb=short
   ```
- To overwrite reference files with new outputs:
   ```sh
   uv run --locked --extra test pytest --regen-reference=write
   ```

See `conftest.py` for more details on this workflow.

## Architecture Overview

### Probes and Factories

The “Probe” and “ProbeFactory” pattern is at the heart of Arm Top-Down tool. Each probe is a self-contained measurement and reporting unit. Factories set up CLI options, handle user arguments, and instantiate their probe(s). Browse `probe/probe.py` for base class documentation.

- **To add a new probe:**
 Create a new factory/probe pair, and register your factory using Python’s entry point system.

### Extending Beyond This Repository

You can register new probes from another Python package by adding an appropriate entry to your own package’s `pyproject.toml` under `[project.entry-points."topdown_tool.probe_factories"]`.
This lets you create plug-in probes that don’t touch the core repository.

### Additional Internals of Interest

- `perf/`: All things performance event capture and event grouping.
- `layout/`: Pretty terminal and table output (Rich-powered).
- `common/`: Range handling, string normalization, argument helpers, and reusable exceptions.

If you’re building a new probe, refer to the existing CPU probe and the base classes as templates.
