# Changelog

All notable changes to the Telemetry Solution are documented in this file.

## [2026.09]

### Breaking Changes

- TDT / COMMON: Python 3.10 or later is required; support extends through Python 3.14.
- TDT / COMMON: Installation and development use locked uv dependencies, with a persistent tool installer. The old `tools/topdown_tool/topdown-tool` checkout launcher is removed; use the installed CLI or `uv run --locked topdown-tool`.
- TDT / COMMON: Custom probes must follow the updated configuration-builder and `SharedContext` interfaces, including `get_mux_interval_requests()`.
- SPECS: CPU and CMN specifications, schemas and mappings are consolidated under `data/pmu/{cpu,cmn}` and packaged with Topdown-tool. Specifications reside in `specifications/`; consumers using old file paths must update them.
- SPECS: CPU schemas v1.0 and v1.2 now define CPU-specific contracts with documented formula and reference rules, tighter field constraints and rejection of unknown properties. Existing schema selectors are retained.
- SPEPARSER-COMMON: Python 3.10 or later is required; support extends through Python 3.14.
- PERF-JSON-GENERATOR: Python 3.10 or later is required. Development dependencies and commands now use a per-tool uv lockfile.
- BENCHMARKS: UStress sources moved from `tools/ustress` to `benchmarks/ustress`; update scripts using the old path.

### TDT

#### Added

- CMN: CMN-700 profiling on Linux, with automatic discovery, reusable mesh layouts and combined CPU/CMN capture.
- CMN: Metric and group selection with CMN, XP, port and node filters; CSV export and per-device reporting for supported metrics.
- COMMON: Experimental Python embedding API for configuring probes and managing capture lifecycles.
- COMMON: CI packaging for a standalone Linux Arm64 executable, with embedded CPU/CMN specifications, README files and build-identification metadata.
- COMMON: Build identification through `--version` and detailed metadata through `--version --verbose`.
- CPU: User-space and kernel-space event selection with `--cpu-events-modifiers`.
- CPU: `validate-cpu-spec` checks individual files or directories against the schema and implemented reference rules, rejecting duplicate references.
- OUTPUT: Global `--generate-csv` selection with per-probe overrides and a default `tdt_out` output directory.
- PERF: Software events participate in scheduling without consuming hardware-counter capacity.
- REMOTE-TARGET: Remote Linux and Android profiling over SSH or ADB using the optional devlib dependency.
- WORKLOAD: Optional Workload Automation instrument for CPU capture and CSV artifacts.

#### Changed

- PERF: Configurable Linux multiplexing intervals, defaulting to 4 ms when privileged, with global and per-probe overrides. Original settings are restored during cleanup where possible; failures produce warnings.

#### Fixed

- COMMON: Help can be displayed without perf privileges; argument errors raised as `ArgsError` are reported without an internal-error label.
- CPU: Combined-stage selection is preserved when configuration is copied or normalised, retaining the combined metric-tree output.
- OUTPUT: Split tables preserve numeric alignment and can render without data rows.
- PERF: Metric scheduling preserves input order for reproducible grouping and rejects metric event sets that exceed available hardware counters before capture.
- WORKLOAD: Linux command workloads are gated before execution, and perf capture waits for counter-enable acknowledgement before the workload starts.

### SPECS

#### Added

- CPU telemetry specifications and detection mappings for Neoverse V3AE, Cortex-A725, Cortex-X925 and Arm C2-Ultra, including Cortex-X925 L3-cache events.
- CMN-700 telemetry specification and CMN JSON schema.

#### Fixed

- Duplicate metric references removed from Arm C1 metric groups.

### SPEPARSER-COMMON

#### Changed

- Development and test environments use a uv lockfile and dependency groups.

### PERF-JSON-GENERATOR

#### Fixed

- Events assigned to multiple telemetry function groups use an explicit single-group override, preventing duplicate-event failures when building perf. Ambiguous events without a valid override are rejected.

### BENCHMARKS

#### Added

- Random pointer-access benchmark with configurable software prefetching and result verification.
- Matrix-multiplication benchmarks demonstrating loop reordering and blocking.
- Sysstress workloads for lock contention, memory bandwidth and system-cache bandwidth, including modified STREAM sources.
- Neoverse V3 cache and TLB configuration for UStress workloads.

### USTRESS-CHARTS

#### Changed

- UStress Charts uses a uv-managed environment and requires Python 3.10 or later.

#### Fixed

- UStress Charts uses the current Topdown-tool CLI options, timestamped CSV layout and relocated benchmark directory.
