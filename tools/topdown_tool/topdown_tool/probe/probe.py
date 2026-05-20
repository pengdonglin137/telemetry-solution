# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 Arm Limited

"""
Module defining the abstract classes for telemetry capture.

Classes:
    SharedContext: Invocation-scoped shared context for probe factories.
    Probe: Abstract definition for a telemetry capture object. A Probe is
        responsible for capturing telemetry data, processing it, and outputting
        the results. A typical Probe implementation comprises:

        - A module to read its telemetry specification.
        - A module to expose the content of its specification in a structured
          fashion.
        - An event scheduler.
        - One or multiple renderers to format and output the captured data
          (for instance CSV, JSON, or CLI).
    ProbeFactory: Abstract definition for a probe factory. A ProbeFactory
        builds probes for a specific telemetry domain and applies
        probe-specific configuration objects produced by the companion CLI
        config builder.
    ProbeFactoryCliConfigBuilder: Helper responsible for exposing
        probe-specific CLI arguments and translating parsed namespaces plus
        shared context into configuration objects understood by the associated
        ProbeFactory.
"""

import argparse
from abc import ABC, abstractmethod
import importlib
import logging
import os
from typing import TYPE_CHECKING, Generic, List, Optional, Sequence, Set, Tuple, TypeVar, Union
from importlib.metadata import EntryPoint

if TYPE_CHECKING:
    from topdown_tool.perf.mux_interval import MuxIntervalRequest
    from topdown_tool.perf.perf_factory import PerfFactory


ConfigT = TypeVar("ConfigT")


class SharedContext:
    """Invocation-scoped shared context for probe factory configuration."""

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        perf_factory: "PerfFactory",
        base_csv_dir: Optional[str] = None,
        mux_interval_ms: Optional[int] = None,
    ) -> None:
        self.perf_factory = perf_factory
        self.mux_interval_ms = mux_interval_ms
        self._base_csv_dir = base_csv_dir

    @property
    def base_csv_dir(self) -> Optional[str]:
        """Disallow direct access to the base CSV path after construction."""

        raise AttributeError(
            "SharedContext.base_csv_dir is internal. "
            "Use get_or_create_base_csv_dir() or get_existing_base_csv_dir()."
        )

    def get_or_create_base_csv_dir(self) -> Optional[str]:
        """Return the CSV root directory path, creating it on demand."""

        existing = self.get_existing_base_csv_dir()
        if existing is not None:
            return existing
        if self._base_csv_dir is None:
            return None
        os.makedirs(self._base_csv_dir, mode=0o755, exist_ok=True)
        return self._base_csv_dir

    def get_existing_base_csv_dir(self) -> Optional[str]:
        """Return the CSV root directory path only if it already exists."""

        if self._base_csv_dir is None or not os.path.isdir(self._base_csv_dir):
            return None
        return self._base_csv_dir


class Probe(ABC):
    """Abstract base class for telemetry probes.

    Implementations capture data from a telemetry source, process it, and
    render the result. A typical probe combines:

    - a telemetry specification loader,
    - structured access to the specification content,
    - an event scheduler that orchestrates capture, and
    - one or more renderers (CSV, JSON, CLI, etc.) for the results.

    Subclasses must implement the capture lifecycle methods documented below.
    """

    def __init__(self) -> None:
        pass

    @abstractmethod
    def start_capture(
        self,
        run: int = 1,
        pids: Optional[Union[int, Set[int]]] = None,
    ) -> None:
        """Start telemetry capture for a given run.

        Args:
            run (int): Current run iteration (default 1). Implementations may
                use the run number to differentiate repeated captures.
            pids (Optional[Union[int, Set[int]]]): Process identifier(s) to
                monitor. None indicates system-wide capture.
        """
        raise NotImplementedError("Use derived class")

    @abstractmethod
    def stop_capture(
        self,
        run: int = 1,
        pid: Optional[int] = None,
        interrupted: bool = False,
    ) -> None:
        """Stop telemetry capture for a given run and finalise results.

        Args:
            run (int): Run iteration that is ending (default 1).
            pid (Optional[int]): Process identifier that triggered completion.
                None indicates a system-wide capture.
            interrupted (bool): True when capture terminated because of an
                external interrupt (for example Ctrl-C).
        """
        raise NotImplementedError("Use derived class")

    @abstractmethod
    def need_capture(self) -> bool:
        """Return True when additional capture runs are required.

        Returns:
            bool: True if further capture passes are required.
        """
        raise NotImplementedError("Use derived class")

    @abstractmethod
    def get_mux_interval_requests(self) -> Sequence["MuxIntervalRequest"]:
        """Return concrete sysfs mux interval requests for this probe."""

        raise NotImplementedError("Use derived class")

    @abstractmethod
    def output(self) -> None:
        """Render the captured telemetry data for the user."""
        raise NotImplementedError("Use derived class")


