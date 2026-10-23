# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Tests for the simpleperf backend used on Android targets."""

import logging
import shlex
from signal import SIGINT
from typing import Dict, List, Optional

import pytest

from topdown_tool.common import remote_target_manager
from topdown_tool.perf.perf import Cpu, Uncore
from topdown_tool.perf.remote_simpleperf import (
    REFERENCE_EVENT,
    RemoteSimpleperf,
    parse_simpleperf_verbose_csv,
    scale_block,
    unique_event_names,
)
from tests.perf.conftest import FakeProcess, RecordingTarget


class _Event:
    def __init__(self, name: str) -> None:
        self.name = name

    def perf_name(self) -> str:
        return self.name

    def __lt__(self, other: "_Event") -> bool:
        return self.name < other.name


def _line(name: str, tid: int, cpu: int, count: int, enabled: int, running: int) -> str:
    return (
        f"{name},tid,{tid},cpu,{cpu},count,{count},time_enabled,{enabled},"
        f"time running,{running},id,1,"
    )


def _block(lines: List[str], seconds: float = 1.0) -> str:
    # Summary lines (non-verbose) are ignored by the parser; include one to make sure.
    return "\n".join(
        ["Performance counter statistics,", *lines, "123,r11,1.0,G/sec,", f"Total test time,{seconds},seconds,"]
    )


# Captured from simpleperf 1.build.26.09.23 on a Snapdragon 8 Gen 3 (-a --cpu 0,1).
SYSTEM_WIDE_OUTPUT = """Performance counter statistics,
r11,tid,-1,cpu,0,count,328521490,time_enabled,200544532,time running,200544532,id,1249721,
r11,tid,-1,cpu,1,count,318861130,time_enabled,200670313,time running,200670313,id,1249723,
r8,tid,-1,cpu,0,count,90727035,time_enabled,200719168,time running,200719168,id,1249722,
r8,tid,-1,cpu,1,count,80176141,time_enabled,200679844,time running,200679844,id,1249724,
r011,tid,-1,cpu,0,count,329261078,time_enabled,200655001,time running,200655001,id,1249725,
r011,tid,-1,cpu,1,count,319806979,time_enabled,200629793,time running,200629793,id,1249727,
r1b,tid,-1,cpu,0,count,97183079,time_enabled,200648490,time running,100324245,id,1249726,
r1b,tid,-1,cpu,1,count,85494815,time_enabled,200635001,time running,0,id,1249728,
0,328521490,r11,1.638,G/sec,
1,318861130,r11,1.589,G/sec,
Total test time,0.200249,seconds,
"""


# Parsing -----------------------------------------------------------------------------


def test_parse_system_wide_output() -> None:
    blocks = parse_simpleperf_verbose_csv(SYSTEM_WIDE_OUTPUT)

    assert len(blocks) == 1
    block = blocks[0]
    assert block.seconds == pytest.approx(0.200249)
    assert len(block.counters) == 8
    counter = block.counters[("r11", -1, 1)]
    assert (counter.count, counter.enabled, counter.running) == (318861130, 200670313, 200670313)


def test_parse_interval_output_returns_one_block_per_interval() -> None:
    text = "\n".join(
        [
            _block([_line("r11", -1, 0, 10, 100, 100)], seconds=0.1),
            _block([_line("r11", -1, 0, 20, 100, 100)], seconds=0.2),
        ]
    )
    blocks = parse_simpleperf_verbose_csv(text)

    assert [b.seconds for b in blocks] == [0.1, 0.2]
    assert [b.counters[("r11", -1, 0)].count for b in blocks] == [10, 20]


def test_parse_ignores_incomplete_trailing_block_and_noise() -> None:
    text = "warning: something\n" + _block([_line("r8", -1, 0, 5, 10, 10)]) + "\n"
    text += "Performance counter statistics,\n" + _line("r8", -1, 0, 7, 10, 10)
    blocks = parse_simpleperf_verbose_csv(text)

    assert len(blocks) == 1
    assert blocks[0].counters[("r8", -1, 0)].count == 5


