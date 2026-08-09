# Part 4 — the contract-gate slice

Classes 55–72 and rules 63–96: six classes found by repairing a gate nobody could run, then the alias maps, the floors pulled from the air, and the losses that only occur during an outage.

*One part of [Defect-class sweeps](../defect-class-sweeps.md), which carries the index of every class and links to the other parts.*

---

# The contract-gate slice — six classes found by repairing a gate nobody could run

Every class below was found downstream of one repair. The `api-contract` job had been
advisory for weeks under a comment saying it was ready to flip "pending one green CI
run"; that run was unreachable, and each fix was a prerequisite for seeing the next
problem. The order is the finding.

## Rule 63 — every component fast and the whole impossible is a feedback loop, not a slow part

The job needed ~2.5 minutes per operation × 451 ≈ **19 hours**, against a 6-hour limit.
Measured individually: one HTTP request 45 ms, one `call_and_validate` 0.1 s, building a
strategy 0.14 s, drawing an example 0.0 s. Nothing was slow.

Two loops compounded. `from_asgi` drives the app in-process, so every generated example
ran on a new event loop while the app's module-level singletons stayed bound to the
first — and `_process_message_queue` caught the resulting `RuntimeError`, logged it, and
re-entered the loop with no delay, spinning at full CPU forever.

Looking for the slow component is what kept this broken. When the parts are all fast,
stop profiling parts and start looking for something that feeds itself.

## Class 55 — an error path with no delay is a spin

`while self._running:` … `except Exception: logger.error(...)` and straight back round.
Safe while every failure is transient; with a permanent one — a queue bound to a dead
event loop — it is an infinite tight loop that never exits and never recovers.

**Not test-only.** Any `while running` worker does this the first time a fault stops
being transient. Fixed with exponential backoff plus a terminal case for the
unrecoverable error. Guard: `test_ws_queue_processor_cannot_spin.py`, one test per
failure kind — permanent stops, transient sleeps, cancellation propagates.

## Class 56 — a migration that depends on an extension it does not create

