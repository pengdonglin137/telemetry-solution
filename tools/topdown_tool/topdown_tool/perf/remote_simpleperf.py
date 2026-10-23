# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Remote Android perf runner built on ``simpleperf stat``.

Android devices ship ``simpleperf`` (``/system/bin/simpleperf``) rather than Linux ``perf``.
This backend drives it through a devlib target and converts its output into the
:class:`~topdown_tool.perf.perf.PerfRecords` structure used by the probes.

simpleperf differs from ``perf stat`` in ways that matter here:

* system-wide counting needs ``-a``; ``--cpu`` only affects the events listed after it.
* the same event name may not appear twice in one invocation, so repeated raw events are
  zero-padded (``r11``, ``r011``, ...). simpleperf parses the code as hex, so the padded names
  select the same hardware event.
* summary counts are not scaled for multiplexing. The backend parses the ``--verbose`` per-fd
  lines (count, time enabled, time running) and scales the counts itself.
* ``-p`` can be combined with ``--cpu``, which counts a process only while it runs on the given
  cores. This allows per-process collection on heterogeneous (big.LITTLE) systems.
"""

import logging
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from importlib.resources import as_file, files
from pathlib import Path
from signal import SIGINT
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from topdown_tool.common import remote_target_manager
from topdown_tool.common.devlib_types import Target
from topdown_tool.common.remote_utils import remote_path_exists
from topdown_tool.perf.linux_perf_base import LinuxPerfBase
from topdown_tool.perf.perf import (
    Cpu,
    PerfEventGroup,
    PerfRecordLocation,
    PerfRecords,
    PerfResults,
    PerfTimedResults,
    Uncore,
)
from topdown_tool.perf.remote_linux_perf import RemoteLinuxPerf

_VERBOSE_LINE = re.compile(
    r"^(?P<name>.+),tid,(?P<tid>-?\d+),cpu,(?P<cpu>-?\d+),count,(?P<count>\d+),"
    r"time_enabled,(?P<enabled>\d+),time running,(?P<running>\d+),id,\d+,?$"
)
_BLOCK_START = "Performance counter statistics,"
_BLOCK_END = re.compile(r"^Total test time,(?P<seconds>[0-9.]+),seconds,?$")
_RAW_EVENT = re.compile(r"^r(?P<code>[0-9a-fA-F]+)$")

#: Software event counted next to the hardware events in PID mode. It is never multiplexed, so
#: its ``time_running`` is the time each thread ran on each CPU.
REFERENCE_EVENT = "task-clock"


def _base_name(event_name: str) -> str:
    """Return ``event_name`` without its ``:modifier`` suffix."""
    return event_name.split(":", 1)[0]


_READY_TIMEOUT_S = 15.0
_READY_POLL_S = 0.02
_PROBE_DURATION_S = 0.05


@dataclass
class _Counter:
    """Raw counter values for one event file descriptor (or a sum of them)."""

    count: int = 0
    enabled: int = 0
    running: int = 0


@dataclass
class SimpleperfBlock:
    """Counters printed by simpleperf for one reporting period."""

    seconds: Optional[float] = None
    # (event name, tid, cpu) -> counter
    counters: Dict[Tuple[str, int, int], _Counter] = field(default_factory=dict)


def parse_simpleperf_verbose_csv(text: str) -> List[SimpleperfBlock]:
    """Parse ``simpleperf stat --csv --verbose`` output into reporting blocks.

    Args:
        text: Content of the simpleperf output file.

    Returns:
        One block per report (a single block without ``--interval``).
    """
    blocks: List[SimpleperfBlock] = []
    current: Optional[SimpleperfBlock] = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == _BLOCK_START:
            current = SimpleperfBlock()
            continue
        end = _BLOCK_END.match(line)
        if end:
            if current is not None:
                current.seconds = float(end.group("seconds"))
                blocks.append(current)
            current = None
            continue
        match = _VERBOSE_LINE.match(line)
        if match is None or current is None:
            continue
        # simpleperf prints the event type without its ":u"/":k" modifier in verbose lines.
        name = _base_name(match.group("name"))
        key = (name, int(match.group("tid")), int(match.group("cpu")))
        counter = current.counters.setdefault(key, _Counter())
        counter.count += int(match.group("count"))
        counter.enabled += int(match.group("enabled"))
        counter.running += int(match.group("running"))
    return blocks


def scale_block(  # pylint: disable=too-many-locals
    block: SimpleperfBlock,
    per_cpu: bool,
    reference: Optional[str] = None,
) -> Dict[Tuple[str, Optional[int]], Optional[float]]:
    """Return multiplexing-scaled counts for a block.

    Each counter file descriptor reports ``count``, ``time_running`` and an "active" time during
    which it should have been counting. A counter that ran for only part of the active time was
    multiplexed and is scaled by ``active / running``.

    * CPU-wide counters (``tid == -1``) are active for their whole ``time_enabled``.
    * Task counters restricted with ``--cpu`` report the task's run time on *every* CPU as
      ``time_enabled``, so it cannot be used. The active time is instead the ``time_running``
      of the ``reference`` software event (``task-clock``) for the same thread and CPU, which is
      never multiplexed and equals the time the thread ran on that CPU.

    Descriptors that were active but never scheduled have no data. Their share is
    extrapolated from the descriptors that did run.

    Args:
        block: Parsed simpleperf block.
        per_cpu: Return values keyed by CPU (``True``) or summed over CPUs (``False``).
        reference: Name of the per-thread reference event, if one was counted.

    Returns:
        Mapping ``(event name, cpu or None) -> scaled value``; ``None`` means no data.
    """
    # (name, cpu or None) -> [scaled sum, covered active time, total active time]
    sums: Dict[Tuple[str, Optional[int]], List[float]] = {}
    for (name, tid, cpu), counter in block.counters.items():
        if name == reference:
            continue
        if tid == -1 or reference is None:
            active = counter.enabled
        else:
            ref = block.counters.get((reference, tid, cpu))
            active = ref.running if ref is not None else counter.enabled
        entry = sums.setdefault((name, cpu if per_cpu else None), [0.0, 0.0, 0.0])
        entry[2] += active
        if counter.running > 0:
            entry[0] += counter.count * max(active, counter.running) / counter.running
            entry[1] += active
    result: Dict[Tuple[str, Optional[int]], Optional[float]] = {}
    for key, (scaled_sum, covered, total) in sums.items():
        if total == 0:
            result[key] = scaled_sum
        elif covered == 0:
            result[key] = None
        else:
            result[key] = scaled_sum * total / covered
    return result


def unique_event_names(events: Sequence[PerfEventGroup]) -> List[List[str]]:
    """Give each event occurrence a distinct simpleperf name.

    Raw events (``rNN`` with an optional ``:modifier``) whose base name appears more than once
    get leading zeros on their code. Uniqueness is checked without the modifier, because
    simpleperf reports counters by base name (``r11:u`` is printed as ``r11``).

    Raises:
        ValueError: If a non-raw event name appears more than once.
    """
    seen: Dict[str, int] = {}
    names: List[List[str]] = []
    for group in events:
        group_names: List[str] = []
        for event in group:
            perf_name = event.perf_name()
            base, sep, modifier = perf_name.partition(":")
            occurrence = seen.get(base, 0)
            seen[base] = occurrence + 1
            if occurrence == 0:
                group_names.append(perf_name)
                continue
            raw = _RAW_EVENT.match(base)
            if raw is None:
                raise ValueError(
                    f"simpleperf cannot count non-raw event {perf_name!r} twice in one run"
                )
            group_names.append(f"r{'0' * occurrence}{raw.group('code')}{sep}{modifier}")
        names.append(group_names)
    return names


def _to_text(output: Any) -> str:
    if isinstance(output, (bytes, bytearray)):
        return output.decode("utf-8", errors="replace")
    return str(output)


class RemoteSimpleperf(LinuxPerfBase):
    """Run ``simpleperf stat`` on a remote Android device via devlib."""

    #: ``pid`` and ``cores`` may be combined: the process is counted only on ``cores``.
    SUPPORTS_PID_WITH_CORES = True

    _simpleperf_path: Optional[str] = None

    class _Recorder(LinuxPerfBase._Recorder):  # pylint: disable=protected-access
        """One simpleperf process counting a bin of event groups."""

        # pylint: disable=too-many-arguments
        def __init__(
            self,
            events: Sequence[PerfEventGroup],
            *,
            target: "Target",
            simpleperf_path: str,
            remote_dir: str,
            as_root: bool,
            cli_filename: Path,
            output_filename: str,
            cores: Optional[Sequence[int]],
            perf_args: Optional[str],
            interval: Optional[int],
            pid: Optional[int],
            timeout: Optional[int],
        ) -> None:
            super().__init__(events=events, output_filename=output_filename)
            self._target = target
            self._as_root = as_root
            self._cli_filename = cli_filename
            self._remote_output = f"{remote_dir}/{Path(output_filename).name}"
            self._remote_stderr = f"{self._remote_output}.err"
            self._names = unique_event_names(events)
            self._process: Any = None
            self._pulled = False
            self._command = RemoteSimpleperf.build_stat_command(
                simpleperf_path,
                self._remote_output,
                self._names,
                cores=cores,
                pid=pid,
                interval=interval,
                timeout=timeout,
                perf_args=perf_args,
            )
            LinuxPerfBase._initialize_output_file(output_filename)

        @property
        def names(self) -> List[List[str]]:
            return self._names

        @property
        def command(self) -> List[str]:
            return list(self._command)

        def _execute(self, command: str) -> str:
            return _to_text(
                self._target.execute(command, check_exit_code=False, as_root=self._as_root)
            )

        def start(self) -> None:
            if not self._events:
                logging.info("Empty run with no events")
                return
            LinuxPerfBase.write_cli_command(self._cli_filename, self._command)
            self._execute(
                f"rm -f {shlex.quote(self._remote_output)} {shlex.quote(self._remote_stderr)}"
            )
            cmd = " ".join(shlex.quote(arg) for arg in self._command)
            cmd = f"devlib-signal-target {cmd} 2>{shlex.quote(self._remote_stderr)}"
            try:
                self._process = self._target.background(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    as_root=self._as_root,
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                raise RuntimeError(f"Failed to start simpleperf on target: {exc}") from exc
            logging.info("Remote simpleperf started: %s", cmd)
            self._wait_until_counting()

        def _wait_until_counting(self) -> None:
            # simpleperf opens the output file right after the counters are opened and enabled,
            # so its existence marks the start of counting.
            deadline = time.monotonic() + _READY_TIMEOUT_S
            while time.monotonic() < deadline:
                if remote_path_exists(self._target, self._remote_output):
                    return
                poll = getattr(self._process, "poll", None)
                if callable(poll) and poll() is not None:  # pylint: disable=not-callable
                    self._process = None
                    raise RuntimeError(
                        "simpleperf exited before counting started: " + self._stderr_text()
                    )
                time.sleep(_READY_POLL_S)
            logging.warning(
                "simpleperf did not create %s within %.0fs; continuing anyway",
                self._remote_output,
                _READY_TIMEOUT_S,
            )

        def _stderr_text(self) -> str:
            try:
                text = self._execute(f"cat {shlex.quote(self._remote_stderr)}").strip()
            except Exception:  # pylint: disable=broad-exception-caught
                return "<stderr unavailable>"
            return text or "<no stderr output>"

        def stop(self) -> None:
            if self._process is None:
                return
            try:
                self._process.send_signal(SIGINT)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.warning("Failed to send SIGINT to simpleperf: %s", exc)

        def wait(self) -> None:
            if self._process is None:
                return
            try:
                self._process.wait()
            finally:
                self._process = None
            self._pulled = self._pull()

        def _pull(self) -> bool:
            try:
                self._target.pull(self._remote_output, self._output_filename, as_root=self._as_root)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.warning(
                    "Failed to pull %s: %s (simpleperf stderr: %s)",
                    self._remote_output,
                    exc,
                    self._stderr_text(),
                )
                return False
            with open(self._output_filename, encoding="utf-8") as handle:
                if not handle.read().strip():
                    logging.warning(
                        "simpleperf produced no output (stderr: %s)", self._stderr_text()
                    )
                    return False
            logging.debug("simpleperf stderr: %s", self._stderr_text())
            return True

        def prepare_output(self) -> bool:
            return self._pulled

    def __init__(
        self,
        *,
        perf_args: Optional[str] = None,
        interval: Optional[int] = None,
        target: Optional["Target"] = None,
    ) -> None:
        super().__init__(perf_args=perf_args, interval=interval)
        resolved = target or remote_target_manager.get_remote_target()
        if resolved is None:
            raise RuntimeError("RemoteSimpleperf requires a configured devlib target")
        self._target: "Target" = resolved
        self._pid: Optional[int] = None
        self._binary: Optional[str] = None
        self._remote_dir: Optional[str] = None

    # Command construction ------------------------------------------------------
    # pylint: disable=too-many-arguments
    @staticmethod
    def build_stat_command(
        simpleperf_path: str,
        output_filename: str,
        event_names: Sequence[Sequence[str]],
        *,
        cores: Optional[Sequence[int]],
        pid: Optional[int],
        interval: Optional[int],
        timeout: Optional[int],
        perf_args: Optional[str],
    ) -> List[str]:
        """Build the ``simpleperf stat`` argument list."""
        command = [simpleperf_path, "stat", "--csv", "--verbose", "-o", output_filename]
        if pid is not None:
            command.extend(["-p", str(pid)])
        else:
            command.append("-a")
        if interval is not None:
            command.extend(["--interval", str(interval), "--interval-only-values"])
        if timeout is not None:
            command.extend(["--duration", f"{timeout / 1000:g}"])
        if perf_args:
            command.extend(shlex.split(perf_args))
        # --cpu applies to the events that follow it.
        if cores is not None:
            command.extend(["--cpu", ",".join(map(str, cores))])
        if pid is not None:
            # Reference for multiplexing correction of task counters (see scale_block).
            command.extend(["-e", REFERENCE_EVENT])
        for names in event_names:
            if len(names) > 1:
                command.extend(["--group", ",".join(names)])
            else:
                command.extend(["-e", names[0]])
        return command

    # LinuxPerfBase hooks ---------------------------------------------------------
    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def start(
        self,
        events_groups: Sequence[PerfEventGroup],
        output_filename: str,
        pid: Optional[int] = None,
        cores: Optional[Sequence[int]] = None,
        timeout: Optional[int] = None,
    ) -> None:
        self._pid = pid
        super().start(events_groups, output_filename, pid=pid, cores=cores, timeout=timeout)

    def _before_start(self) -> None:
        self._binary = self.resolve_simpleperf(self._target)
        self._remote_dir = RemoteLinuxPerf.remote_workdir(self._target)
        try:
            self._target.execute(
                f"mkdir -p {shlex.quote(self._remote_dir)}",
                check_exit_code=False,
                as_root=_use_root(self._target),
            )
        except Exception:  # pylint: disable=broad-exception-caught
            self._remote_dir = "/data/local/tmp"
        self._ensure_signal_helper(self._target)

    def _recorder_kwargs(
        self,
        *,
        events: Sequence[PerfEventGroup],
        cli_path: Path,
        output_basename: str,
        pid: Optional[int],
        timeout: Optional[int],
    ) -> Dict[str, Any]:
        kwargs = super()._recorder_kwargs(
            events=events,
            cli_path=cli_path,
            output_basename=output_basename,
            pid=pid,
            timeout=timeout,
        )
        kwargs.update(
            target=self._target,
            simpleperf_path=self._binary or "simpleperf",
            remote_dir=self._remote_dir or "/data/local/tmp",
            as_root=_use_root(self._target),
            # One file per recorder and per core type ("perf-cli-<index>" would be shared by
            # every CPU probe and overwritten).
            cli_filename=cli_path.with_name(f"{Path(output_basename).name}.cmd"),
        )
        return kwargs

    def get_perf_result(self) -> PerfRecords:  # pylint: disable=too-many-locals
        """Collect recorder outputs into ``PerfRecords``.

        Without a PID the results are reported per CPU in ``cores``. With a PID they are summed
        over threads and CPUs and reported under :class:`Uncore`.
        """
        per_cpu = self._pid is None and self._cores is not None
        reference = REFERENCE_EVENT if self._pid is not None else None
        if per_cpu:
            assert self._cores is not None
            locations: List[PerfRecordLocation] = [Cpu(core) for core in self._cores]
        else:
            locations = [Uncore()]
        records = PerfRecords({location: PerfTimedResults() for location in locations})

        for recorder in self._recorders:
            recorder.wait()
            if not recorder.events or not recorder.prepare_output():
                continue
            assert isinstance(recorder, RemoteSimpleperf._Recorder)
            with open(recorder.output_filename, encoding="utf-8") as handle:
                blocks = parse_simpleperf_verbose_csv(handle.read())
            if reference is not None and blocks:
                self._report_pid_runtime(blocks)
            for block in blocks:
                timestamp = block.seconds if self._interval is not None else None
                values = scale_block(block, per_cpu, reference)
                for location in locations:
                    cpu = location.id if isinstance(location, Cpu) else None
                    results = records[location].setdefault(timestamp, PerfResults())
                    for group, names in zip(recorder.events, recorder.names):
                        results[tuple(group)] = tuple(
                            values.get((_base_name(name), cpu)) for name in names
                        )
        return records

    def _report_pid_runtime(self, blocks: Sequence[SimpleperfBlock]) -> None:
        """Warn when the tracked process ran too little on these cores to count every event."""
        ran_ns = 0
        unscheduled: Set[str] = set()
        for block in blocks:
            for (name, _tid, _cpu), counter in block.counters.items():
                if name == REFERENCE_EVENT:
                    ran_ns += counter.running
            for (event_name, _location), value in scale_block(
                block, False, REFERENCE_EVENT
            ).items():
                if value is None:
                    unscheduled.add(event_name)
        cores = ",".join(map(str, self._cores or [])) or "all"
        if ran_ns == 0:
            logging.warning(
                "PID %s did not run on CPUs %s during the capture; no data for these cores.",
                self._pid,
                cores,
            )
        elif unscheduled:
            logging.warning(
                "PID %s ran only %.1f ms on CPUs %s; %d multiplexed events were never scheduled "
                "in that time, so metrics using them are unavailable for these cores.",
                self._pid,
                ran_ns / 1e6,
                cores,
                len(unscheduled),
            )
        else:
            logging.info("PID %s ran %.1f ms on CPUs %s", self._pid, ran_ns / 1e6, cores)

    # Binary / helper provisioning -------------------------------------------------
    @classmethod
    def update_perf_path(cls, perf_path: str) -> None:
        cls._simpleperf_path = perf_path

    @classmethod
    def resolve_simpleperf(cls, target: "Target") -> str:
        """Return the simpleperf path on the target, pushing devlib's copy if needed."""
        if cls._simpleperf_path:
            if cls._simpleperf_path.startswith("/") or "/" not in cls._simpleperf_path:
                return cls._simpleperf_path
            return f"{RemoteLinuxPerf.remote_workdir(target)}/{cls._simpleperf_path}"
        for candidate in ("/system/bin/simpleperf", "/system/xbin/simpleperf"):
            if remote_path_exists(target, candidate):
                return candidate
        bin_dir = _executables_dir(target)
        bundled = f"{bin_dir}/simpleperf"
        if remote_path_exists(target, bundled):
            return bundled
        try:
            # pylint: disable=import-outside-toplevel, import-error
            import devlib.bin  # type: ignore

            resource = files(devlib.bin).joinpath(f"{getattr(target, 'abi')}/simpleperf")
            with as_file(resource) as host_path:
                RemoteLinuxPerf._install_binary(  # pylint: disable=protected-access
                    target, str(host_path), bundled
                )
            return bundled
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.warning("Failed to provision simpleperf on target: %s", exc)
            return "simpleperf"

    @staticmethod
    def _ensure_signal_helper(target: "Target") -> None:
        destination = f"{_executables_dir(target)}/devlib-signal-target"
        if remote_path_exists(target, destination):
            return
        try:
            # pylint: disable=import-outside-toplevel, import-error
            import devlib.bin  # type: ignore

            resource = files(devlib.bin).joinpath("scripts/devlib-signal-target")
            with as_file(resource) as helper:
                RemoteLinuxPerf._install_binary(  # pylint: disable=protected-access
                    target, str(helper), destination
                )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.warning("Failed to provision devlib-signal-target: %s", exc)

    @classmethod
    def is_remote_runnable(cls, target: "Target", perf_path: Optional[str]) -> bool:
        """Return whether simpleperf can be executed on the target."""
        binary = perf_path or cls.resolve_simpleperf(target)
        try:
            output = target.execute(
                f"{shlex.quote(binary)} --version", check_exit_code=False, as_root=_use_root(target)
            )
        except Exception:  # pylint: disable=broad-exception-caught
            return False
        # Device output: "simpleperf I command.cpp:270] Simpleperf version 1.build...".
        return "simpleperf version" in _to_text(output).lower()

    # Capability queries ----------------------------------------------------------
    @staticmethod
    def have_perf_privilege() -> bool:
        target = remote_target_manager.get_remote_target()
        if target is None:
            return True
        if _use_root(target):
            return True
        return RemoteLinuxPerf.have_perf_privilege()

    @classmethod
    def get_pmu_counters(cls, core: int) -> int:
        """Return how many raw events fit in one fully scheduled group on ``core``."""
        target = remote_target_manager.get_remote_target()
        if target is None:
            raise RuntimeError("Remote PMU counter query requires a configured target")
        binary = cls.resolve_simpleperf(target)
        as_root = _use_root(target)

        def check(count: int) -> bool:
            if count == 0:
                return True
            names = ",".join(f"r{'0' * i}8" for i in range(count))
            command = (
                f"{shlex.quote(binary)} stat -a --csv --verbose --cpu {core} "
                f"--group {names} --duration {_PROBE_DURATION_S} 2>/dev/null"
            )
            try:
                text = _to_text(
                    target.execute(command, timeout=10, check_exit_code=False, as_root=as_root)
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.warning("simpleperf PMU probe failed for %d events: %s", count, exc)
                return False
            blocks = parse_simpleperf_verbose_csv(text)
            if not blocks or len(blocks[0].counters) != count:
                return False
            return all(
                c.running > 0 and c.running == c.enabled for c in blocks[0].counters.values()
            )

        counters = LinuxPerfBase._binary_search_pmu_max(check)
        logging.info("Detected %d PMU counters on core %d (simpleperf)", counters, core)
        return counters

    @classmethod
    def has_cycle_counter(cls, core: int, programmable: int) -> bool:
        """Return whether CPU_CYCLES fits next to ``programmable`` raw events in one group.

        The Arm PMU has a dedicated cycle counter. When the kernel uses it for CPU_CYCLES, a
        group can hold one CPU_CYCLES event on top of the programmable counters. This is
        checked on the device: CPU_CYCLES plus ``programmable`` INST_RETIRED events must all
        be counted for the whole run.
        """
        target = remote_target_manager.get_remote_target()
        if target is None or programmable <= 0:
            return False
        names = ",".join(["r11"] + [f"r{'0' * i}8" for i in range(programmable)])
        command = (
            f"{shlex.quote(cls.resolve_simpleperf(target))} stat -a --csv --verbose --cpu {core} "
            f"--group {names} --duration {_PROBE_DURATION_S} 2>/dev/null"
        )
        try:
            text = _to_text(
                target.execute(command, timeout=10, check_exit_code=False, as_root=_use_root(target))
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.warning("simpleperf cycle counter probe failed: %s", exc)
            return False
        blocks = parse_simpleperf_verbose_csv(text)
        available = bool(blocks) and len(blocks[0].counters) == programmable + 1 and all(
            c.running > 0 and c.running == c.enabled for c in blocks[0].counters.values()
        )
        logging.info(
            "Dedicated cycle counter on core %d: %s", core, "yes" if available else "no"
        )
        return available

    @classmethod
    def get_cmn_version(cls) -> Dict[int, Union[int, str]]:
        raise RuntimeError("CMN is not supported with simpleperf")

    @classmethod
    def get_cmn_frequency(cls, cmn_index: int) -> float:
        raise RuntimeError("CMN is not supported with simpleperf")

    @classmethod
    def get_cmn_mux_interval(cls, cmn_index: int) -> int:
        raise RuntimeError("CMN is not supported with simpleperf")


def _use_root(target: "Target") -> bool:
    """Run simpleperf as root when the target allows it (adb root or su)."""
    try:
        return bool(getattr(target, "is_rooted", False))
    except Exception:  # pylint: disable=broad-exception-caught
        return False


def _executables_dir(target: "Target") -> str:
    directory = getattr(target, "executables_directory", None)
    if isinstance(directory, str) and directory:
        return directory.rstrip("/")
    return "/data/local/tmp/bin"


__all__ = [
    "RemoteSimpleperf",
    "SimpleperfBlock",
    "parse_simpleperf_verbose_csv",
    "scale_block",
    "unique_event_names",
]