def test_parse_handles_modifiers_in_event_names() -> None:
    blocks = parse_simpleperf_verbose_csv(_block([_line("r0011:u", -1, 3, 42, 10, 10)]))
    assert blocks[0].counters[("r0011:u", -1, 3)].count == 42


# Scaling -----------------------------------------------------------------------------


def test_scale_system_wide_per_cpu() -> None:
    block = parse_simpleperf_verbose_csv(SYSTEM_WIDE_OUTPUT)[0]
    values = scale_block(block, per_cpu=True)

    assert values[("r11", 0)] == 328521490
    # cpu0 ran half of the time: scaled by enabled/running.
    assert values[("r1b", 0)] == pytest.approx(97183079 * 200648490 / 100324245)
    # cpu1 never scheduled the counter: no data.
    assert values[("r1b", 1)] is None


def test_scale_system_wide_summed() -> None:
    block = parse_simpleperf_verbose_csv(SYSTEM_WIDE_OUTPUT)[0]
    values = scale_block(block, per_cpu=False)

    assert values[("r11", None)] == 328521490 + 318861130
    # cpu1 has no data for r1b; extrapolate from cpu0's share of the active time.
    cpu0 = 97183079 * 200648490 / 100324245
    assert values[("r1b", None)] == pytest.approx(cpu0 * (200648490 + 200635001) / 200648490)


def test_scale_counter_that_was_never_active_is_zero() -> None:
    block = parse_simpleperf_verbose_csv(_block([_line("r8", -1, 0, 0, 0, 0)]))[0]
    assert scale_block(block, per_cpu=True)[("r8", 0)] == 0.0


def test_scale_task_counters_use_reference_event() -> None:
    # Thread 10 ran 300 on cpu2 and 100 on cpu3 (per task-clock). time_enabled reports the
    # thread's total run time on every CPU file and must not be used for scaling.
    lines = [
        _line(REFERENCE_EVENT, 10, 2, 300, 1000, 300),
        _line(REFERENCE_EVENT, 10, 3, 100, 1000, 100),
        # Fully counted on cpu2, half of the time on cpu3.
        _line("r11", 10, 2, 3000, 1000, 300),
        _line("r11", 10, 3, 500, 1000, 50),
        # Never ran on cpu3.
        _line("r8", 10, 2, 600, 1000, 150),
        _line("r8", 10, 3, 0, 1000, 0),
    ]
    values = scale_block(parse_simpleperf_verbose_csv(_block(lines))[0], False, REFERENCE_EVENT)

    assert REFERENCE_EVENT not in {name for name, _ in values}
    assert values[("r11", None)] == pytest.approx(3000 + 500 * 100 / 50)
    # r8: 600 counted in half of cpu2's 300 -> 1200, extrapolated over cpu3's 100 -> 1600.
    assert values[("r8", None)] == pytest.approx(1200 * 400 / 300)


def test_scale_task_counters_without_runtime_have_no_data() -> None:
    lines = [_line(REFERENCE_EVENT, 10, 7, 0, 0, 0), _line("r11", 10, 7, 0, 0, 0)]
    values = scale_block(parse_simpleperf_verbose_csv(_block(lines))[0], False, REFERENCE_EVENT)
    assert values[("r11", None)] == 0.0


# Event naming ------------------------------------------------------------------------


def test_unique_event_names_pads_repeated_raw_events() -> None:
    groups = (
        (_Event("r11"), _Event("r8")),
        (_Event("r11"), _Event("r1b")),
        (_Event("r11:u"), _Event("r8")),
        (_Event("r11"),),
    )
    assert unique_event_names(groups) == [
        ["r11", "r8"],
        ["r011", "r1b"],
        ["r11:u", "r08"],
        ["r0011"],
    ]


def test_unique_event_names_rejects_repeated_symbolic_events() -> None:
    with pytest.raises(ValueError, match="non-raw"):
        unique_event_names(((_Event("instructions"),), (_Event("instructions"),)))


# Command construction ----------------------------------------------------------------


