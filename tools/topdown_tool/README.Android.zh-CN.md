# Arm Top-Down tool：Android 设备 TMA 分析使用指南

本指南介绍如何用 Arm Top-Down tool（`topdown-tool`）通过 `simpleperf` 对 Android 设备做 Topdown 微架构分析（TMA）。文中的命令和输出都在 Snapdragon 8 Gen 3（SM8650，Cortex-A520 ×2 + Cortex-A720 ×5 + Cortex-X4 ×1，Android 14，已 root）上实测过。

英文参考文档：[README.md](README.md)（总体用法）、[README.CPU.md](README.CPU.md)（CPU 探针选项）、[派生规范说明](../../data/pmu/cpu/specifications/derived/README.md)。

## 目录

1. [工作原理](#1-工作原理)
2. [准备工作](#2-准备工作)
3. [安装](#3-安装)
4. [连接设备](#4-连接设备)
5. [采集方式](#5-采集方式)
6. [选择采集内容](#6-选择采集内容)
7. [输出与 CSV](#7-输出与-csv)
8. [大中小核注意事项](#8-大中小核注意事项)
9. [解读结果](#9-解读结果)
10. [派生规范的限制](#10-派生规范的限制)
11. [其他 SoC 与 CPU 核](#11-其他-soc-与-cpu-核)
12. [常见问题](#12-常见问题)
13. [命令速查](#13-命令速查)

## 1. 工作原理

工具运行在 Linux 主机上，通过 adb（借助 devlib）控制设备：

1. 读取每个 CPU 核的 MIDR，按核型分组（例如 A520 / A720 / X4），为每种核型加载对应的遥测规范（事件、指标、Topdown 决策树）。
2. 按每种核型的可用计数器数量，把事件排成若干组，在设备上启动 `simpleperf stat` 计数。
3. 采集结束后把 simpleperf 的输出拉回主机，校正多路复用，计算指标，并按核型分别输出表格或 CSV。

所有被测程序都运行在设备上，路径也是设备上的路径。

## 2. 准备工作

### 2.1 主机

- Linux 主机，Python 3.10 或更新版本。
- [uv](https://docs.astral.sh/uv/)（Python 依赖管理工具）。
- `adb`，并能通过 `adb devices` 看到设备。

### 2.2 设备

- **已 root**：`adb root` 之后 `adb shell id` 显示 `uid=0(root)`，或设备上有可用的 `su`。系统级采集和 PMU 原始事件都需要 root。
- **有 simpleperf**：一般在 `/system/bin/simpleperf`。如果没有，工具会把 devlib 自带的 simpleperf 推到设备上。
- **内核开放了 CPU PMU**：`/sys/bus/event_source/devices/` 下有 `armv8_pmuv3`（或 `armv8_pmuv3_0` 等）。

检查命令：

```sh
adb devices -l
adb shell id
adb shell 'which simpleperf; simpleperf --version'
adb shell ls /sys/bus/event_source/devices/
adb shell simpleperf stat --print-hw-counter     # 每个核可用的硬件计数器数量
```

## 3. 安装

在仓库的 `tools/topdown_tool` 目录下操作。

**方式一：安装为命令行工具**（之后可以在任意目录运行 `topdown-tool`）：

```sh
cd tools/topdown_tool
git submodule update --init --recursive
uv run --no-project scripts/install_topdown_tool.py --remote
topdown-tool --help
```

**方式二：在源码目录里直接运行**（修改代码后立即生效，适合开发）：

```sh
cd tools/topdown_tool
git submodule update --init --recursive
uv sync --locked --extra remote --no-dev
uv run --locked --extra remote topdown-tool --help
```

`--remote` / `--extra remote` 会安装 devlib，这是连接 Android 设备必需的。下文的命令都写成 `topdown-tool`；用方式二时请替换为 `uv run --locked --extra remote topdown-tool`。

> 在源码目录里运行时，第一行会提示 `Missing topdown_tool._version metadata`，这不影响使用。

## 4. 连接设备

每次运行都要告诉工具连接哪台设备：

```sh
topdown-tool --target-type adb --target-config '{"device": "1e33dcf8"}' ...
```

`device` 是 `adb devices` 显示的序列号。为了少打字，也可以用环境变量，效果相同：

```sh
export TOPDOWN_TOOL_TARGET_TYPE=adb
export TOPDOWN_TOOL_TARGET_CONFIG='{"device": "1e33dcf8"}'
```

**下文的示例都假定已设置这两个环境变量。**

先确认工具识别出了所有核：

```text
$ topdown-tool --cpu-list-cores
        Available CPUs
┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ CPU         ┃ Cores indices ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ Cortex-A520 │ 0, 1          │
│ Cortex-A720 │ 2, 3, 4, 5, 6 │
│ Cortex-X4   │ 7             │
└─────────────┴───────────────┘
```

如果出现 `Unknown CPU at cores: ... (skipping capture)`，说明这种核没有遥测规范，见[第 11 节](#11-其他-soc-与-cpu-核)。

## 5. 采集方式

### 5.1 运行一个命令（适合 benchmark）

```sh
topdown-tool -- taskset 80 /data/local/tmp/my_benchmark --arg1
```

- `--` 后面是在设备上执行的命令（以 root 身份运行），命令结束时采集结束。
- 需要 `cd`、重定向或多条命令时，用 `sh -c`：

  ```sh
  topdown-tool -- sh -c 'cd /data/local/tmp && taskset 80 ./my_benchmark > /dev/null'
  ```

- **建议用 `taskset` 把程序绑定到一种核型上**，原因见[第 8 节](#8-大中小核注意事项)。`taskset` 的参数是十六进制 CPU 掩码，按 `--cpu-list-cores` 的结果计算。以 SM8650 为例：

  | 核型        | CPU   | 掩码 |
  |-------------|-------|------|
  | Cortex-A520 | 0-1   | `3`  |
  | Cortex-A720 | 2-6   | `7c` |
  | Cortex-X4   | 7     | `80` |

### 5.2 监控正在运行的进程（适合 App）

```sh
PID=$(adb shell pidof com.example.app)
topdown-tool -p "$PID"
```

- 按 Ctrl-C 停止采集，或者等进程退出后自动停止。按 Ctrl-C 后稍等几秒，工具会拉取数据并输出结果。
- 采集期间请操作 App（滑动、播放等），保证进程真正在运行。进程空闲时计数接近于零，大部分指标会显示 ❌。
- 一个 App 可能有多个进程，`pidof` 会返回多个 PID。一般选主进程。
- 只监控一个 PID 时，工具在每种核型上分别统计这个进程（`simpleperf stat -p PID --cpu <该核型的核>`），结果只包含该进程。
- 用逗号同时传多个 PID（`-p 1234,5678`）时，工具改为对各核做系统级统计（结果包含同一时间在这些核上运行的所有程序），直到这些进程全部退出。

### 5.3 系统级采集

不带命令也不带 `-p`：

```sh
topdown-tool              # 按 Ctrl-C 停止
topdown-tool -C 7         # 只统计 CPU 7
```

结果按单个核输出，同时给出每种核型的汇总（Aggregated 列）。系统级的结果包含这段时间内在这些核上运行的所有程序和内核。

## 6. 选择采集内容

默认采集全部内容：Stage 1（Topdown 指标）和 Stage 2（微架构指标组）。常用选项：

| 选项 | 作用 |
|------|------|
| `-s topdown` | 只采集 Stage 1，最快 |
| `-s uarch` | 只采集 Stage 2 |
| `-s combined` | 采集全部，并按 Topdown 决策树的层级输出 |
| `-n backend_mem_bound` | 只采集某个决策树节点及其子树 |
| `-m Topdown_L1,MPKI` | 只采集指定的指标组 |
| `--cpu-events-modifiers u` | 只统计用户态（EL0）；`k` 只统计内核态 |
| `--cpu-list-groups` | 列出每种核型的指标组 |
| `--cpu-list-metrics -d` | 列出指标及其说明 |
| `--cpu-list-events` | 列出事件 |

注意：

- 不同核型的指标组和指标不完全相同（例如 A520 没有 `SVE_Effectiveness`）。用 `-m` 指定的指标组在某个核型上不存在时，工具会给出警告并跳过这个组；如果指定的组在这个核型上都不存在，就跳过整个核型。
- 采集的事件越多，多路复用越多，每个事件实际计数的时间越短。对短时间运行的程序，可以用 `-s topdown` 或 `-m` 缩小范围。

## 7. 输出与 CSV

### 7.1 终端输出

每种核型输出一段，标题是 `CPU Cortex-X4 metrics` 这样的格式。值显示为 ❌ 表示没有数据（原因见[第 12 节](#12-常见问题)）。

系统级采集时表格每个核占一列，终端较窄时列会被截断，可以加大宽度：

```sh
COLUMNS=200 topdown-tool -C 2-6
```

### 7.2 CSV

```sh
topdown-tool --cpu-generate-csv metrics,events --csv-output-path out -- taskset 80 ./bench
```

结果写在 `out/<时间戳>/cpu/` 下：

| 采集方式 | 指标文件 | 事件文件 |
|----------|----------|----------|
| 命令、单个 PID | `cortex_x4_metrics.csv` | `cortex-x4_events.csv` |
| 系统级、多个 PID | `cortex_a720_core_3_metrics.csv`（每核一个）<br>`cortex_a720_core_aggregate_(2-6)_metrics.csv`（汇总） | 同上 |

指标文件的列是 `time,group,stage,level,metric,value,units`，事件文件的列是 `run,time,event,value`。CSV 里的 `nan` 对应终端里的 ❌。

### 7.3 按时间间隔采样

```sh
topdown-tool -p "$PID" -I 1000 --cpu-generate-csv metrics --csv-output-path out
```

`-I 1000` 每 1000 ms 输出一组数值，`time` 列是时间（秒）。`-I` 必须和 CSV 一起使用，此时不在终端输出表格。

### 7.4 调试文件

工具会在当前目录写入 `perf-cli-<N>`（实际执行的 simpleperf 命令）和 `perf.stat.cpu.<核型>.*`（simpleperf 原始输出）。结果异常时可以先看这两个文件。设备上的临时文件在 `/sdcard/devlib-target/topdown_perf/`。

## 8. 大中小核注意事项

这一节对 Android 设备很重要。

**每种核型单独计算。** 不同核型的流水线宽度、事件和指标公式不同，所以工具为每种核型使用各自的规范，分别输出结果。

**按进程采集时，结果只覆盖进程在该核型上运行的时间。** 调度器会把进程在大中小核之间迁移。如果进程在某种核型上只运行了很短时间，这段时间内某些多路复用的事件组可能一次都没被调度到，对应的指标就没有数据。工具会给出提示：

- `PID 1234 did not run on CPUs 0,1 during the capture; no data for these cores.`：进程没有在这些核上运行过，这种核型的结果全部是 ❌。这是正常现象。
- `PID 1234 ran only 0.8 ms on CPUs 0,1; 7 multiplexed events were never scheduled ...`：进程在这些核上运行时间太短，部分指标是 ❌。数值即使存在，样本也很少，参考价值有限。

要得到某种核型的完整结果：

- benchmark：用 `taskset` 绑核（[5.1 节](#51-运行一个命令适合-benchmark)）。
- App：延长采集时间，并在采集期间持续操作。也可以在 `/proc/<PID>/task/*` 上用 `taskset -p` 临时绑核，但这会改变 App 的真实行为。

**计数器数量。** SM8650 每个核有 18 个可用于分组的硬件计数器，工具会自动探测。一些高通设备的内存延迟调节器（`arm-memlat-mon`）会占用 PMU 计数器。如果探测到的数量明显偏少，可以让 simpleperf 在采集期间暂时释放这些计数器：

```sh
topdown-tool --perf-args=--use-devfreq-counters -- taskset 80 ./bench
```

这会在采集期间把内存延迟调节器换成 performance 调节器，从而影响内存延迟。注意 `--perf-args` 的值以 `--` 开头时必须用 `=` 连接。

## 9. 解读结果

### 9.1 分析流程

1. **看 Stage 1 的 Topdown Level 1**：四项加起来约 100%，含义如下。

   | 指标 | 含义 |
   |------|------|
   | Retiring | 流水线槽位被有用的操作占用。比例高说明执行效率高，进一步优化要减少指令数或使用 SIMD |
   | Bad Speculation | 槽位浪费在错误的推测执行上，通常是分支预测失败 |
   | Frontend Bound | 前端没能及时提供指令：取指、指令缓存、ITLB、分支预测器 |
   | Backend Bound | 后端无法接收操作：等待数据（内存），或执行单元繁忙（核心） |

2. **沿占比最大的一项往下钻**：Topdown_Frontend / Topdown_Backend 指标组给出下一层的分解，例如 Backend Bound 分为 Backend Core Bound 和 Backend Memory Bound。用 `-s combined` 可以直接看到树形结构。
3. **看 Stage 2 的相关指标组**：决策树的叶子节点会指向对应的指标组，例如 Backend Memory Bound → `L1D_Cache_Effectiveness`、`L2_Cache_Effectiveness`、`DTLB_Effectiveness`。用 MPKI、缺失率等指标确认瓶颈。
4. **定位代码**：确定瓶颈后，用 simpleperf record 对相应事件采样，找出热点函数。`--cpu-list-metrics --cpu-show-sample-events` 会列出每个指标建议采样的事件。

### 9.2 示例

在 X4 上运行一个随机访问 128 MB 内存的指针追逐程序：

```sh
topdown-tool -s combined -- taskset 80 /data/local/tmp/chase 134217728 40000000
```

结果（节选，已整理为简洁的树形格式）：

```text
Backend Bound                 97.7 %
├── Backend Core Bound         4.5 %
└── Backend Memory Bound      95.4 %
    ├── Backend Memory Cache Bound   94.7 %
    │   ├── Backend Cache L1D Bound   3.4 %
    │   └── Backend Cache L2D Bound  96.6 %
    ├── Backend Memory TLB Bound      7.7 %
    └── Backend Memory Store Bound   25.5 %
Retiring                       1.3 %     IPC 0.136
L1D Cache MPKI 20.7   L2 Cache MPKI 16.5   LL Cache Read MPKI 15.8   DTLB MPKI 17.0
```

解读：几乎所有槽位都是 Backend Bound，其中 95% 是等待内存；内存停顿几乎全部是 L2 缺失（L2D Bound 96.6%），每千条指令有约 16 次末级缓存缺失，DTLB 缺失也很多（17 MPKI）。优化方向是改善访存局部性、使用预取或大页。

## 10. 派生规范的限制

Arm 没有发布 Cortex-X4、Cortex-A720、Cortex-A520 的官方遥测规范。仓库里这三种核的规范是从后继核（X925、A725、C1-Nano）派生的，并按 SM8650 上的实测结果做了调整，质量等级是 Development。与官方规范相比：

| 核型 | 差异 |
|------|------|
| Cortex-X4 | 67 个指标全部保留，公式与 X925 相同 |
| Cortex-A720 | 没有 `frontend_core_flow_bound`；没有前端 L1I/L2I 拆分（`frontend_mem_cache_bound` 等 3 项）；后端 L1D/L2D 拆分改了公式，在 DRAM 级大工作集下 `backend_cache_l1d_bound` 可能略低于 0%（实测 -2.3%），按 0% 理解 |
| Cortex-A520 | 保留 66/119 个指标；没有 `backend_core_bound`（其子节点直接挂在 `backend_bound` 下）；没有 L1D/L2D、L1I/L2I 拆分；没有 SVE/SME/LSE 相关指标 |

另外，程序没有执行 SVE 指令时，三个 SVE Predicate 百分比指标的分母为 0，显示 ❌，这是正常现象。

调整的依据和实测数据见[派生规范说明](../../data/pmu/cpu/specifications/derived/README.md)。

## 11. 其他 SoC 与 CPU 核

**已有官方规范的核**（Cortex-X925、Cortex-A725、C1-Ultra/Premium/Pro/Nano 等，完整列表见 `data/pmu/cpu/mapping.json`）可以直接使用，步骤与本指南相同。

**没有规范的核**（例如 Cortex-A510、A710、A715、X2、X3）会显示 `Unknown CPU at cores`。可以按以下步骤派生规范：

1. 选一个有官方规范、流水线宽度和事件编码相近的核作为基础。
2. 用 `scripts/derive_cpu_spec.py` 生成规范：它会根据 [ARM-software/data](https://github.com/ARM-software/data/tree/master/pmu) 里该核的事件列表，去掉不存在或编码不同的事件和相应指标。
3. 在设备上测量流水线宽度（slots）：绑核运行一个高 IPC 的循环，计算 `(STALL_SLOT + OP_SPEC) / CPU_CYCLES`。如果和基础规范不同，加 `--num-slots N --rewrite-slots`。
4. 检查缓存停顿事件是互斥还是包含关系，必要时用 `--override-metric` / `--drop-metric` 调整。
5. 用 `topdown-tool --cpu my_core.json` 指定规范，或把它加入 `mapping.json`。

详细说明和完整命令见[派生规范说明](../../data/pmu/cpu/specifications/derived/README.md)。

## 12. 常见问题

**`Error: Insufficient privilege`**
设备没有 root 权限。执行 `adb root`，或确认设备上有可用的 `su`。

**`Error: The perf tool at ... is not runnable`**
设备上找不到 simpleperf，或 `--perf-path` 指定的路径不对。检查 `adb shell simpleperf --version`。也可以用 `--perf-path /data/local/tmp/simpleperf` 指定其他版本（例如 NDK 自带的 simpleperf）。

**`Unknown CPU at cores: ... (skipping capture)`**
这种核没有遥测规范，见[第 11 节](#11-其他-soc-与-cpu-核)。

**某种核型的指标全部是 ❌**
按进程采集时，进程没有在这种核型上运行，见[第 8 节](#8-大中小核注意事项)。

**部分指标是 ❌，日志里有 `Metric ... has incomplete perf data`**
对应的事件没有计数数据，通常是进程在该核型上运行时间太短，或公式分母为 0（例如没有 SVE 指令时的 SVE 指标）。

**`argument --perf-args: expected one argument`**
`--perf-args` 的值以 `-` 开头时要用 `=`：`--perf-args=--use-devfreq-counters`。

**指标略高于 100% 或略低于 0%**
多路复用的缩放误差和事件计数的微小差异会造成几个百分点的偏差。A720 的 `backend_cache_l1d_bound` / `backend_cache_l2d_bound` 见[第 10 节](#10-派生规范的限制)。

**想知道工具实际执行了什么**
看当前目录下的 `perf-cli-<N>` 和 `perf.stat.cpu.*` 文件，或加 `--log-level INFO`。

## 13. 命令速查

```sh
# 设备
export TOPDOWN_TOOL_TARGET_TYPE=adb
export TOPDOWN_TOOL_TARGET_CONFIG='{"device": "<序列号>"}'

# 查看核型、指标组、指标
topdown-tool --cpu-list-cores
topdown-tool --cpu-list-groups
topdown-tool --cpu-list-metrics -d

# benchmark 绑大核，完整分析，树形输出
topdown-tool -s combined -- taskset 80 /data/local/tmp/bench

# App 主进程，只看 Stage 1，Ctrl-C 结束
topdown-tool -p "$(adb shell pidof com.example.app)" -s topdown

# App 主进程，每秒一组数据，写 CSV
topdown-tool -p "$PID" -I 1000 --cpu-generate-csv metrics --csv-output-path out

# 系统级，只统计 CPU 2-6，宽表格
COLUMNS=200 topdown-tool -C 2-6

# 只看内存相关子树
topdown-tool -n backend_mem_bound -- taskset 80 ./bench

# 只统计用户态
topdown-tool --cpu-events-modifiers u -- taskset 80 ./bench

# 指定 simpleperf，传额外参数
topdown-tool --perf-path /data/local/tmp/simpleperf --perf-args=--use-devfreq-counters -- ./bench
```
