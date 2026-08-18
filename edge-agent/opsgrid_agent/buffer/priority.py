"""What must leave the edge first when the link is narrow (FS-754).

THE DEFECT. The store-and-forward buffer drained strictly FIFO by `timestamp_edge` and
pruned strictly oldest-first. So after an outage, an emergency-stop event queued behind
every vibration sample recorded before it — at the measured drain rate that is hours — and
when the buffer filled, the oldest rows died regardless of what they were.

Priority tiers already existed, in `backend/app/services/data_shedding.py`, deciding what to
shed when the BACKEND is overloaded. That is the wrong side of the link: by the time a
reading reaches the backend it has already crossed the scarce resource. The tiers were right
and they were in the wrong place.

WHY THE TABLE IS DUPLICATED HERE RATHER THAN IMPORTED. The agent and the backend are separate
deployables — an edge gateway does not install the backend package, and an agent in the field
may be older than the cloud it talks to. So this is a deliberate copy, and
`test_priority_tiers_match_the_backend.py` asserts the two agree, in the same way
`test_role_vocabulary_parity.py` holds the role vocabulary across its copies. A copy with a
parity guard is honest; a copy without one is the drift this codebase has been bitten by
repeatedly.

TIER MEANINGS, lowest number wins:

    1  safety and state    emergency_stop, alarm, packml_state — never shed, always first
    2  operational         job_status, operator_action
    3  process             temperatures, position, progress — the default
    4  bulk telemetry      vibration, current, voltage, acceleration
    5  diagnostic          debug, verbose — first to die

The default is 3, deliberately. An unrecognised metric is process data until somebody says
otherwise: defaulting to 1 would make everything un-sheddable and the tiers meaningless,
while defaulting to 5 would silently discard a metric whose name simply had not been
classified yet.
"""

from __future__ import annotations

from typing import Dict

#: Metric name -> tier. Kept flat and literal so the parity guard can compare it to the
#: backend's `PriorityConfig` table without either side needing to import the other.
PRIORITY_BY_METRIC: Dict[str, int] = {
    # 1 — safety and machine state. Never shed.
    "emergency_stop": 1,
    "alarm": 1,
    "packml_state": 1,
    # 2 — operational decisions
    "job_status": 2,
    "operator_action": 2,
    # 3 — process values (the default tier)
    "temp_nozzle": 3,
    "temp_bed": 3,
    "progress": 3,
    "position": 3,
    # 4 — bulk telemetry, high volume and individually low value
    "vibration": 4,
    "current": 4,
    "voltage": 4,
    "acceleration": 4,
    # 5 — diagnostic
    "debug": 5,
    "verbose": 5,
}

DEFAULT_PRIORITY = 3
HIGHEST_PRIORITY = 1
LOWEST_PRIORITY = 5

#: Tiers that must never be shed to make room. A buffer that drops an emergency stop to
#: keep vibration samples has inverted its own purpose.
NEVER_SHED_ABOVE = 3


def priority_for(topic: str, payload: dict | None = None) -> int:
    """The tier for a message, from its topic or the metric names in its payload.

    Checks the PAYLOAD as well as the topic because this agent's telemetry arrives as
    `topic="telemetry"` with the metric names as payload keys — classifying on topic alone
    would put every reading in the default tier and the whole mechanism would do nothing.
    The strongest (lowest) tier found wins: a batch containing an alarm is an alarm batch.
    """
    best = PRIORITY_BY_METRIC.get(str(topic).lower(), None)
    if payload:
        for key in payload:
            tier = PRIORITY_BY_METRIC.get(str(key).lower())
            if tier is not None and (best is None or tier < best):
                best = tier
        # `collector_type` and similar envelope fields can also name the class of data.
        for field in ("metric_name", "metric", "event_type"):
            value = payload.get(field)
            if isinstance(value, str):
                tier = PRIORITY_BY_METRIC.get(value.lower())
                if tier is not None and (best is None or tier < best):
                    best = tier
    return best if best is not None else DEFAULT_PRIORITY