def test_build_command_system_wide() -> None:
    command = RemoteSimpleperf.build_stat_command(
        "/system/bin/simpleperf",
        "/data/out.txt",
        [["r11", "r8"], ["r1b"]],
        cores=[2, 3],
        pid=None,
        interval=None,
        timeout=None,
        perf_args=None,
    )
    assert command == [
        "/system/bin/simpleperf", "stat", "--csv", "--verbose", "-o", "/data/out.txt",
        "-a", "--cpu", "2,3", "--group", "r11,r8", "-e", "r1b",
    ]  # fmt: skip


def test_build_command_pid_interval_timeout_and_args() -> None:
    command = RemoteSimpleperf.build_stat_command(
        "simpleperf",
        "out",
        [["r11"]],
        cores=[7],
        pid=1234,
        interval=500,
        timeout=2500,
        perf_args="--use-devfreq-counters",
    )
    assert command[:6] == ["simpleperf", "stat", "--csv", "--verbose", "-o", "out"]
    assert "-a" not in command
    assert command[command.index("-p") + 1] == "1234"
    assert command[command.index("--interval") + 1] == "500"
    assert "--interval-only-values" in command
    assert command[command.index("--duration") + 1] == "2.5"
    assert "--use-devfreq-counters" in command
    # --cpu must come before every event it should apply to, including the reference.
    cpu_index = command.index("--cpu")
    assert command[cpu_index + 1] == "7"
    assert command[cpu_index + 2 : cpu_index + 4] == ["-e", REFERENCE_EVENT]
    assert command[-2:] == ["-e", "r11"]


def test_build_command_without_cores_has_no_cpu_option() -> None:
    command = RemoteSimpleperf.build_stat_command(
        "sp", "o", [["r11"]], cores=None, pid=None, interval=None, timeout=None, perf_args=None
    )
    assert "--cpu" not in command


# Recorder flow with a fake devlib target -----------------------------------------------


class _SimpleperfTarget(RecordingTarget):
    """Fake target that writes simpleperf output when the background command 'runs'."""

    def __init__(self, outputs: Dict[str, str]) -> None:
        super().__init__(working_directory="/data/local/tmp/devlib-target")
        self.os = "android"
        self.is_rooted = True
        self.executables_directory = "/data/local/tmp/bin"
        self.outputs = outputs
        self.files: Dict[str, str] = {}
        self.processes: List[FakeProcess] = []
        self.background_kwargs: List[dict] = []
        self.pull_impl = self._pull
        self.background_impl = self._background

    def _background(self, cmd: str) -> FakeProcess:
        args = shlex.split(cmd)
        output = args[args.index("-o") + 1]
        self.files[output] = self.outputs.get(output.rsplit("/", 1)[-1], "")
        process = FakeProcess()
        self.processes.append(process)
        return process

    def background(self, cmd: str, **kwargs) -> FakeProcess:  # type: ignore[override]
        self.background_kwargs.append(kwargs)
        return super().background(cmd, **kwargs)

    def execute(self, cmd: str, **kwargs) -> str:  # type: ignore[override]
        if "test -e" in cmd:
            # remote_path_exists() only falls back to the shell when file_exists() said no.
            self.exec_calls.append(cmd)
            raise RuntimeError("no such file")
        return super().execute(cmd, **kwargs)

    def file_exists(self, path: str) -> bool:
        return (
            path in self.files
            or path.startswith("/system/bin/")
            or path.endswith("/devlib-signal-target")
        )

    def _pull(self, remote: str, local: str) -> None:
        with open(local, "w", encoding="utf-8") as handle:
            handle.write(self.files[remote])


@pytest.fixture
def android_target(monkeypatch):
    def _make(outputs: Dict[str, str]) -> _SimpleperfTarget:
        target = _SimpleperfTarget(outputs)
        monkeypatch.setattr(remote_target_manager, "get_remote_target", lambda: target)
        return target

    monkeypatch.setattr(RemoteSimpleperf, "_simpleperf_path", None)
    return _make


