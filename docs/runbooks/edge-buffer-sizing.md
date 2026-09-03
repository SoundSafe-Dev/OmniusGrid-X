# Sizing an edge agent's buffer

**How long will this device survive a link outage, and what governs the answer?**

Every number here was measured on 2026-08-31 against the real buffer, not estimated. The
measurement is reproducible in ten lines and is worth re-running whenever the reading
schema changes, because that is what moves it.

---

## The one number everything follows from

**195 bytes per reading, on disk.** That is a full telemetry row — asset, metric, value,
unit, both timestamps, `time_quality`, `sequence_num` — after JSON framing and SQLite's
page overhead, checkpointed so the WAL is included rather than hiding a third of it.

    empty database        4,096 bytes
    after 5,000 rows    978,944 bytes
    per reading             195.0 bytes

It is not the size of your JSON. SQLite rounds into pages and keeps an index; a payload
that looks like 140 bytes costs 195 once stored.

---

## What actually bounds the buffer

Three limits apply at once, and **the one that governs changes with the reading rate.**
Sizing a device without knowing which is which produces a number that is wrong in a
direction you will not predict.

| Limit | Default | Where |
|---|---|---|
| Age | 24 hours | `StoreForwardBuffer(retention_hours=24)` |
| Size | 1 GB | `StoreForwardBuffer(max_size_mb=1000)`, enforced hourly from `main.py` |
| Drain rate | paced from the backlog | `BACKFILL_MAX_BATCH` / `BACKFILL_DRAIN_SLEEP` (FS-757) |

**The crossover is 62 readings per second.**

    rate     24h volume    binds first        buffer holds
       1/s        16 MB    retention (24h)         24.0 h
      10/s       161 MB    retention (24h)         24.0 h
      50/s       803 MB    retention (24h)         24.0 h
      64/s     1,028 MB    size cap (1 GB)         23.3 h
     100/s     1,607 MB    size cap (1 GB)         14.9 h
     200/s     3,214 MB    size cap (1 GB)          7.5 h

Below 62 readings/s the device holds a full 24 hours and the size cap never fires — raising
`max_size_mb` buys nothing, because age is deleting the data first. Above it, the cap binds
and 24 hours is no longer what you get.

**So the two knobs are not interchangeable, and which one to reach for depends on which
side of 62/s the device sits.** Below it, extend `retention_hours`. Above it, raise
`max_size_mb` — and check the disk can hold it.

---

## Sizing for a required outage window

    MB needed  =  readings/sec  x  outage hours  x  0.67

(That constant is 195 bytes × 3600 ÷ 1024², rounded. Keep the rounding generous: it is a
floor, and a device that runs out mid-outage has no second chance.)

| Target | 10 readings/s | 50 readings/s | 100 readings/s |
|---|---|---|---|
| 24 hours | 161 MB | 803 MB | 1.6 GB |
| 72 hours | 482 MB | 2.4 GB | 4.8 GB |
| 7 days | 1.1 GB | 5.6 GB | 11.2 GB |

Set `retention_hours` to the window and `max_size_mb` to the figure above **plus headroom**,
then confirm the partition holds it. A `max_size_mb` larger than the disk is not a bigger
buffer; it is a buffer whose real limit is `SQLITE_FULL`, and that path prunes 500 rows and
retries once rather than shedding by priority.

---

## What happens when it fills anyway

Two different mechanisms, and the difference matters:

1. **The size cap fires** (hourly, orderly). Sheds by **priority tier**, so tier 5
   diagnostic goes before tier 4 bulk telemetry, and alarms and E-stops are last.
   `enforce_size_limit` counts what it removed.
2. **The disk fills** (immediate, blunt). SQLite raises `SQLITE_FULL`, and the write path
   prunes the **oldest 500 rows** and retries the insert once. Age is all that path can
   express, so it will discard an alarm to make room for a vibration reading.

**Mechanism 1 is the one you want to be operating in.** If a device is regularly hitting
mechanism 2, its `max_size_mb` is larger than its disk and the priority tiers are not
protecting anything.

---

## The limit that is not about space at all

At sustained high rates the binding constraint is neither age nor size — it is whether the
agent can **drain faster than the collectors fill**. FS-757 found the agent could not keep
up with 50 readings/second on a perfectly healthy link: the backlog grew forever and
retention deleted the oldest end of it, silently converting a throughput shortfall into
permanent data loss with nothing reporting a fault.

Pacing now scales from the backlog, so the drain is no longer the ceiling it was. But the
question survives the fix: **a buffer is only a buffer if it empties.** Before sizing for a
72-hour outage, confirm the device drains a 72-hour backlog in materially less than 72
hours, or it will never return to empty and every subsequent outage starts from a fuller
buffer.

`docs/runbooks/` has no procedure for that yet, and the DDIL suite's
`test_the_backlog_drains_faster_than_it_expires.py` is the closest thing to one.

---

## Reproducing the measurement

```python
buf = StoreForwardBuffer(buffer_path=path)
before = os.path.getsize(path)
for i in range(5000):
    await buf.store_message({...a representative reading...})
sqlite3.connect(path).execute("PRAGMA wal_checkpoint(TRUNCATE)")   # or you measure a third of it
per_row = (os.path.getsize(path) - before) / 5000
```

The checkpoint is not optional. Without it the WAL holds a large share of the writes and the
figure comes out low, which is the wrong direction for a number an operator sizes a disk
from.
