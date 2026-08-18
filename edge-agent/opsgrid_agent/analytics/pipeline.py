"""Local analytics pipeline: single entrypoint run from the collector seam.

Runs the OEE, anomaly, and alerting trackers for each collector message so the
coordinator has one call site and future analytics stay additive.
"""

from typing import Any, Dict, List

from . import oee_tracker, anomaly_tracker, alerting_tracker


def record(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run the trackers and RETURN what the alerting tracker fired.

    The return value used to be discarded (FS-755). `alerting_tracker.record` has always
    returned the alerts it raised, and this function dropped them on the floor — so a local
    alarm's entire effect was a Prometheus counter the scraper could not reach during an
    outage, plus an in-memory list that died with the process. The alerts never reached the
    store-and-forward buffer either, so even after the link recovered the backend never
    learned that the edge had decided anything.

    Returning them is what lets the caller do something durable with them. OEE and anomaly
    results stay unreturned because nothing acts on them locally; when something does, they
    should join this signature rather than acquire a second one.
    """
    oee_tracker.record(message)
    anomaly_tracker.record(message)
    return alerting_tracker.record(message)


def reset() -> None:
    oee_tracker.reset()
    anomaly_tracker.reset()
    alerting_tracker.reset()