def test_recorder_system_wide_flow(tmp_path, android_target) -> None:
    out = tmp_path / "perf.stat"
    target = android_target({"perf.stat-0": SYSTEM_WIDE_OUTPUT})
    perf = RemoteSimpleperf(target=target)

    groups = ((_Event("r11"), _Event("r8")), (_Event("r11"), _Event("r1b")))
    perf.start(groups, str(out), cores=[0, 1])

    assert len(target.background_calls) == 1
    cmd = target.background_calls[0]
    assert cmd.startswith("devlib-signal-target /system/bin/simpleperf stat")
    assert "--group r11,r8 --group r011,r1b" in cmd
    assert "2>" in cmd and cmd.endswith(".err")
    assert target.background_kwargs[0]["as_root"] is True
    assert (tmp_path / "perf-cli-0").read_text().startswith("/system/bin/simpleperf stat")

    perf.stop()
    assert target.processes[0].signals == [SIGINT]
    records = perf.get_perf_result()
    assert target.processes[0].wait_count == 1

    assert set(records) == {Cpu(0), Cpu(1)}
    cpu0 = records[Cpu(0)][None]
    assert cpu0[groups[0]] == (328521490, 90727035)
    assert cpu0[groups[1]][0] == 329261078
    assert cpu0[groups[1]][1] == pytest.approx(97183079 * 200648490 / 100324245)
    assert records[Cpu(1)][None][groups[1]][1] is None


def test_recorder_pid_flow_sums_threads_and_cpus(tmp_path, android_target, caplog) -> None:
    output = _block(
        [
            _line(REFERENCE_EVENT, 10, 2, 300_000, 900_000, 300_000),
            _line(REFERENCE_EVENT, 11, 3, 100_000, 100_000, 100_000),
            _line("r11", 10, 2, 3000, 900_000, 300_000),
            _line("r11", 11, 3, 1000, 100_000, 100_000),
            _line("r8", 10, 2, 50, 900_000, 300_000),
            _line("r8", 11, 3, 10, 100_000, 100_000),
        ]
    )
    target = android_target({"perf.stat-0": output})
    perf = RemoteSimpleperf(target=target)
    group = (_Event("r11"), _Event("r8"))

    perf.start((group,), str(tmp_path / "perf.stat"), pid=4321, cores=[2, 3])
    cmd = target.background_calls[0]
    assert "-p 4321" in cmd and "-a" not in cmd.split()
    assert f"--cpu 2,3 -e {REFERENCE_EVENT} --group r11,r8" in cmd

    perf.stop()
    caplog.set_level(logging.INFO)
    records = perf.get_perf_result()

    assert set(records) == {Uncore()}
    assert records[Uncore()][None][group] == (4000, 60)
    assert any("ran 0.4 ms on CPUs 2,3" in m for m in caplog.messages)


def test_recorder_pid_never_ran_warns(tmp_path, android_target, caplog) -> None:
    output = _block([_line(REFERENCE_EVENT, 10, 7, 0, 0, 0), _line("r11", 10, 7, 0, 0, 0)])
    target = android_target({"perf.stat-0": output})
    perf = RemoteSimpleperf(target=target)
    group = (_Event("r11"),)
    perf.start((group,), str(tmp_path / "perf.stat"), pid=99, cores=[7])
    perf.stop()

    caplog.set_level(logging.WARNING)
    records = perf.get_perf_result()

    assert records[Uncore()][None][group] == (0.0,)
    assert any("did not run on CPUs 7" in m for m in caplog.messages)


def test_recorder_interval_timestamps(tmp_path, android_target) -> None:
    output = "\n".join(
        [
            _block([_line("r11", -1, 0, 10, 100, 100)], seconds=0.5),
            _block([_line("r11", -1, 0, 30, 100, 100)], seconds=1.0),
        ]
    )
    target = android_target({"perf.stat-0": output})
    perf = RemoteSimpleperf(interval=500, target=target)
    group = (_Event("r11"),)
    perf.start((group,), str(tmp_path / "perf.stat"), cores=[0])
    assert "--interval 500 --interval-only-values" in target.background_calls[0]
    perf.stop()

    records = perf.get_perf_result()
    assert records[Cpu(0)] == {0.5: {group: (10.0,)}, 1.0: {group: (30.0,)}}