class ProbeFactoryCliConfigBuilder(ABC, Generic[ConfigT]):
    """Build factory-specific configuration from CLI arguments."""

    @abstractmethod
    def add_cli_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Register CLI arguments for the associated factory.

        Args:
            parser (argparse.ArgumentParser): Parser that receives probe
                specific argument groups.
        """

    @abstractmethod
    def build_config_from_cli_arguments(
        self,
        args: argparse.Namespace,
        shared_context: SharedContext,
    ) -> ConfigT:
        """Build a typed probe configuration from CLI arguments.

        Args:
            args (argparse.Namespace): Parsed CLI arguments to normalise.
            shared_context (SharedContext): Invocation-scoped shared context.

        Returns:
            ConfigT: Probe-specific configuration object that will be consumed
            by :meth:`ProbeFactory.configure`.
        """


class ProbeFactory(ABC, Generic[ConfigT]):
    """Abstract base class for telemetry probe factories.

    A ProbeFactory is responsible for:

    - Creating one or more instances of Probe according to a configuration.
    - Applying configuration objects.
    - Indicating whether the probe category is available on the current system.

    Companion objects (ProbeFactoryCliConfigBuilder) are used to expose CLI
    arguments and produce configuration objects in a probe-specific format.

    Note:

    - To make a ProbeFactory visible to the application, it must be registered
      via the entry point topdown_tool.probe_factories.
    - It is recommended to prefix registered CLI arguments to avoid conflicts;
      for example, the CPU probe factory's arguments are prefixed with
      '--cpu'.

    In practice, a derived ProbeFactory typically creates a single
    Probe-derived class.
    """

    def __init__(self) -> None:
        self._cli_config_builder: ProbeFactoryCliConfigBuilder[
            ConfigT
        ] = self._get_config_builder()
        self._shared_context: Optional[SharedContext] = None

    @property
    def shared_context(self) -> SharedContext:
        """Return the configured shared context for this factory."""

        if self._shared_context is None:
            raise RuntimeError(
                f"{self.__class__.__name__} must be configured before calling create()."
            )
        return self._shared_context

    @abstractmethod
    def name(self) -> str:
        """Return the name of the probe.

        Returns:
            str: The name of the probe.
        """
        raise NotImplementedError("Use derived class")

    @abstractmethod
    def is_available(self, shared_context: SharedContext) -> bool:
        """Determine if the probe is available on the system.

        Args:
            shared_context (SharedContext): Invocation-scoped shared context.

        Returns:
            bool: True if the probe can capture telemetry data on the system;
            False otherwise.
        """
        raise NotImplementedError("Use derived class")

    @abstractmethod
    def _get_config_builder(self) -> ProbeFactoryCliConfigBuilder[ConfigT]:
        """Build the CLI config builder used by this factory."""

    def add_cli_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Register CLI arguments for this factory via its config builder."""

        self._cli_config_builder.add_cli_arguments(parser)

    def configure_from_cli_arguments(
        self,
        args: argparse.Namespace,
        shared_context: SharedContext,
        **kwargs: object,
    ) -> bool:
        """Process CLI arguments and configure the factory in one step.

        Args:
            args (argparse.Namespace): Parsed CLI namespace.
            shared_context (SharedContext): Invocation-scoped shared context.
            **kwargs: Optional factory-specific parameters.

        Returns:
            bool: True if telemetry capture should proceed; False otherwise.
        """

        config = self._cli_config_builder.build_config_from_cli_arguments(
            args, shared_context
        )
        return self.configure(config, shared_context, **kwargs)

    @abstractmethod
    def create(
        self,
        capture_data: bool,
    ) -> Tuple["Probe", ...]:
        """Create probe instance(s) based on the CLI arguments and capture flag.

        Args:
            capture_data (bool): Indicates if the probe should capture
                telemetry data.

        Returns:
            Tuple[Probe, ...]: A tuple of Probe instances.
        """
        raise NotImplementedError("Use derived class")

    def configure(
        self,
        config: ConfigT,
        shared_context: SharedContext,
        **kwargs: object,
    ) -> bool:
        """Apply a pre-built configuration to the factory.

        Args:
            config (ConfigT): Object carrying probe-specific configuration
                values.
            shared_context (SharedContext): Invocation-scoped shared context.
            **kwargs: Optional factory-specific parameters.

        Returns:
            bool: True if telemetry capture should proceed; False otherwise.
        """
        self._shared_context = shared_context
        return self._configure(config, **kwargs)

    @abstractmethod
    def _configure(
        self,
        config: ConfigT,
        **kwargs: object,
    ) -> bool:
        """Apply a pre-built configuration to the factory.

        Args:
            config (ConfigT): Object carrying probe-specific configuration
                values.
            **kwargs: Optional factory-specific parameters.

        Returns:
            bool: True if telemetry capture should proceed; False otherwise.
        """

        raise NotImplementedError("Use derived class")

    @abstractmethod
    def get_description(self) -> str:
        """Return a short, human-friendly description of this probe.

        This description is used when listing probes via the global
        '--probe-list' option. Keep it concise and static (no I/O or system
        probing).

        Returns:
            str: Human-friendly description of the probe.
        """
        raise NotImplementedError("Use derived class")


