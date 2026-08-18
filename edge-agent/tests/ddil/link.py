"""A controllable link, so DDIL behaviour can be measured instead of argued about (FS-753).

WHY THIS EXISTS BEFORE THE WORK IT SUPPORTS. The remaining DDIL items — edge priority tiers,
adaptive backfill drain, resumable OTA — all have acceptance criteria of the form "survives N
hours denied and drains without loss at X msg/s". None of those can be settled by reading
code. Building the measurement first is what stops the next three items being marked done on
inspection, which is how "the buffer handles outages" became a belief nobody had tested.

WHAT IT IS. An in-process fake uplink the agent's backfill path talks to, whose behaviour is
controlled per-scenario: denied, lossy, slow, or flapping. Time is compressed — a 72-hour
outage is simulated by stamping messages, not by waiting — so a scenario that represents
three days runs in under a second and can live in CI.

WHAT IT IS NOT, stated plainly so nobody reads more into a green run than it earns:

  * **It is not the transport.** There is no TCP here. Half-open connections, SO_KEEPALIVE
    behaviour, DNS failure, TLS renegotiation and kernel buffer exhaustion are invisible to
    it. Those need toxiproxy or `tc netem` in front of a real broker, which is a follow-on —
    the deliberate trade is that this version is deterministic, fast, and dependency-free, so
    it will actually be run.
  * **It does not prove the real producer's behaviour.** It proves the AGENT's: what it
    buffers, what it drains, what it counts, and what it loses.

THE CONSERVATION LAW is the point of the whole file. Every scenario ends by asserting

    produced == sent + still_buffered + dead_lettered + dropped + expired

Any message that is neither delivered, nor held, nor deliberately discarded and counted, has
vanished — and a buffer that loses data silently is the failure mode DDIL exists to prevent.
The buffer's per-instance loss ledger (FS-753) is what makes this checkable at all; before
it, losses went only to global Prometheus counters that could not be reconciled against a
single run.
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class LinkDenied(Exception):
    """The uplink refused the message. What a denied or degraded link looks like."""


@dataclass
class LinkController:
    """The knobs a DDIL scenario turns.

    Deterministic by construction: loss uses a seeded `random.Random`, so a failing scenario
    reproduces exactly rather than "sometimes". A flaky DDIL suite is worse than none — it
    trains people to re-run until green, which is precisely how intermittent-link defects
    survive.
    """

    #: Nothing gets through. Denied.
    denied: bool = False
    #: Fraction of sends that fail, 0.0–1.0. Intermittent.
    loss: float = 0.0
    #: Messages accepted per drain call, or None for unlimited. Limited bandwidth.
    capacity_per_call: Optional[int] = None
    #: Flap: denied for `flap_down` calls, up for `flap_up`, repeating.
    flap_down: int = 0
    flap_up: int = 0

    seed: int = 20260818
    _rng: random.Random = field(init=False)
    _calls: itertools.count = field(init=False)
    _call_index: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._calls = itertools.count()

    def deny(self) -> None:
        self.denied = True

    def restore(self) -> None:
        self.denied = False
        self.flap_down = self.flap_up = 0

    def _flapping_down(self) -> bool:
        if not (self.flap_down and self.flap_up):
            return False
        period = self.flap_down + self.flap_up
        return (self._call_index % period) < self.flap_down

    def accepts(self) -> bool:
        """Whether the link is up for this attempt."""
        if self.denied or self._flapping_down():
            return False
        return self._rng.random() >= self.loss


class FakeUplink:
    """Stands in for the Kafka producer, and counts what genuinely landed.

    `sent` is incremented ONLY for messages the link accepted. That distinction is the whole
    reason this class exists rather than a Mock: the real defect this guards against is
    marking rows sent because `producer.send()` returned, when the broker never took them.
    """

    def __init__(self, link: LinkController):
        self.link = link
        self.delivered: List[Dict[str, Any]] = []
        self.refused = 0

    async def send(self, message: Dict[str, Any]) -> None:
        self.link._call_index += 1
        # The bandwidth ceiling is enforced by `drain`, not here: it is a property of how
        # much the drainer offers per round, not of a single send.
        if not self.link.accepts():
            self.refused += 1
            raise LinkDenied("uplink refused the message")
        self.delivered.append(message)

    @property
    def sent(self) -> int:
        return len(self.delivered)


async def drain(buffer, uplink: FakeUplink, *, batch_size: int = 100, rounds: int = 1) -> int:
    """Move what the link will take, marking only what it took.

    Mirrors `main.py`'s backfill loop with one deliberate difference: it marks each message
    sent individually, after the send succeeded. The production loop sends a whole batch
    fire-and-forget and then marks all of it — which is a real finding recorded against the
    DDIL workstream (a broker that accepts and loses a batch deletes buffered rows that
    never landed). Modelling the SAFE version here keeps the conservation law measuring the
    buffer rather than re-measuring that known bug.
    """
    total = 0
    for _ in range(rounds):
        pending = await buffer.get_pending_messages(batch_size=batch_size)
        if not pending:
            break
        taken = 0
        for message in pending:
            if (
                uplink.link.capacity_per_call is not None
                and taken >= uplink.link.capacity_per_call
            ):
                break
            try:
                await uplink.send({"id": message.id, "payload": message.payload})
            except LinkDenied:
                await buffer.increment_retry([message.id])
                continue
            await buffer.mark_sent([message.id])
            taken += 1
            total += 1
    return total


async def conservation(buffer, uplink: FakeUplink, produced: int) -> Dict[str, int]:
    """The books, and they must balance.

        produced == sent + still_buffered + dead_lettered + dropped + expired

    Returns the ledger so a failing assertion can print where the messages went, which is
    the difference between "something was lost" and a diagnosis.
    """
    stats = await buffer.get_stats()
    ledger = {
        "produced": produced,
        "sent": uplink.sent,
        "still_buffered": stats["total_messages"],
        "dead_lettered": stats["dead_lettered"],
        "dropped": stats["dropped"],
        "expired": stats["expired"],
    }
    ledger["accounted"] = (
        ledger["sent"]
        + ledger["still_buffered"]
        + ledger["dead_lettered"]
        + ledger["dropped"]
        + ledger["expired"]
    )
    ledger["unaccounted"] = produced - ledger["accounted"]
    return ledger