def test_recorder_start_fails_when_simpleperf_exits_early(tmp_path, android_target) -> None:
    target = android_target({})

    class _Exited(FakeProcess):
        def poll(self) -> Optional[int]:
            return 1

    target.background_impl = lambda _cmd: _Exited()
    target.execute_impl = lambda cmd: "Event type 'r11' appears more than once" if "cat" in cmd else ""
    perf = RemoteSimpleperf(target=target)

    with pytest.raises(RuntimeError, match="appears more than once"):
        perf.start(((_Event("r11"),),), str(tmp_path / "perf.stat"), cores=[0])


def test_recorder_empty_output_is_skipped(tmp_path, android_target, caplog) -> None:
    target = android_target({"perf.stat-0": "\n"})
    perf = RemoteSimpleperf(target=target)
    group = (_Event("r11"),)
    perf.start((group,), str(tmp_path / "perf.stat"), cores=[0])
    perf.stop()

    caplog.set_level(logging.WARNING)
    records = perf.get_perf_result()
    assert records[Cpu(0)] == {}
    assert any("produced no output" in m for m in caplog.messages)


def test_recorders_split_by_max_event_count(tmp_path, android_target, monkeypatch) -> None:
    outputs = {
        "perf.stat-0": _block([_line("r1", -1, 0, 1, 1, 1), _line("r2", -1, 0, 2, 1, 1)]),
        "perf.stat-1": _block([_line("r3", -1, 0, 3, 1, 1)]),
    }
    target = android_target(outputs)
    monkeypatch.setattr(RemoteSimpleperf, "max_event_count", property(lambda self: 1))
    perf = RemoteSimpleperf(target=target)
    g1, g2 = (_Event("r1"), _Event("r2")), (_Event("r3"),)
    perf.start((g1, g2), str(tmp_path / "perf.stat"), cores=[0])
    perf.stop()

    assert len(target.background_calls) == 2
    assert perf.get_perf_result()[Cpu(0)][None] == {g1: (1.0, 2.0), g2: (3.0,)}


# Binary resolution and capability queries ----------------------------------------------


def test_resolve_simpleperf_prefers_override_then_system(android_target, monkeypatch) -> None:
    target = android_target({})
    assert RemoteSimpleperf.resolve_simpleperf(target) == "/system/bin/simpleperf"

    monkeypatch.setattr(RemoteSimpleperf, "_simpleperf_path", "/data/local/tmp/simpleperf")
    assert RemoteSimpleperf.resolve_simpleperf(target) == "/data/local/tmp/simpleperf"


def test_is_remote_runnable_checks_version_output(android_target) -> None:
    target = android_target({})
    target.execute_impl = lambda cmd: "simpleperf I command.cpp:270] Simpleperf version 1.build"
    assert RemoteSimpleperf.is_remote_runnable(target, None)

    target.execute_impl = lambda cmd: "/system/bin/sh: simpleperf: not found"
    assert not RemoteSimpleperf.is_remote_runnable(target, None)


def test_have_perf_privilege_true_when_rooted(android_target) -> None:
    android_target({})
    assert RemoteSimpleperf.have_perf_privilege() is True


def test_get_pmu_counters_binary_search(android_target) -> None:
    target = android_target({})
    hardware_counters = 6

    def execute(cmd: str) -> str:
        names = shlex.split(cmd)[shlex.split(cmd).index("--group") + 1].split(",")
        lines = []
        for index, name in enumerate(names):
            running = 1000 if len(names) <= hardware_counters else 1000 * index // len(names)
            lines.append(_line(name, -1, 4, 5, 1000, running))
        return _block(lines)

    target.execute_impl = execute
    assert RemoteSimpleperf.get_pmu_counters(4) == hardware_counters
    probes = [cmd for cmd in target.exec_calls if "--group" in cmd]
    assert probes and all("--cpu 4" in cmd and "-a" in cmd.split() for cmd in probes)


def test_cmn_queries_are_unsupported() -> None:
    with pytest.raises(RuntimeError):
        RemoteSimpleperf.get_cmn_version()
