# spe-parser

The `spe-parser` tool parses SPE (Statistical Profiling Extension) raw data and generates Parquet or CSV files for further processing and analysis.

For guidance on performance analysis with SPE, refer to the [Arm Statistical Profiling Extension: Performance Analysis Methodology White Paper](https://developer.arm.com/documentation/109429/latest/)

For an introduction to Statistical Profiling Extension, refer to the [Arm Architecture Reference Manual for A-profile architecture](https://developer.arm.com/documentation/ddi0487/latest/)

## Installation

Ensure you have the following prerequisites before installing the `spe-parser` tool:

- [uv](https://docs.astral.sh/uv/)
- python version 3.10 or higher

`spe-parser` uses uv to install dependencies from `pyproject.toml` and lock them in
`uv.lock`.

To install `spe-parser` in a local environment:

```bash
uv sync --locked --no-dev
```

To run `spe-parser` without installing it separately, prefix the normal command
with `uv run --locked`:

```bash
uv run --locked spe-parser perf.data
```

## Usage

To record SPE performance data:

```bash
perf record -e arm_spe_0/branch_filter=1,ts_enable=1,load_filter=1,jitter=1,store_filter=1,min_latency=0/ -- test_program
```

For more options and a detailed introduction, please refer to the  [Arm Statistical Profiling Extension: Performance Analysis Methodology White Paper](https://developer.arm.com/documentation/109429/latest/)

---
To parse the `perf` binary data and output in Parquet format:

```bash
uv run --locked spe-parser perf.data
```

---

To obtain output in CSV format:

```bash
uv run --locked spe-parser perf.data -t csv
```

---

To modify the output files prefix to `record1`:

```bash
uv run --locked spe-parser perf.data -t csv -p record1
```

This will result in the creation of three files: record1-ldst.csv, record1-br.csv, and record1-other.csv, corresponding respectively to Load/Store, Branch, and Other SPE packets.

---

The `spe-parser` will by default parse Load/Store, Branch, and Other SPE packets into three separate files. To disable parsing for a specific packet type, use the options below:

```bash
uv run --locked spe-parser perf.data --noldst --noother --nobr
```

---

To speed up parsing, increase concurrency; to use less resources, decrease it. By default, the system's core count is used. To change it:

```bash
uv run --locked spe-parser perf.data --concurrency 2
```

---

To include symbol information for corresponding instructions in the output files:

```bash
uv run --locked spe-parser perf.data --symbols
```

Please make sure your workload is compiled with debug information (e.g. -g).

---

To parse raw SPE fill buffer data (e.g. generated with [WindowsPerf](https://gitlab.com/Linaro/WindowsPerf/windowsperf)), use the options below:

```bash
uv run --locked spe-parser spe.data --raw-buffer
```

Please note that raw SPE buffer doesn't contain additional meta-data perf.data file contains, e.g. no symbol name resolution is possible.

---

To check the `spe-parser` version, which is crucial as the file schema may change between versions, the updates between each version can be found in the [Changelog](CHANGELOG.md):

```bash
uv run --locked spe-parser --version
```

---

For detailed scheme descriptions of output files, column explanations, and possible values and meanings:

```bash
uv run --locked spe-parser --help
```

## Development

Run tests using the following command.

```bash
uv run --locked --group tox tox
```

For now, please refrain from using pre-commit to install the .pre-commit-config.yaml configuration, and instead run make lint to check.

```bash
make lint
```

The tox test matrix uses the tox-uv plugin and syncs tox environments from
`uv.lock`. To run one environment explicitly:

```bash
uv run --locked --group tox tox -e py312
```

The full matrix includes Python 3.10 through 3.14. Missing local interpreters are
skipped by tox; CI is expected to provide the supported interpreter set.

Test data files are located under the spe_parser/tests/testdata/ directory. Some of them are binary files that are stored using git-lfs; working with them requires installing git-lfs (if not yet done so) by issuing `git lfs install`. Adding a new file is done by `git lfs track <file>`, then `git add` both this file and the resulting change in .gitattributes and then `git commit`. Updating a file is similar to updating regular git files: modify, then `git add` followed by `git commit`.
