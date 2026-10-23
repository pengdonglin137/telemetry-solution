# CPU platform adaptation layer

Telemetry specifications describe a CPU core. A SoC can integrate the same core in a way that
makes part of its specification wrong or useless for that SoC. This directory holds such
SoC- and feature-specific adjustments as data. `topdown-tool` applies them at run time on top of
the unchanged specifications in `../specifications`.

The goal is that adapting a new SoC never changes the results on SoCs that are already
supported:

- Specification files are never edited for one SoC.
- A SoC profile applies only to devices that match it. Devices without a matching profile get
  exactly the previous behaviour.
- A feature rule applies only to cores that lack the feature, and only to specifications that
  contain its events.
- Problems in this data (bad JSON, unknown keys) are reported as a warning and the
  specifications are used unchanged.
- `topdown-tool --cpu-no-platform-adaptation` disables the layer for a run.
- `tests/cpu_probe/test_platform_adaptation.py` checks that every specification in
  `mapping.json` is unchanged on a device without a profile.

Run with `--log-level INFO` to see which profile was selected and which metrics were hidden.

## Files

### `features.json`: CPU feature rules

Each rule names a feature flag as reported in `/proc/cpuinfo` (`Features`, the Linux HWCAP name)
and a list of events. On a core whose flags do not include the feature, every metric that uses
one of those events is hidden, and the topdown decision tree is pruned the same way as in
derived specifications (removed nodes are replaced by their children).

| Feature | Events | Why |
|---------|--------|-----|
| `sme`   | SME/SME2-unit (CME) events used by core specifications | The SME2 unit is optional in C1-series clusters. Without it these events never count and the metrics are always empty. Hiding them also frees PMU counters for the other events. |

### `soc/*.json`: SoC profiles

```json
{
  "name": "XRing O3",
  "match": {
    "android_properties": {"ro.soc.manufacturer": "XRing", "ro.soc.model": "O3"},
    "dt_compatible": ["vendor,soc"]
  },
  "cycle_counter": true,
  "cpus": {
    "0x41d8b": {"name": "C1-Pro", "drop_metrics": ["..."], "reason": "..."}
  }
}
```

- `match`: every criterion present must hold. Android properties are compared case-insensitively.
  A `dt_compatible` entry matches a device-tree root `compatible` string that starts with it.
  At least one criterion is required.
- `cycle_counter`: allow perf groups to hold CPU_CYCLES on top of the programmable counters, on
  the Arm PMU's dedicated cycle counter. The simpleperf backend also checks on the device that a
  group of CPU_CYCLES plus *N* programmable events is fully counted; if not, the option has no
  effect. Default `false` (previous behaviour).
- `cpus`: per core type, keyed by the CPU id used in `mapping.json`
  (`implementer << 12 | part number`, e.g. `0x41d8b` for C1-Pro). `drop_metrics` hides metrics
  whose formula does not hold on this SoC; `reason` is printed in the log.

## Adding a SoC

1. Run `topdown-tool --cpu-list-cores` and check that every core type has a specification
   (see `../specifications/derived/README.md` otherwise).
2. Find stable identification: `adb shell getprop ro.soc.manufacturer`,
   `getprop ro.soc.model`, or `/sys/firmware/devicetree/base/compatible`.
3. Measure before changing anything, with small benchmarks pinned to one core type:
   - slots: `(STALL_SLOT + OP_SPEC) / CPU_CYCLES` in a high-IPC loop must equal the
     specification's `num_slots`;
   - counters: `simpleperf stat --print-hw-counter`; whether CPU_CYCLES + *N* events fit in one
     group;
   - cache stall split: with working sets from L1 to DRAM size, check that
     `STALL_BACKEND_L1D + STALL_BACKEND_MEM ≈ STALL_BACKEND_MEMBOUND` and that each
     working set is attributed to the right level.
4. Write `soc/<vendor>_<soc>.json` with only the adjustments the measurements justify, and record
   the measurements below.
5. Add a matching case to `tests/cpu_probe/test_platform_adaptation.py`.

## Profiles

### Devices verified without a profile

| SoC | Cores | Why no profile is needed |
|-----|-------|--------------------------|
| Snapdragon 8 Gen 3 (SM8650) | Cortex-A520 ×2, Cortex-A720 ×5, Cortex-X4 ×1 | 18 programmable counters per core; the SoC-independent adjustments are already in the derived specifications. Their specifications contain no SME2 events, so the `sme` rule has no effect. |