def load_probe_factories() -> Sequence[ProbeFactory[object]]:
    """Load ProbeFactory instances from registered entry points.

    This function retrieves all plugins registered under the
    topdown_tool.probe_factories entry point, attempts to load each plugin,
    and instantiates it if it is a subclass of ProbeFactory. Plugins that
    do not inherit from ProbeFactory or that fail to load are skipped.

    Returns:
        Sequence[ProbeFactory]: A sequence of ProbeFactory instances.
    """
    eps = importlib.metadata.entry_points()

    entries: Sequence[EntryPoint]
    factory_classes: List[ProbeFactory[object]] = []

    # For Python 3.10+, use the `select` method
    if hasattr(eps, "select"):
        entries = eps.select(group="topdown_tool.probe_factories")
    elif hasattr(eps, "get"):
        # For Python 3.9, entries are organized as a dict keyed by group
        entries = eps.get("topdown_tool.probe_factories", tuple())
    else:
        return factory_classes

    for ep in entries:
        try:
            factory_cls = ep.load()
            if issubclass(factory_cls, ProbeFactory):
                factory_classes.append(factory_cls())
            else:
                logging.warning(
                    "Class listed in %s %s do not inherit from ProbeFactory",
                    ep.name,
                    factory_cls,
                )
        except Exception as e:  # pylint: disable=broad-exception-caught
            # handle mis-configured plugins gracefully
            logging.warning("Failed to load plugin %s: %s", ep.name, e)
    return factory_classes


__all__ = [
    "SharedContext",
    "Probe",
    "ProbeFactory",
    "ProbeFactoryCliConfigBuilder",
    "load_probe_factories",
]

PROBE_PUBLIC_EXPORTS: Tuple[str, ...] = tuple(__all__)
