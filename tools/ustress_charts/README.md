# Chart generating script

`ustress-charts.py` uses Arm Top-Down tool to capture metric data for selected ustress suite workloads and then generates charts from collected data.

## Getting started

`ustress-charts.py` uses [uv](https://docs.astral.sh/uv/) for its plotting
dependencies. From the repository root, initialize the tool data submodule and
install Top-Down once as a persistent uv tool so the script can find the
`topdown-tool` executable on your `PATH`:

```sh
git submodule update --init --recursive
uv run --no-project ./tools/topdown_tool/scripts/install_topdown_tool.py
topdown-tool --help
```

The installer validates Top-Down's `uv.lock` before creating the persistent
tool, so its runtime package versions and Git commit SHAs match the lockfile.
Plain `uv tool install ./tools/topdown_tool` re-resolves dependencies and is
not lock-enforced; rerun the installer after updating the checkout.

Then run the chart script from its directory:

```sh
cd tools/ustress_charts
uv run --locked ./ustress-charts.py --help
```

Repository developers can run `uv sync --locked` in this directory to create
the local environment for the chart script's plotting dependencies. This does
not install Top-Down tool; use the locked persistent installation above.

To generate your first charts using `ustress-charts.py`, ensure that:

1. UStress workloads are built under `benchmarks/ustress`.
1. perf monitoring is possible. This can be achieved by running
   `echo -1 >/proc/sys/kernel/perf_event_paranoid` as root.

Then use the following command:

```sh
uv run --locked ./ustress-charts.py --workload branch_direct_workload branch_indirect_workload
```

Collected data will be saved to `dataset_branch_direct_workload_cpu0_run0.csv` and `dataset_branch_indirect_workload_cpu0_run0.csv`.

Charts will be saved to `*.png` files for each metric group with the same measurement units.

## Going further

`ustress-charts.py` includes options to adjust the capture such as setting the CPU number on which a worload must run, allowing/disallowing PMU multiplexing, selecting the collection mode, selecting the PMU grouping mode, repeating running of worloads given number of times.

Invoke the script with the `--help` option to view additional options.


## Limitations

1. It is not possible to pass arguments to workloads
2. All selected workloads will run on the same single CPU
