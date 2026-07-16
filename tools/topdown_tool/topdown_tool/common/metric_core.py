# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Shared metric evaluation helper used by multiple probes."""

import logging
import re
from typing import Dict, Mapping, Optional, Protocol, Sequence, Tuple, TypeVar

from topdown_tool.common import simple_maths
from topdown_tool.perf import PerfEvent

logger = logging.getLogger(__name__)

SYMBOL_PATTERN = re.compile(r"[a-zA-Z_]\w*")

EventT = TypeVar("EventT", bound=PerfEvent)


class EventResultRetriever(Protocol[EventT]):
    """Protocol for retrieving metric event results."""

    def retrieve_event_results(
        self,
        perf_result: Dict[Tuple[EventT, ...], Tuple[Optional[float], ...]],
        group: Sequence[Tuple[EventT, ...]],
        metric_events: Tuple[EventT, ...],
    ) -> Tuple[Optional[float], ...]:
        """Retrieve results for the requested metric events."""


class MetricProtocol(Protocol[EventT]):
    """Protocol describing the minimum metric surface needed for evaluation."""

    name: str
    events: Tuple[EventT, ...]
    formula: str


ComputedMetricsMap = Mapping[MetricProtocol[EventT], Optional[float]]


def compute_metric_value(  # pylint: disable=too-many-arguments, too-many-locals
    *,
    scheduler: EventResultRetriever[EventT],
    perf_result: Mapping[Tuple[EventT, ...], Tuple[Optional[float], ...]],
    group_metric_events: Sequence[Sequence[EventT]],
    metric: MetricProtocol[EventT],
    computed_metrics: Optional[ComputedMetricsMap] = None,
) -> Optional[float]:
    """Compute a single metric using the event-result retriever.

    Args:
        scheduler: Event-result retriever responsible for retrieving perf result values.
        perf_result: Perf results captured for a single timestamp.
        group_metric_events: Metric-event tuples for the group the metric belongs to.
        metric: Metric definition to compute (provides name/formula metadata).
        computed_metrics: Already computed metrics available for substitution.

    Returns:
        Computed metric value, or ``None`` when inputs are missing or invalid.
    """

    assert scheduler is not None, "Event scheduler not initialized"

    normalized_groups = tuple(tuple(events) for events in group_metric_events)
    normalized_metric_events = tuple(metric.events)
    lookup_metric_events = tuple(
        getattr(metric, "required_leaf_events", normalized_metric_events)
    )
    typed_results: Dict[Tuple[EventT, ...], Tuple[Optional[float], ...]] = dict(perf_result)

    try:
        values = scheduler.retrieve_event_results(
            typed_results,
            normalized_groups,
            lookup_metric_events,
        )
    except KeyError:
        return None

    if values is None or any(value is None for value in values):
        logger.warning(
            "Metric %s has incomplete perf data; values=%s",
            metric.name,
            values,
        )
        return None

    formula = metric.formula
    if not formula:
        logger.warning("Metric %s missing formula; cannot evaluate.", metric.name)
        return None

    replacements = {
        event.name: str(value)
        for event, value in zip(normalized_metric_events, values)
        if value is not None
    }

    if computed_metrics:
        for other_metric, other_value in computed_metrics.items():
            if other_value is not None:
                replacements.setdefault(other_metric.name, str(other_value))

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        return replacements.get(token, token)

    substituted = SYMBOL_PATTERN.sub(repl, formula)
    try:
        return simple_maths.evaluate(substituted)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Metric formula evaluation failed for %s: %s",
            getattr(metric, "name", "<unknown>"),
            formula,
            exc_info=True,
        )
        return None
