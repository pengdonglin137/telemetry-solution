# Release notes

## 2026.09

Product: Telemetry Solution, Arm Top-Down tool

Quality Status: Release (Rel)

License: See LICENSE.md

Confidentiality: Public

### Highlights

- CMN-700 profiling on Linux, with automatic discovery, reusable mesh layouts, targeted metrics, CSV output and combined CPU/CMN capture. A WindowsPerf backend is included, but CMN-700 profiling on Windows is disabled.
- CPU telemetry specifications and detection mappings for Neoverse V3AE, Cortex-A725, Cortex-X925 and Arm C2-Ultra.
- Remote Linux and Android profiling over SSH or ADB through optional devlib support; an experimental Python embedding API and optional Workload Automation integration.
- Unified CSV selection, user/kernel CPU event filtering, configurable multiplexing intervals and detailed build-version reporting.
- More reliable event scheduling and Linux workload startup: counters are enabled before the profiled command starts.
- CPU specification validation CLI, clarified CPU schemas and a CMN JSON schema.
- New pointer-access, matrix-multiplication and system-stress benchmarks; updated UStress Charts integration and a perf-event generation fix for events shared by multiple groups.

### Upgrading

- Python-based tools require Python 3.10 or later. Arm Top-Down tool and SPE parser support extends through Python 3.14.
- Follow the updated README for uv-based installation. The old `tools/topdown_tool/topdown-tool` launcher is removed; use the installed CLI or `uv run --locked topdown-tool` from the tool directory.
- Update scripts using old data paths: CPU/CMN specifications, schemas and mappings now reside under `data/pmu/{cpu,cmn}`. UStress moved to `benchmarks/ustress`.
- Custom CPU specifications must meet the tightened schema constraints. Custom probes must adopt the updated configuration-builder and `SharedContext` interfaces.

### Known issues

- CMN-700 DRAM bandwidth output is 1,000 times too high. Divide the reported DRAM bandwidth by 1,000, including values exported to CSV, to correct this scaling error.
- CPU event CSV output labels all captures as run 1, including multi-run captures; the run column cannot distinguish those captures.

## 2025.09

Product: Telemetry Solution, Arm Top-Down tool
Version: 2025.09
Quality Status: Release (Rel)
License: See LICENSE.md
Confidentiality: Public

Changes:
 - Refactored PMU support in Arm Top-Down tool.
 - Add support for systems with heterogeneous cores.
 - Refactored CLI UX: Refactor CSV generation, improve command line arguments, improve metric display. 
 - Updated existing CPU JSON specifications.
 - Added CPU JSON specifications for Total Compute 2024.
 - Added support for Scalable Matrix Extension.
 - Added JSON schema for CPU JSON specification files.

Product quality:

These deliverables are being released under the terms of the agreement between Arm and each licensee 
(the “Agreement”). All planned verification and validation is complete. The release is suitable for volume 
production under the terms of the Agreement.