### XRing O3 (`soc/xring_o3.json`)

Measured on a Xiaomi device with Android 17, kernel 6.18, simpleperf 1.build.26.10.23.

| CPUs | Core | MIDR | Max freq | Specification |
|------|------|------|----------|---------------|
| 0-3  | C1-Pro r1p2     | 0x411fd8b2 | 2.90 GHz | `lumex/arm_c1_pro_r1p2_pmu` |
| 4-7  | C1-Premium r1p0 | 0x411fd900 | 3.15 GHz | `lumex/arm_c1_premium_r0p0_pmu` (matched by CPU id) |
| 8-9  | C1-Ultra r1p0   | 0x411fd8c0 | 3.40 GHz | `lumex/arm_c1_ultra_r0p0_pmu` (matched by CPU id) |

**Slots.** `(STALL_SLOT + OP_SPEC) / CPU_CYCLES` was 5.00 (C1-Pro) and 10.00 (C1-Premium,
C1-Ultra) for high-IPC, memory-bound, frontend-bound and divide-bound loops, matching the
specifications. Topdown level 1 adds up to 100.0% in all cases.

**PMU counters.** The device tree uses the vendor driver `xring,armv8-pmuv3`, which splits the
counters: `perf = 0x7f` (counters 0-6 for Linux perf), `nn = 0x1fff80` (7-20) and
`deoc = 0x7fe00000` (21-30, used by the vendor `perf_particle` DVFS driver). simpleperf therefore
has 7 programmable counters plus the cycle counter (`--print-hw-counter` reports 8). A group of
CPU_CYCLES plus 7 INST_RETIRED events is fully counted on every core type, so the profile sets
`cycle_counter: true`.

**No SME unit.** No core reports `sme` in `/proc/cpuinfo` (the kernel has `CONFIG_ARM64_SME=y`),
and the CME events count 0. The `sme` feature rule hides the 14 SME2 metrics on every core type.

**C1-Pro backend cache split.** Pointer chase pinned to one core, share of
`STALL_BACKEND_MEMBOUND` cycles:

| Working set | C1-Pro L1D | C1-Pro MEM | C1-Premium L1D | C1-Premium MEM | C1-Ultra L1D | C1-Ultra MEM |
|-------------|-----------|-----------|----------------|----------------|--------------|--------------|
| 256 KB  | 0.92 | 0.07 | 0.96 | 0.03 | 0.99 | 0.01 |
| 2 MB    | 0.12 | 0.88 | 0.28 | 0.69 | 0.43 | 0.47 |
| 16 MB   | 0.74 | 0.20 | 0.06 | 0.90 | 0.10 | 0.81 |
| 128 MB  | 0.78 | 0.13 | 0.03 | 0.92 | 0.04 | 0.90 |

On C1-Premium and C1-Ultra, the share moves from L1D to MEM as the working set grows, as
expected. On C1-Pro it moves to MEM at 2 MB but back to L1D for DRAM-resident data, so
`backend_cache_l1d_bound` / `backend_cache_l2d_bound` would report a DRAM-bound loop as L1D
bound. The profile hides these two metrics on C1-Pro; `backend_mem_cache_bound` (their sum)
and the L2/LL cache effectiveness groups are kept. The frontend split (`STALL_FRONTEND_L1I` /
`STALL_FRONTEND_MEM`) behaves as expected on all three cores and is kept.

**Effect** (full analysis of a pointer chase pinned to one core type, scheduled groups and
metrics without a value):

| Core | Without adaptation | With adaptation |
|------|--------------------|-----------------|
| C1-Pro     | 32 groups, 4 empty  | 26 groups, 0 empty |
| C1-Premium | 32 groups, 10 empty | 28 groups, 3 empty |
| C1-Ultra   | 32 groups, 10 empty | 28 groups, 3 empty |

The remaining empty metrics are the SVE predicate percentages, whose denominator is 0 when the
program runs no SVE code. `-c group` failed without adaptation (Topdown_L1 needs 8 events with 7
counters) and works with it. Topdown level 1 values agree within 0.5 percentage points with and
without adaptation.