`009_audit_logs.sql` triggers on every insert into `audit_logs` and calls
`encode(digest(...), 'hex')`. `digest()` is pgcrypto. No migration created it, so the
trigger raised on every insert, `app/services/audit.py` caught it by design ("never fail
the audited operation"), and **the audit trail recorded nothing at all**. Verified on a
freshly migrated database: `SELECT count(*)` returned 0.

## Rule 64 — a fixture that provisions what migrations do not makes the suite an unreliable witness

Class 56 survived because `tests/conftest.py:91` runs
`CREATE EXTENSION IF NOT EXISTS pgcrypto` when building a test container. The real-DB
suite exercised a working audit trail while a real deployment had none.

**The tests were not wrong about the code. They were wrong about the database.** That is
the general shape: any environment difference the harness papers over is a difference the
suite can no longer see, and it papers over exactly the environments nobody inspects by
hand. Guard: `test_schema_extensions_come_from_migrations.py` fails on any extension
`conftest` creates and no migration does.

## Class 57 — client input that can never be stored, reported as a server fault

Postgres text columns cannot hold `0x00`. A request carrying one raised
`CharacterNotInRepertoireError` and returned **500** — telling the caller to retry
something that can never succeed, and filing a non-incident into error tracking each time.

The mapping is deliberately narrow: **one** exception type whose cause is unambiguous,
because nothing in this codebase generates a NUL byte, so the byte came from the payload.
The tempting version maps every `DataError` to 400 and would relabel our own bad values
as the caller's fault. `test_every_other_database_error_stays_a_500` fails if anyone
widens it.

## Class 58 — an id path parameter typed `str` where the column is a UUID

`DELETE /api/v1/api-keys/0` returned 500: the parameter was `key_id: str`, so "0" reached
a uuid column and asyncpg raised. 28 path params across nine routers had drifted from a
convention 145 others already followed.

**Not every `*_id` is a UUID** — `geotab.device_id` is GeoTab's identifier,
`rag.doc_id` lives in the vector store, `data_residency.record_id` is polymorphic — so
the guard works from an explicit allowlist with a reason per entry, and a companion test
fails on entries whose subject no longer exists. That companion immediately caught an
exemption written from memory for a parameter that does not exist.

## Class 59 — a tenant id taken from the request body

`create_dock_door` did `DockDoor(**data.model_dump())` where `DockDoorCreate` carries
`organization_id`, so the tenant a row landed in came from the client. One offender among
18 schemas that carry the field; every other handler already ignored it.

RLS is forced on the table and would reject the write, so this was defence-in-depth
rather than an open door — but relying on it alone makes correctness depend on the
database **role** rather than the code.

## Rule 65 — a security claim that has not eliminated the harness is not a finding

Class 59 was found beside a false alarm. A dock-door create naming another tenant
returned **200 and wrote the row**, which reads exactly like a cross-tenant write. It was
not one: the contract suite connects as a superuser, and **a superuser bypasses RLS even
where `FORCE ROW LEVEL SECURITY` is set**. The policy was present, forced and correct.

`conftest.py:139` already avoids this by creating a `NOSUPERUSER NOBYPASSRLS` role for
the real-DB suite, precisely because superusers bypass RLS. The contract gate does not
yet, and `docs/engineering/api-contract-gate.md` records that its results are not
evidence about tenant isolation.

The check that resolved it was one query against `pg_roles`. Run it before writing the
bug report, not after.

## Rule 66 — a guard that cries wolf on compliant code gets loosened until it catches nothing

The first version of the class-59 sweep reported `assets.py` as an offender while it was
already correct: it overrides via `payload["organization_id"] = org_id`, a dict-key
assignment the naive pattern missed. Shipping that would have trained the next reader to
widen the exemption list rather than trust the check.

Both directions are mutation-verified — reverting the real fix must fail, and the
compliant file must stay unflagged. The second half is the one that usually goes untested.

## Class 60 — a control whose foreground and background resolve to the same colour

Found by looking at the page, which is the only reason it was found at all.

The Compliance Assistant's "Form" badge rendered as a blank white pill. `STATUS_COLORS.info`
was `bg-opsgrid-primary text-white`; `bg-opsgrid-primary` is `var(--color-primary)`, which is
`#fafafa` in the **default dark theme** and `#171717` in light. White text on a white
background.

Swept across every badge variant: `info` was the only entry pairing a theme-following
background with a fixed foreground. Every other entry already used `text-opsgrid-bg` — the
opposite end of whichever theme is active — and the fixed-colour backgrounds (`bg-status-*`,
`bg-packml-*`) are exempt because they do not move with the theme, so a fixed foreground
beside them is a real decision rather than a coin flip.

**Ten call sites, all illegible in the theme most people use:** the ERP integration type
column, the admin user-role chips, the NLP domain and priority tags in four components, the
fleet vehicle count, and the new Forms panel. None of them wrong at the call site. The variant
was.

Guard: `frontend/src/utils/statusColors.test.ts` asserts the rule rather than the instance — a
`bg-opsgrid-*` background must pair with `text-opsgrid-bg`. Mutation-verified in both
directions.

## Rule 67 — a test suite has no opinion about what the screen looks like

This is the part worth keeping. **467 unit tests, a passing typecheck, and the four
frontend defect-class guards all ran green over a control that displayed nothing.** They were
not weak tests; the page tests asserted the badge's *text content*, which was present and
correct in the DOM the whole time.

No assertion anywhere in this codebase compares a foreground colour to its background, so
contrast is not a dimension the suite can fail in. The bug lived in the one axis every gate
was blind to, and it had been there long enough to reach ten call sites.

It survived a second way: it is perfectly legible in light theme. A defect that only appears
under the *default* setting, and disappears under the one a developer might toggle to while
debugging, is one that a screenshot finds in a second and a green suite never will.

The correction is not "write contrast tests" — it is that **rendering the thing and looking at
it is a distinct verification method, not a weaker substitute for the suite.** Classes 1–59
were all found by reading code or running tests. This one could not have been.

## What the six cost, and what they bought

The gate now runs all 451 operations in ~8 minutes and blocks as a ratchet. Conformance
went 299 → 360 along the way, and the sequence is the argument for repairing a broken
gate rather than routing around it: a job that could not finish, made to finish; which
then could not explain its own failures, made to explain them; and only then did a
documented security feature turn out never to have worked.

## Rule 68 — when a new detector reports a surprising number, the detector is the first suspect

**Eight instrument errors in one sweep**, and every one arrived looking exactly like a
finding:

| Reported | Actually |
|---|---|
| a heading at **1.0:1** contrast, i.e. invisible | `rgba(239,68,68,0.1)` read as solid, which *is* the text colour; composited, it is fine |
| **623** test failures after enabling FK enforcement | `PRAGMA` run against Postgres, where it raises and poisons the transaction. Real number: 39 |
| **39** hardcoded light-theme colours across five pages | 38 were status swatches, translucent chips, and complete `dark:` pairs. Real number: 1 |
| the RUL risk filters **dead** | `Critical (0)` and `High (0)` both empty the table, so the DOM is identical and only the pressed chip differs |
| a click-sweep with **0 problems** | it had not been instrumented; nobody knew whether it had clicked anything (it had: 81 controls) |
| a **2×** suite slowdown from 121 new relationships | machine noise; minimum-of-five put it at 2% |
| **two** undeclared body fields in the ERP client | nested inside `rate_limit`, which is declared |
| **four** endpoints "declaring no JSON body" | URLs written `${BASE}/x`, which the reader could not resolve at all |

Each cost minutes to disprove and would have cost hours to "fix" — and two of them
(the theme guard, the click sweep) would have meant rewriting working code across other
people's lanes.

**The ratio is the lesson, not any single case.** Once a detector has been wrong twice, its
next *empty* result is not evidence either. That is rule 69.

## Rule 69 — fixing a detector's false positives says nothing about its false negatives

Class 25 was swept on 2026-08-02. The detector reported two mismatches, both were shown to
be false positives — a casing seam and a nested object — and the sweep concluded from the
corrected run that **the class was clean and deserved no guard**.

On 2026-08-04 the same class was swept with a new reader. It hit **the same two false
positives, in the same order**, and needed the same two corrections. Then it found
`POST /transportation/shipments/{id}/dispatch`, which had returned **422 on every call since
the day it was written**.

Both readers covered a seventh of the subject: they resolved inline object literals and
stopped, while 61% of the writes in this codebase pass a variable. Both produced an empty
result set. The first mistook that for absence of defects.

The corrections were real work and they were *not* progress toward completeness. A detector
that has stopped lying to you has not thereby started telling you everything, and the moment
it feels trustworthy — just after you have fixed its errors — is the moment its silence is
most persuasive and least earned.

## Rule 70 — a floor pulled from the air is a claim about nothing

Three vacuity floors were guessed for one guard before one was measured: **20, then 45, then
35**, against a real 31.

A floor above reality fails on arrival and gets lowered until it passes, which is the same as
not having one — and worse, it trains the next person to edit the number without reading it,
the exact reflex that let the README claim 2,149 tests while 3,191 ran. A floor below reality
passes forever.

So: measure it, assert the measured number, and **state the fraction of the subject it
represents**. This guard says "31 of 70 bodies resolved, all 31 matched" in its own docstring,
because an empty result over a third of the surface must not read like an empty result over
all of it.

## Rule 71 — a comment describing a check is not a check

Rule 17 says a limitation written into a comment is a finding waiting to be re-found. This is
its sharper cousin: a comment describing behaviour **the code does not have**, written by the
same person in the same sitting.

The branch handling "this operation declares no JSON body" read `continue`, with a comment
saying the case was *"reported separately below"*. Nothing below reported it. A planted
`{ operatorId, clearedBecause }` on such an endpoint passed the guard in silence — and that
branch is precisely where the live defect turned out to be.

The comment was not a lie; it was an intention that never became code, and it read as
completeness to everyone afterwards, including its author twenty minutes later. Mutation-test
every branch, not just the one the defect you are fixing goes down.

## Rule 72 — restarting a service is a claim; verify the port and the process

A fix was verified against a live stack and appeared **not to work**. The fix was correct:
`kill` had not taken, the old server still held the port, and the "restart" bound nothing, so
the verification was running the pre-fix code.

Ten seconds of `lsof -ti:PORT | wc -l` and `ps -o lstart` turned a wrong conclusion into a
right one. Without them the next step would have been to unpick a correct change.

The general form, and it is the same shape as rule 68: **when a verification contradicts a
change you have good reason to believe in, check the verification's premises before the
change's.** A stale process, a cached bundle, a browser holding an old service worker, and a
test run against the wrong database all present as "your fix does not work".

## Class 61 — a half-written alias map

The casing seam renames some fields beyond casing. `YARD_ALIASES` mapped
`scheduledStart → scheduledArrival` and `scheduledEnd → scheduledDeparture`, and stopped
there: `actual_start` and `actual_end` are columns on the same table, are sent, and were
never mapped. `TRANSPORT_ALIASES` aliased `ctpatExpiresAt` and `insuranceExpiresAt` to their
`*Expiry` names and omitted `medical_cert_expires` — the one of the three with a hard DOT
consequence.

**A half-written alias map looks complete at the line above it.** Each entry is evidence that
someone understood the seam, which is exactly why the missing sibling reads as a decision
rather than an omission.

Six aliases added across two maps. Every one is a field that now *arrives* rather than a
declaration deleted — the same sweep found `jockey_driver_id`, `started_at` and `completed_at`
reaching a yard move as three undefineds.

Guard: `backend/tests/test_frontend_types_match_their_own_payload.py` — per type, not against
a global vocabulary, which is what made the missing siblings visible at all.

## Class 62 — a block gated on a field nobody sends

`{trailer.driverName && ( … )}` wrapped a trailer's whole driver section, and `driverName`
was never sent. So the block never rendered — **and it took `driverPhone` with it**, a field
a resolver existed specifically to deliver, under a docstring calling it "the number an
operator calls when a trailer has been sitting on the yard".

That phone fix was real, correct, tested, and invisible for as long as the gate stood. **A
guard on a field nobody sends is a permanent `false`, and everything inside it disappears** —
worse than a blank line, because a blank line can be seen, and worse than a missing field,
because it silently cancels work that was done properly.

The rule is narrower than "do not gate on an unsent field". Two other gates do exactly that,
correctly: `{zone.vehiclesInside && …}` exists to stop the panel rendering a fabricated
`0 vehicles inside`. The defect is the other shape — an absent field standing in front of one
that **does** arrive.

Guard: `backend/tests/test_no_block_is_gated_on_a_field_nobody_sends.py`. Its first version
used the global wire vocabulary and **would not have caught the defect it was written for**:
`driverName` is sent by `fleet_health.py`, so it stayed in the vocabulary no matter what the
yard did. Found by reverting the fix and running the guard, not by reading it.

## Class 63 — a floor that changes the operation

`chunk_blocks` computed `max_chars = max(int(target_tokens * chars_per_token), 1)`. **A floor
of one character is not a fallback; it is a different operation.** With `target_tokens=0`,
"hello world" became eleven chunks — one per character.

`rag_ingestion` passes `settings.RAG_CHUNK_TOKENS`, which is env-overridable, so one mistyped
deployment variable would embed a 40-page manual one letter at a time, report `indexed: True`
with an enormous `num_chunks`, and retrieve nothing usable. Success, an embedding bill, and no
searchable document — and nothing downstream can tell that corpus apart from a genuinely
unhelpful one.

The general form: a clamp written to avoid a crash (`max(x, 1)`, `or 1`, `min(x, len(y))`)
turns a nonsense input into a *plausible* one. Ask what the clamped value **means**, not
whether it is safe to divide by.

Refused at both ends now: the chunker raises below a 32-character budget, and
`validate_settings` reports the misconfiguration at startup — deliberately not gated on
production, because a shredded staging corpus is just as wrong.

## Class 64 — substring matching that routes work to the wrong domain

`correlation_registry_integration` detected domains with `keyword in analysis_lower`, and the
short keywords sit inside words this domain uses constantly:

    "Line CAPAcity was reduced by 12%"       -> QUALITY_CONTROL        (capa)
    "The valve was ISOlated for servicing"   -> COMPLIANCE_REGISTRIES  (iso)
    "Cycle counts are exCELLent this week"   -> PRODUCTION_OEE         (cell)
    "Two customer orders were canCELLed"     -> PRODUCTION_OEE         (cell)

`capa` is Corrective And Preventive Action and `iso` is the standards body. **A registry item
and a Kanban task are created per detected domain, and the analysis text is quoted into the
item** — so a routine capacity note opened a formal quality investigation, and the mismatch
reads as a judgement somebody made rather than a string bug.

Guard: `backend/tests/test_correlation_registry_integration.py` asserts both halves — the
false positives are gone *and* the eight real keyword families still fire, because a matcher
that matches nothing also has no false positives.

## Class 65 — a spec CI does not name is a spec that never runs

Playwright collects `e2e/*.spec.ts` automatically, so a new spec *appears* wired up the moment
it is written. But the live-backend job invoked files **by name**, and a live-backend spec
`test.skip`s itself without `E2E_LIVE_BACKEND=1`.

So a new one would be collected everywhere, skipped on every laptop for want of a backend, and
**executed nowhere** — green locally, absent from CI, indistinguishable from a passing test in
both.

Distinct from FS-365, where a file was not collected at all. Here collection was never the
question; execution was.

Guard: `backend/tests/test_every_e2e_spec_is_run.py`, in the **backend** suite deliberately —
no browser, no Node, so it runs in the cheapest job on every push rather than only where
Playwright is installed.

## Rule 73 — a vacuity guard keyed to a defect population fails on success

Twice in three days, a guard written to stop a sweep passing over nothing broke *because the
sweep worked*:

* `test_the_global_vocabulary_really_does_hide_these` asserted a current offender existed. At
  zero it failed with the message *"delete it rather than keeping a guard that guards
  nothing"* — exactly the wrong conclusion, since the count was zero **because** the file
  worked.
* `test_it_finds_the_unread_ones_at_all` asserted the phantom population was large. Sound at
  34, self-defeating at 5.

**A floor under a defect count is a guard that fails when you fix the defects.** Key the
vacuity check to the *instrument* instead — the vocabulary size, the interface count, the
number of routes walked. Those do not move when the findings do.

## Rule 74 — a default is a claim

Three defects in one week were a fallback turning an absent field into an answered question:

* `alertType: … ?? 'violation'` — every geofence alert read "Violation"
* `vehiclesInside: … ?? []` — every zone reported "0 vehicles inside", a *count*, which reads
  as a measurement
* `{shipment.vehicleId || 'Not assigned'}` — every shipment read "Not assigned" under a
  Vehicle heading, for a column that does not exist

A blank is visibly missing. **A default is a statement, and a wrong one is indistinguishable
from a right one.** Where the absence is meaningful, let it be absent and let the reader see
that nobody answered.

## Rule 75 — a number in a comment is a claim

Writing up class 63's registry finding, the first version said **41** unfillable registries,
from `46 − 5 default-item domains`. The five are a *subset* of the eight extractable ones, so
the union is 8 and the answer is **38**.

The test caught it — `reachable >= 9` failed at 8 — and both the test and the service
docstring were corrected before either was committed. After a week spent finding stale notes
in this codebase: the only reason a wrong number did not ship is that it had been **asserted**
rather than only written down.

Corollary, and the whole reason this rule is worth its space: three of the notes that turned
out to be wrong this week were *accurate when written* — `ActiveAlarmsResponse`'s "every field
the client's `Alarm` type reads is in `AlarmResponse` already", `validate_data_residency`'s
"`data_residency_tags` has no `organization_id` at all", and a `DockDoor` deferral listing
five fields that had already been fixed in the same interface. **A note records what someone
believed; only a test records what is true now.**

## Class 66 — a skip guard in front of a locator that cannot match

Two e2e assertions aimed at freshly-fixed defects were **skipping, not passing**. Both had
the shape:

    const rows = page.locator('table tbody tr')
    test.skip(await rows.count() === 0, 'nothing to assert about')

The pages render div lists, so the locator matched nothing, and the guard converted that into
a silent skip. **A red test gets fixed; this sat green and inert for as long as it existed,
and nothing was ever going to say so.**

The guard is not the mistake — a test that needs data it may not have should skip rather than
fail spuriously. The mistake is skipping on a condition that is *also* what a broken selector
produces. Where the two are indistinguishable, assert the precondition instead: this now
asserts the seeded trailer `TRL-4482` is present, so a seed change fails loudly rather than
making the test about nothing.

Chasing the first one found a real defect underneath: `Alarms.tsx` rendered
`{alarmCode} • {occurredAt}` and **named no machine at all**, on the dedicated alarms screen,
while `/api/v1/alarms/` had been sending `asset_name` for two days.

## Class 67 — a sweep that reports no problems because it did no work

`controls-do-not-break.spec.ts` clicks controls and watches for uncaught errors and 5xx
responses. Its first version had no wait after `goto`, counted buttons before the page
rendered, clicked **zero**, and **passed in 4.7 seconds**.

An earlier attempt failed the opposite way — 32 routes × 12 controls with waits **timed out at
ten minutes** before printing its findings. **Too slow to run is the same outcome as too blind
to see.**

`expect(clicked).toBeGreaterThan(15)` is now the first assertion in the file. Every sweep in
this document has a vacuity check for this reason; this one was written by someone who had
just added three rules about it.

## Rule 76 — read the DOM before rewriting the locator

A field would not fill. Three rewrites followed — container by heading text, container by
contained button, preceding-sibling XPath — and **all three resolved to a real element and
none could see the input**. `filter({ hasText })` matches every ancestor and `.last()`
returns the deepest, which is the title; `filter({ has: button })` also matches every
ancestor and `.last()` returns a div *inside* the button component.

The original locator had been correct all along. Dumping 700 characters of `innerHTML` took
thirty seconds and would have saved all three attempts.

The general form: **when a selector fails, the cheapest next step is to look at what it is
selecting against**, not to write a cleverer selector. This applies equally to a SQL predicate
returning nothing and a regex matching nothing.

## Rule 77 — asking a question before the answer exists returns "no"

A write test read `isVisible()` immediately after `goto` to decide whether the operator was
already clocked in. The card's query was still in flight, so neither button existed, so the
answer was "not clocked in" — and the clocked-in card then rendered with no Clock in button
to press.

**"Not present yet" and "not true" are the same boolean and different facts.** Where a check
drives a branch, wait for the thing that settles it first: here, for *either* button to be
visible before asking which one it is.

## Rule 78 — a per-file remedy for a shared resource is a per-file remedy

The e2e suite hit `AUTH_LOGIN_RATE_LIMIT = 10/minute` twice, three days apart, in two
different files. Both were fixed the same way — authenticate once, replay the state — inside
the file that hit it. **The second file could not benefit from the first file's fix, and a
third would have hit it again.**

The fix that generalises is a Playwright setup project: one login for the entire suite,
written to disk, inherited by every spec, however many files it grows to.

The tell is in the diagnosis, not the fix. A rate limiter, a connection pool, a disk quota
and a port are all *shared*; a remedy that lives inside one consumer of a shared resource is
a remedy that has to be rediscovered by the next one.

## Rule 79 — a script that writes at the end discards everything if it fails in the middle

A documentation edit vanished. One script made several replacements into a string and then
hit an `assert` that failed, so `write_text` never ran — and the earlier, **correct**
replacements were discarded with it. The shell reported nothing, because the failure was the
last thing to happen and nobody asked.

The result was a README claiming 78 rules beside a document indexing 75, which a guard caught.
Without that guard it would have joined the heading that read "the forty-seven classes" for
weeks.

Same shape as rule 72 (a `kill` that did not take, so the "restart" bound nothing) and as a
`docker compose build` that appeared to succeed because it was piped to `tail` and the shell
reported `tail`'s exit code. **A step that is not asked whether it succeeded will not
volunteer that it failed.**

Two habits, both cheap: make one edit per script so a failure cannot roll back a success, and
where a document must agree with code, assert the agreement rather than maintaining it.

## Rule 80 — a register nobody can trust is worse than no register

`open-decisions.md` collects the findings that are understood and deliberately not fixed. Its
value is entirely in being believed: a reader consults it to decide something, and if one
figure is wrong they discount the whole page — **including the entries that were right**.

Every number in it was correct when audited, and every one was unasserted. "Correct today
with nothing keeping it correct" is the state every ratchet in this document exists to
prevent, applied to prose instead of code.

`test_open_decisions_numbers_are_true.py` asserts the numbers and nothing else — not the
prose, not the reasoning, not whether an entry still deserves to be open. It also requires
every entry to name the test that pins it, because **an entry with no pin is a note, and
notes are what that document replaced.**

---

## Class 68 — a provenance stamp decided somewhere other than where the data was made

**Where:** `edge-agent/opsgrid_agent/collectors/audio.py`, `video.py` (FS-457)

Two edge collectors fabricate readings when hardware is absent, and stamp `simulated: True`
so the platform can tell an invented number from a measured one. The stamp is the entire
safety property — an agent reporting invented vibration as fact is worse than one reporting
nothing, because nothing is visibly nothing.

The capture synthesized on one condition:

```python
if self.source == "device":
    ...record from the microphone...
return synthesize_frame(...)          # everything else
```

and the stamp fired on another, a method away:

```python
if self.source == "simulate":
    features["simulated"] = True
```

**Those are not complements.** `source: "mic"`, `"alsa"`, `"rtsp"`, `"camera"` — any typo, any
plausible-looking alternative — took the synthesis branch and missed the stamp. Fabricated
audio RMS, peak frequency, brightness and motion score, arriving in the platform indexed
against a real asset and indistinguishable from a real sensor's.

Both collectors had it, in the same shape. The existing `EDGE_REQUIRE_EXPLICIT_SOURCES` guard
did not help: it catches an OMITTED source, and these sources were present and wrong.

**Fixed** by returning the fact rather than re-deriving it — `_capture()` and `_grab_frame()`
now answer `(data, synthetic)` — and by rejecting a source the collector does not know, so a
typo stops the agent instead of quietly changing what it measures. Pinned by
`edge-agent/tests/test_synthetic_data_is_always_stamped.py`, which asserts the SHAPE (no
provenance stamp assigned inside a branch on `self.source`) rather than the two instances.

## Class 69 — the loss that only occurs during an outage, reported only to the outage

**Where:** `edge-agent/opsgrid_agent/buffer/store_forward.py` (FS-458)

The store-and-forward buffer loses undelivered telemetry three ways. Two of them increment a
Prometheus counter and log a warning. The third — deletion for passing the retention window —
returned its count faithfully and the caller only logged it, at INFO.

That third one is the one that matters. Dead-lettering and size-pruning happen on a healthy
device under load. Expiry happens when the device has been **unable to reach the cloud for
longer than the retention window**: the buffer's whole reason for existing, failing. Its only
trace was a log line on a box that by construction cannot ship logs.

The operator's view of a week-long outage was a pending-messages gauge that stops rising.
Nothing distinguished "holding steady" from "deleting the oldest hour, every hour."

**Fixed** with `edge_buffer_expired_total`, wired at the call site, and the log raised to
warning to match its two siblings. Pinned by
`edge-agent/tests/test_every_buffer_loss_is_counted.py`, which walks the file for methods
that `DELETE FROM messages` and requires each to have a counter reading its return value.

**And an alert, because the counter is only half of it.** Both sibling counters already had
a Prometheus rule; a third that was scraped and unwatched would be exactly as unnoticed as
the log line it replaced, while looking on the dashboard like it had been handled. The new
`EdgeBufferExpiring` rule is HIGH rather than the size cap's MEDIUM, because of what causes
it: the size cap trips on a busy device, expiry trips on a device that has been cut off long
enough to start losing what it buffered. The guard asserts the pairing, so a fourth loss
counter cannot ship without a rule.

## Rule 81 — a provenance stamp derived from config is a second guess

Class 68. The function that fabricated the data knows it fabricated the data. Ask it.

## Rule 82 — a fallback is a decision; make an unrecognised value an error

Class 68. `else: simulate` converts a typo into a silent change of what the system measures.

## Rule 83 — the loss that only happens during an outage cannot be reported only in logs

Class 69. Losses need counters. The loss whose cause is an outage needs one most.

## Rule 84 — a guard whose window can reach a neighbour's evidence proves nothing

The first version of the Class 69 guard searched 400 characters after each buffer call for
`metrics.record_`. It passed with the fix deleted, because the window reached down into the
NEXT loss path's counter. A guard that is green whether or not the defect is present is worse
than no guard, because it is also a claim that someone checked.

Caught by mutating the fix out and watching the test stay green — the step that is easy to
skip when a test passes on the first run, and the only thing that distinguishes a guard from
a decoration. The rewrite binds the assigned variable and follows it to the counter, which
also catches the subtler mutation: a counter present but reading the wrong variable.

## Rule 85 — `| tail` on a test run discards the diagnosis of whatever it reports

The second time this cost something in one week. Earlier it was `docker compose build | tail`,
where the shell reported **tail's** exit code and a build that failed on `No space left on
device` read as a success.

Here it was `pytest ... | tail -6`. The run reported one failure —
`test_backup_restore_drill.py::test_dump_restores_into_an_empty_database` — and the traceback
that would have explained it had already been thrown away. The test passed in isolation and
passed on a full re-run, so it is an intermittent, and the one observation that could have
diagnosed it is gone.

**Recorded as unexplained rather than quietly dropped.** A failure seen once and not
reproduced is still a fact about the suite; calling it "flaky" and moving on is how a real
order-dependency becomes folklore. What is known: it dumps and restores the shared
`omniusgrid_test` database and compares row counts, so anything writing to that database
between its snapshot and its `pg_dump` would produce exactly this.

Redirect to a file and read the file. The cost is one path; the alternative is running the
whole suite again to see what you already saw.

---

## The capped-list ratchet reached zero (FS-459)

Class 12 — a cap that cannot say it capped — is closed on the API surface. Eleven endpoints
returned a bare array truncated at `limit`, which makes a full page indistinguishable from
the complete set; all eleven now select `limit + 1` and set `X-Result-Truncated`.

**One extra row, not a COUNT.** The whole fix per endpoint is a `+ 1` on the limit and one
`mark_truncated(response, rows, limit)` call. A `COUNT(*)` over the table would answer the
same question and cost a scan on every list request, which is why the ratchet sat at eleven
for as long as it did: the fix was assumed to be expensive.

The last five were in `analysis_sessions.py` and `kanban.py`, files another lane owns. The
open-decisions register had recorded that entry as **the one needing nobody's intent** — the
change contains no decision about semantics — and crossing a lane for a mechanical fix while
leaving the entries that need someone's judgement untouched is what keeps the lane rule
meaningful rather than a rule to route around.

**Stopping at the server would have been half of it,** and this repository has now recorded
that failure three times (FS-434, FS-456, and the `truncated` flag the intake panel had been
receiving and not rendering). So the three chat endpoints with real callers return
`ListResult` and both components render a notice. Ranked by how badly silence hurts:

| endpoint | what silence costs |
|---|---|
| `chat/search` | matches EXIST that were not shown — the user concludes the thing is not there |
| `{session}/messages` | ordered OLDEST FIRST, so truncation drops the most RECENT turns |
| `chat/history` | a page reads as the whole record of what was said |

The two `kanban.py` endpoints have no frontend caller — the board uses `/kanban/board` — so
the signal is there for whoever writes one, and the client half was not invented for it.

**What replaced the ratchet.** `TestTheDebtIsAttributed` used to split the unsignalled
endpoints into mine and another lane's, asserting the cross-lane list was non-empty, with a
note saying that if they were ever fixed the right move was to lower the ratchet and rewrite
the class rather than leave a stale claim about other people's work. That is what happened.
It is now `TestTheDebtIsGone`, asserting the property the inventory was tracking.

---

## Class 70 — fields transmitted across a boundary that the other side never reads

**Where:** `edge-agent/opsgrid_agent/versioning.py` → `backend/app/workers/ingestion.py`
(FS-460)

The edge agent builds one heartbeat payload of eleven fields. The cloud persists four, uses
three for routing and stamping, and **never touches `git_sha`, `collector_status` or
`buffer_depth`** — computed on every device, serialised, transmitted, discarded.

Both sides had tests. `edge-agent/tests/test_heartbeat.py` asserts the payload is built
correctly; `test_agent_heartbeat_updates_assets_realdb.py` asserts the update lands. Neither
could see the gap, because a contract with only one side asserted is not asserted.

**The first version of this entry drew the wrong conclusion, and the correction is the more
useful half.** It said `buffer_depth` was the one that mattered because device backlog was
invisible to the cloud. It is not invisible. A SECOND heartbeat path exists —
`POST /api/v1/edge/heartbeat` — and the agent posts `buffer_pending`, `dead_lettered`,
`dropped` and `active_collectors` to it; the backend persists them on `edge_agent_status`
and publishes per-agent `edge_agent_*` gauges.

The claim came from reading the Kafka path and generalising from it. **A sweep that finds one
consumer and concludes there is no other is asserting a negative it did not check.** It was
caught coming the other way, while checking whether a backend gauge had a producer — which is
the only reason it was caught at all.

What is actually true is narrower and still worth the guard: the same health is assembled
twice, under two names for one quantity (`buffer_depth` / `buffer_pending`), and the Kafka
copy is read by nobody. Redundant work on every device, and two vocabularies for one fact —
the condition that produced six aliases in FS-435.

**Not fixed, recorded** (open-decisions #5). Persisting them is a migration, a worker change
and a panel; the alternative is to stop computing them. Both are defensible and the choice
is not a bug fix. What is now impossible is the gap widening quietly: the guard walks the
agent's payload dict and the worker's `data.get` calls and requires every field to be
consumed or explicitly exempted with a reason.

The guard asserts BOTH directions. The reverse — the worker reading a field no agent sends —
is the one that fails silently in production: `data.get` returns `None` rather than raising,
so the column stays NULL forever while the code reads as though it were populated.

## Rule 86 — a contract with one side asserted is not asserted

Class 70. Two green suites, one on each side of a boundary, prove that each side does what
its author intended. They say nothing about whether those intentions match. Assert the join.

---

## Class 71 — a guard that matches one spelling of the defect it was written for

**Where:** `edge-agent/tests/test_no_naive_utcnow.py` (FS-461)

The agent has had a naive-datetime guard since FS-96, written after two instances became
**silent data loss** — backfill lag reported as 0, collector readings dropped before
forward. Its docstring says so. It matched:

```python
_NAIVE_CALL = re.compile(r"datetime\.utcnow\s*\(")
```

and passed, every run, while **fourteen bare `datetime.now()` calls** sat in the same tree.
`datetime.now()` with no argument returns naive LOCAL time. It is the more dangerous
spelling precisely because it looks right.

Five were `timestamp_edge` on collectors that emit to the cloud — `bacnet`, `profinet`,
`dnp3`, `ethernet_ip`, `http_rest`. `telemetry.time` is `timestamptz`, and the ingestion
worker parses the string with `fromisoformat`, which yields a naive datetime that Postgres
then reads as UTC. **Every reading from a device outside UTC was stored wrong by exactly
that device's offset.** Verified: on a host at −05:00, a stamp emitted at 19:36 local
arrives as 19:36 UTC.

The rest were internal, and one was worse than internal: `local_oee.py` measured elapsed
time against local wall-clock, which is not monotonic. On a DST fall-back it steps backwards
an hour, so the "currently in Execute" term goes negative and silently subtracts from
operating time — feeding availability and performance. Once a year, on a number nobody would
think to question.

`_parse_ts` in `oee_tracker.py` deliberately produced local-naive time to match, and
documented why: "collectors mostly emit local-naive timestamps". That premise had gone
stale — seven emit aware UTC and four emit naive. **A comment explaining a deviation ages
into a justification for it.**

**Fixed** by converting the agent to aware UTC throughout (`astimezone(timezone.utc)` is
correct for both inputs: naive is read as local, aware is converted), and by widening the
pattern. The widened guard now asserts ITSELF — that it matches both spellings and does not
match `datetime.now(timezone.utc)` — because a pattern that quietly narrows restores months
of confident silence.

It also strips comments and string literals via `tokenize` before matching. The first
attempt stripped only `#`-prefixed lines and fired on the docstring **describing this very
defect** — the third time in this document that a comment explaining a defect tripped the
detector for it. A guard that fires on its own explanation gets fixed by deleting the
explanation.

## Rule 87 — a guard that greps for one spelling reports clean on every other spelling

Class 71. Assert the pattern itself: that it matches each form of the defect, and does not
match the correct form.

## Rule 88 — a defect class does not stop at a repository boundary just because the sweep did

Class 29's sixth mechanism and class 71 were both found in the edge agent, and both had
already been found and fixed elsewhere in this repository. After closing a class, ask which
other component computes the same thing.

---

## Class 72 — an unrecognised input defaulted into a value that already means something

**Where:** `edge-agent/opsgrid_agent/packml.py`, `backend/app/api/operations.py` (FS-462)

`PackMLStateMapper.map_state` turns whatever string a PLC reports into a standard PackML
state. For anything it did not recognise it returned `PackMLState.IDLE` — **and `IDLE` is in
`AVAILABILITY_LOSS_STATES`**. So an unreadable state was recorded as downtime, and a machine
running at full rate appeared stopped.

The default was not neutral. It could not be: every member of that enum belongs to a
category, so *any* choice of default asserts something. `Idle` asserts the worst available
thing.

**How likely is a miss.** The default maps are per asset type and do not overlap.
`create_mapper_for_asset_type("3d_printer")` knows "printing" and not "running"; the CNC map
knows "running" and not "printing". One wrong `asset_type` in a config, one firmware update
that renames a state, one vendor that says "in_progress" — verified: a printer mapper given
"running" returned `Idle`, `is_availability_loss` was `True`.

**Three things in the file already said this was wrong**, which is what makes it a class
rather than a slip:

* `get_state_category` has an `"unknown"` branch that was **dead code** — unreachable,
  because every enum member was categorised;
* `get_unknown_states()` is a public accessor **nothing outside the module calls**, so the
  record of what could not be mapped never left the object;
* the warning fires once per *distinct* string, on a device that may be unable to ship logs,
  so the single line recording a permanently mis-measured machine is also the one most
  likely to be lost.

Someone foresaw this and the handling was lost. Unreachable handling for a real condition is
a defect report left in the source.

**Fixed** with `PackMLState.UNDEFINED` in neither category set (which revives the "unknown"
branch), a counter `edge_packml_unmapped_total` labelled by asset TYPE — the vendor string is
arbitrary text off a PLC and would hand unbounded cardinality to Prometheus — and by
excluding unmapped time from availability's denominator rather than scoring it as downtime.

**And fixing the agent alone would have made things worse.** `/operations/{id}/packml-summary`
computes `Execute / total_duration`, and `total_duration` sums every bucket — so the moment
the agent started emitting an honest `Undefined`, that endpoint turned the honesty into a
lower productivity number. A machine would report as less productive the more of its states
its configuration failed to cover: a property of the config presented as a property of the
machine. The denominator there excludes unmapped time now, and `unmeasured_seconds` is
reported so a reader can see how much the answer rests on.

That is class 19 again from a third side, and the reason the cross-boundary rule earns its
place: **fixing one side of a boundary is not finishing when the other side consumes the same
quantity.**

## Rule 89 — a fallback into a valid-looking value inherits that value's meaning

Class 72. Choose a value that belongs to no category, or the default answers a question
nobody asked it.

## Rule 90 — dead code that anticipates a case is evidence the case was foreseen and then lost

Class 72. An unreachable branch for a real condition, or an accessor with no caller, is a
defect report someone left in the source. Read it as one.

---

## The carry-across pass — closed backend classes, re-asked of the edge agent (FS-463)

Four consecutive findings in the edge agent (FS-457, FS-458, FS-461, FS-462) were classes
this repository had **already found and fixed in the backend**. Each was discovered by
accident, in the middle of doing something else. That is not a method, so this is the
systematic version: take the closed classes, ask which of them the agent could also have,
and check each mechanically.

**It found one new defect, confirmed five clean, and finished in an afternoon.** The clean
results are recorded because they are the expensive part to re-derive, and because a sweep
whose negatives are unwritten gets run again by the next person.

| closed backend class | what it becomes for an agent | result |
|---|---|---|
| `test_sql_is_not_built_by_interpolation` | the SQLite store-and-forward buffer | **clean** — parameterised throughout; the `f"…{placeholders}"` are `','.join('?' * n)` |
| `test_capped_lists_cannot_grow` | data the buffer discards | fixed earlier, FS-458 |
| `test_capped_lists_are_ordered` | `[:N]` slices anywhere | **clean** — every hit is byte slicing or a log preview, not a result set |
| `test_datetimes_are_timezone_aware` | naive time in the agent | fixed earlier, FS-461 (14 sites) |
| `test_oee_failure_is_not_zero` | absence rendered as a number | fixed earlier, FS-461 / FS-462 |
| `test_maintenance_costs_are_computed_not_invented` | a figure derived from a constant | **NEW — FS-463**, below |
| `test_provenance_flags_are_always_set` | fabricated readings | fixed earlier, FS-457; sweep confirms only two stamp sites remain and both are correct |
| `test_heartbeat_contract_is_fully_read` | agent → cloud field contract | recorded, FS-460 |
| `test_ws_queue_processor_cannot_spin` | retry loops burning CPU | **clean** — 24 unbounded exception-swallowing loops examined, every one sleeps |
| `test_service_lifecycle_is_declared` | start/stop symmetry | **clean** — 17 collector classes, none creates a task it fails to cancel |
| `test_correlation_alerts_are_dispatched` | a name claiming a side effect | **clean** — every `_send`/`_publish`/`_forward` performs it, and raises rather than logging when it cannot |
| `test_frontend_types_match_their_own_payload` | metrics declared and never touched | **clean** — 25 declared, all incremented |

Two of the "clean" results were **first reported as hits by a detector that was wrong**,
which is the usual tax:

* the hot-spin sweep flagged `mqtt.py` because it sleeps via a `_sleep_or_stop()` wrapper
  rather than calling `asyncio.sleep` directly — and `mqtt.py` is in fact the best-protected
  collector in the tree, with both a circuit breaker and exponential backoff;
* the first version flagged 21 loops by counting any loop with an `except`, including `for`
  loops over finite collections, which terminate by construction.

### FS-463 — a performance figure computed from a constant

`Performance = (parts × ideal cycle time) / operating time`. The ideal cycle time is seconds
per part when the machine runs flat out — a property of **the machine**. The agent had:

```python
self.ideal_cycle_time: float = 60.0  # seconds (default)
```

set in `__init__`, never read from configuration, never assignable, referenced nowhere else
in the tree. Every machine in the world was assumed to take sixty seconds per part.
Measured before the fix, both running flat out for an hour:

| machine | reported performance | truth |
|---|---|---|
| press, 3s cycle | **100%** (computed 2000%, clamped) | 100% |
| CNC, 600s cycle | **10%** (no clamp at the bottom) | 100% |

The clamp is why it survived: fast machines came out at exactly 100% and looked perfect, so
only slow machines showed the error — and they showed it as a machine running perfectly
reporting one tenth of its rate.

The backend has read this per asset from `asset.connection_config['ideal_cycle_time_seconds']`
all along. The agent had no way to be told at all.

**Fixed** with no default: `oee_tracker.configure(asset_id, seconds)` is called from the
collector-registration loop in `main.py`, beside the alert-rule registration already there,
reading the same key the backend reads. Unconfigured, performance is `None` with a reason —
consistent with FS-461. A zero, negative or non-numeric rate is refused rather than clamped,
because clamping would resurrect an invented number by another route.

This turns performance **off** for any deployment that never configured a cycle time. That is
the point: those deployments were not getting performance, they were getting a number
computed from sixty.

## Rule 91 — carry a closed class across every component that computes the same quantity

Finding the same class four times by accident is luck. Walking the closed classes and asking
which other component computes the same thing is a method, and it terminates.

### The reverse pass — the agent's classes re-asked of the backend (FS-464)

The carry-across pass ran one way: closed backend classes, re-asked of the agent. Running it
back the other way — the classes the AGENT taught us, asked of the backend and frontend — took
an afternoon and found one defect, one wrong claim of my own, and four clean results.

| class the agent taught | asked of the backend | result |
|---|---|---|
| 71 — a guard matching one spelling | the backend's naive-datetime guard | **clean** — already AST-based, checks both spellings, and self-tests its own pattern. The agent was the laggard |
| 68 — provenance decided away from the data | `geotab_service` gated/stamped functions | **clean** — every gated function stamps, and `get_device_location` sets `invented = True` in the same block that fabricates the point, which is the correct shape |
| 72 — unrecognised input defaulted into meaning | `except (Value|Key|Type)Error -> return <constant>` | **clean** — 7 sites, 6 return a caller-supplied `default`, the seventh is a sort key |
| 29 — absence rendered as a number | backend OEE `quality = ... else 1.0` | **clean** — `quality_measured` / `performance_measured` flow calculator → API → the OEE page's hint. Wired end to end, and better than the agent's was |
| 69 — a loss reported only to a log | the ingestion worker's DLQ | **NEW — FS-464** |
| 70 — a contract asserted on one side | my own FS-460 entry | **my error** — see Rule 92 |

**FS-464.** A message the ingestion worker cannot process is published to a dead-letter topic
and logged, and that was all: no counter, no alert, nothing on a dashboard. The agent's
equivalent has had a counter and a rule since FS-458 — **the platform was monitoring the
edge's data loss and not its own.**

The cloud case is the sharper one. A dead-lettered message was ACCEPTED: the device sent it,
the broker acknowledged it, and the agent's buffer dropped its copy on that acknowledgement.
The data then exists in exactly one place, a DLQ topic nobody watches, while the device has
been told everything is fine.

And one branch lost it completely. `_dead_letter` opened with `if self._producer is None:
return` — no DLQ record, no counter, no log. Defensive, since the producer starts before the
consumer, but it was the only branch in the worker where an accepted message vanished leaving
no trace of any kind, and "unreachable" there is a property of today's start-up order rather
than of the code.

Two counters, not one, because they need different responses: dead-lettering is replayable
and alerts HIGH; a failed DLQ publish is data leaving the system and alerts CRITICAL. The
guard asserts that ranking, because collapsing it wastes the only distinction that matters at
three in the morning.

## Rule 92 — finding one consumer does not prove there is no other

Class 70, learned by getting it wrong. "Nothing reads this" is a claim about everything, and
the search that supports it has to be about everything too. The FS-460 entry asserted that a
device's buffer depth reached the cloud and was thrown away; a second heartbeat path was
consuming it the whole time, and the mistake surfaced only because a later sweep came at the
same code from the opposite end — asking whether a backend gauge had a producer instead of
whether an agent field had a consumer.

**Two directions, one boundary.** When checking whether a producer's output is consumed, walk
it from the consumer's side as well. The two searches fail in different ways, which is what
makes running both worth the time.

## The third leg — backend and agent classes asked of the frontend (FS-465)

The pass has now run all three ways: backend → agent, agent → backend, and both → frontend.
The last leg found one defect, and it was found from the CLIENT and fixed in the SERVER,
which is the direction that had not been tried.

| class | asked of the frontend | result |
|---|---|---|
| 29 — absence coerced into a number | `(x ?? 0) *` and `(x \|\| 0) *` in rendered figures | **4 hits, 1 real** |
| 29 — the OEE page specifically | `pct = (v) => (v ?? 0) * 100` | **clean** — guarded by `{f.measured ? pct(f.value) : '—'}`; the `?? 0` only ever sees measured values |

The three false positives are worth naming: a form's default radius, and two helpers whose
callers already branch on a measured flag. **A coercion is only a defect where the coerced
value is rendered as a measurement**, and a detector that cannot tell the difference produces
a list nobody reads.

### The real one

`(r.dwellHours ?? 0) * 60` in the yard client. Following it back to the server found that the
same quantity is computed in **two places that disagree about a null check-in**:

    _calculate_dwell_hours    end_time - _as_utc(None)   -> TypeError, a 500
    the dwell-times query     ... if check_in else 0.0   -> 0.0, "arrived just now"

One crashed and one lied. The lie is worse: the yard banner exists to report trailers past a
120-minute target, and a trailer nobody could age was scored as the most favourable value
available — then averaged in at zero by the client, pulling the mean down, while being absent
from the count the banner reports. `check_in_at` is nullable, and its `default=utcnow` is
skipped by a raw insert, a case `test_raw_insert_timestamps.py` already parametrises over
`yard_trailers` for.

**The comment on the next line already knew.** Immediately below the `else 0.0`, the source
explains that `detention_charge` must stay null until assessed because "`float(None or 0)`
turns 'not yet worked out' into 'nothing owed'". The reasoning was right there and one line
too low.

Fixed to `None` in both producers, `Optional[float]` on the wire, and the client now averages
over measured rows and reports `trailersUnmeasured` — the same shape as `assets_measured` on
the OEE surfaces. `formatDuration` also stopped collapsing `0` and `null`, which it had been
doing with `if (!minutes) return 'N/A'`.

## Rule 93 — proximity to a correct decision is not protection

Class 29. The reasoning that would have caught this was one line below it, about a sibling
field, written by someone who had the class clearly in mind.

## Rule 94 — two producers of one number will disagree about the edge case

Class 29. When the same quantity is computed in two places, the edge case is where they part
company — and fixing the one you found leaves the other. Look for the second producer before
believing the fix is complete.

## The register reached zero (FS-466 … FS-470)

`docs/engineering/open-decisions.md` held five entries described as needing intent rather than
investigation. All five are closed. Three took less time to decide than they had spent being
re-read, which is worth knowing about that page: an entry can sit there because it is
genuinely contested, or because nobody has been asked.

**Two closed by deleting.** The 38 registries nothing could fill are no longer created; the
heartbeat fields nobody read are no longer sent. Both had been written up as work to add —
extractor keywords for 38 domains, a migration and a panel for three fields — and in both
cases the honest answer was that the thing should not exist. `INNOVATION_RD` does not become
a real programme because a registry row exists for it.

**Two were closed by making a distinction the code already knew.** The kanban PUT was a
detector false positive: it dumps nested checklist items, not the patch body, and the
detector now reads the receiver of `model_dump()` instead of carrying the difference as an
allowance. The `Location` phantoms were not debt: they describe a server field declared
`Dict[str, Any]`, so the question the sweep was asking had no answer. In both, the fix was to
make the sweep ask a better question rather than to change the code it was asking about.

**One had a second defect hiding behind it.** Narrowing registry creation would have caused
silent data loss, because `_create_registry_item_from_analysis` carried the comment "Get or
create registry for domain" above code that only got — returning None and dropping the item
when the row was missing. Harmless while all 46 were pre-created. **The blocker had been
protecting a bug.**

### Four weak assertions, all caught the same way

Four guards written this week passed with their fix mutated out:

| guard | why it passed anyway |
|---|---|
| buffer-loss counter | 400-char window reached the *next* loss path's counter |
| heartbeat producer | substring search matched the name one line above the emitted key |
| registry initializer | source-text check matched the string inside its own docstring |
| uncontracted-field exemption | `re.search` found a second declaration of the same field |

Every one was found by deleting the fix and re-running, and every one would have shipped as a
green claim that somebody had checked. The shape they share: **a check that looks near the
right place rather than at it.** Bind the variable, parse the keys, run the function.

## Rule 95 — closing a decision often means deleting, not building

Two of five closed by removing something that had been framed as work to add.

## Rule 96 — a too-broad exemption is worse than the entries it removes

Exempting to silence five meaningless entries silenced 34 real ones on the first attempt.
Check both directions of an exemption before believing the count it produces.

---

