# Part 5 — the carry-across era

What the session produced and cost, then classes 73–90 and rules 97–125 — the era of taking a closed class and asking which other component computes the same quantity.

*One part of [Defect-class sweeps](../defect-class-sweeps.md), which carries the index of every class and links to the other parts.*

---

# What this session produced, and what it cost

**FS-431 to FS-490 — sixty items, no gaps** — over one working session. Recorded
together because the individual entries above answer "what was wrong" and this answers "what
the method actually does", which is the thing worth reusing.

The count is stated because it is checkable, and it was wrong when first written: the draft
said "forty items", a figure nobody had counted. `test_the_session_arc_is_a_real_range.py`
now derives it from the FS references in the tree. Four wrong figures in this documentation
in one week is what that guard family exists for, and writing a fifth into the paragraph
describing them would have been its own small joke.

## The shape of the work

It ran in three phases, and each produced a different kind of finding.

**Opportunistic.** Fix a defect, notice the class, sweep for it. This produced the E2E work
(FS-447 to FS-452), the document-intake tests, and the truncation-flag chain. Its strength is
that the class is fresh in mind; its weakness is that what you find depends on where you
happened to be standing.

**Component-by-component.** Take a subsystem nothing has examined and read it. This is how
the edge agent's 14,349 lines came under review at all, and it produced FS-457 (synthetic data
that could ship unstamped) and FS-458 (a buffer loss nobody could see). Its weakness showed up
immediately: three consecutive findings turned out to be classes the backend had **already
fixed**, discovered by accident, one at a time.

**The carry-across pass.** Take each closed class and ask which other component computes the
same quantity. Run in all three directions — backend → agent, agent → backend, both →
frontend — it found four more defects in an afternoon and, more usefully, produced a set of
*clean* results: 24 unbounded loops that all sleep, 17 collector classes with symmetric
lifecycles, 25 metrics all incremented, SQL parameterised throughout. Negatives are the
expensive thing to re-derive, so they are written down beside the positives.

The progression is worth naming: **opportunistic finds what is nearby, component sweeps find
what is unread, and carry-across finds what is already understood but not applied.** The third
is the only one that terminates.

## Where the numbers ended

Four ratchets at zero, the open-decisions register empty, and every figure in the
documentation paired with the thing it describes. The routes to zero were not the same:

| ratchet | from | closed by |
|---|---|---|
| unfed fields | 38 | building the missing producers |
| adapter-unset fields | 17 | building, one layer further in |
| unsignalled capped lists | 11 | `limit + 1` and one function call per endpoint |
| phantom frontend fields | 5 | discovering the question had no answer |
| open decisions | 7 | two by deleting, two by distinguishing, three by deciding |

## What it cost

**Eight defects were mine**, introduced while fixing something else. Three endpoints answering
500 because a rewrite added a call to nine handlers and a parameter to six. Four documentation
figures wrong in a single week. A test asserting 1.0 hours that got 6.0 because I used a naive
local timestamp inside a guard written for naive-timestamp defects. An open-decisions entry
whose central claim was false because I read one of two consumers and generalised.

**Four guards passed with their fix deleted.** A window that reached the next call's evidence,
a substring that matched the line above, a source check that matched its own docstring, a
`re.search` that found a second declaration. Each was caught by mutating the fix out — never
by review, never by the suite — and each would otherwise have shipped as a green claim that
somebody had checked.

**A fifth wrong figure, written into the paragraph about wrong figures.** The README's new
"where the programme stands" note first named five peak ratchet values and three were wrong:
it gave an adapter-unset allowance that was introduced at zero and never had slack, and
quoted the final pre-zero values for two others as though they were the starting ones. Caught
by checking `git log -S` before committing, which took thirty seconds and should have come
before the sentence rather than after it.

The lesson has stopped being about carelessness. Five times now, and the common factor is
always the same: **a number recalled into prose.** The figures in this repository that have
never been wrong are the ones a test derives — the rule index, the class count, the ratchets,
the FS range. The ones that keep being wrong are the ones a person typed from memory into a
sentence. That is not a discipline problem with a discipline fix; it is an argument for
deriving more of them.

**The detectors were wrong before the code was.** The hot-spin sweep flagged the
best-protected collector in the tree. The provenance sweep missed every site by searching for
the wrong helper name. The client-constructed exemption silenced 34 real types to remove five
meaningless ones. In each case the first run's output was noise, and the useful work was
narrowing the detector until its output was a list somebody would act on.

If there is one thing to carry forward from all of it: **a green test is a claim that someone
checked, and the only way to know whether it is true is to break the thing it checks and watch
it fail.** Four of the guards written this week were decorations until that step, and none of
them looked like decorations.

---

## Class 73 — a retry loop that retries at the same rate whether or not anything is working

**Where:** `edge-agent/opsgrid_agent/collectors/{profinet,dnp3,bacnet,ethernet_ip,can_bus}.py`
(FS-472)

Every industrial collector runs the same loop: read, and on failure drop the connection and
sleep. Five of them slept for `poll_interval` — **the same interval they use when everything
is working** — so a PLC that was switched off drew a connection attempt every five seconds
indefinitely. Roughly 17,000 a day, each costing the device a socket it has to refuse.

It is not a data defect, and that is why it lasted: the readings are correct, the suite is
green, and the only symptom is a device being dialled at a rate nobody chose. It surfaced as
a note during the hot-spin sweep (which correctly reported these loops as *not* spinning —
they do sleep) and was set aside as "a robustness gap, not wrong data". That was the right
call at the time and the wrong place to leave it.

**The machinery already existed.** `resilience.py` has `ExponentialBackoff` and a three-state
`CircuitBreaker`, both with their own tests, and `modbus`, `opcua` and `mqtt` have used them
since they were written. The five that did not were written later. Nobody decided against
them; nothing in those files pointed at them.

Measured on a dead device over twelve loop iterations: **five connection attempts instead of
twelve**, delays of 1, 2, 4, 8, 16 seconds, and then the breaker holding at its cooldown. In
steady state an unreachable device is probed once per 300-second cap rather than once per
poll interval.

The guard checks four things per collector — constructs both instruments, consults the
breaker *before* attempting, records both outcomes, and sleeps on the backoff rather than the
poll interval — and then runs a loop against a device that always fails, because the first
four are structural and a collector can satisfy all of them while still retrying at a fixed
rate.

## Rule 97 — a shared utility is only shared if the files that need it point at it

Class 73. Three collectors used the resilience module and five reimplemented the loop without
it. When a utility exists for a problem that recurs, the question is not whether it is good
but whether the next person writing that problem will find it.

## Class 73, second half — the fix that spread the guess (FS-473)

FS-472 above is complete and was not finished. It gave five collectors a backoff and a
breaker by copying four constants into each, and the summary said so plainly: *"I left the
tuning alone — it's the same first-pass guess modbus has carried since it was written."*

That was true and it understated the problem. The constants were now in **sixteen places
across eight files**, one of which carried a `TODO(tune)` explaining they were provisional
pending production telemetry. Whoever eventually holds that telemetry would have had to find
all eight, and the ones they missed would keep the old behaviour while looking deliberate.

**And the copies were less capable than the originals.** `modbus`, `opcua` and `mqtt` accept
an injected `backoff=` / `breaker=` so the coordinator can hand one collector a tuned
instrument. The five new ones accepted nothing — the fix imitated what made the pattern work
and not what made it changeable.

`ReconnectPolicy` now owns the numbers. **They have not changed**: the same guess, in one
place, with a `reconnect:` block in collector config to override them per site and injection
available everywhere. All eight collectors take it the same way, through two entry points
(`from_config` for the config-dict collectors, `from_settings` for the three built from
keyword arguments) that reach identical validation — because an operator writing YAML cannot
see which kind they are configuring.

Two validations earn the class rather than a dict:

* **an unknown key is an error.** A typo that silently keeps the default is a tuning the
  operator believes they applied;
* **the pair must agree.** `max_delay > cooldown_cap` means the loop already waits longer
  than the breaker's cooldown, so opening it changes nothing — an instrument that is present
  and inert.

The guard that checked the original fix had to change, and that is worth recording too: it
asserted `ExponentialBackoff(` and `CircuitBreaker(` appeared in each collector, which was
true only while every collector built its own. Factoring them out failed five collectors that
had just become more correct. **A guard written against one implementation of a property
fails the next implementation of the same property** — it asks about the attributes now, and
separately asserts that no collector hardcodes the tuning.

## Rule 98 — spreading a guess is worse than leaving it in one place

Class 73. Before copying a constant into a fifth file, ask who will have to find all five.

## Rule 99 — a fix that copies the pattern should copy the seams too

Class 73. The five copies took the instruments and left behind the injection parameter, so
newer code was less configurable than the code it imitated.

## Class 73 in the cloud — the same loop, one boundary out (FS-474)

Carried across the moment class 73 was written, rather than waiting to trip over it. Asked of
the backend: which loops here retry at the same rate whether or not anything is working?

The sweep examined every loop containing a `sleep` and an exception handler, and separated
those whose delay grows from those whose does not. Twenty-one loops, six candidates, and
**one real instance** — `CommandExecutor._ack_consumer_loop`, which has two exits (the
consumer will not start; the consumer errors mid-stream) and slept a flat five seconds on
both. A broker down for a day drew roughly 17,000 connection attempts and 17,000 error lines.

The five other candidates were correctly rejected, and why is worth recording:

| site | verdict |
|---|---|
| `command_executor` dispatch and timeout loops | **periodic polling.** A constant interval is the design; there is no device to back off from |
| `erp_database_replication` | already sleeps longer on error (10s → 30s) — crude, but not a fixed rate |
| `feature_extraction` egress cycle | a scheduler cycle, 10s on error against a normal interval |

**The values live in `command_executor.py`, not in a policy class.** The agent has eight
collectors with this loop, so `ReconnectPolicy` earns its place there; the backend has one.
Building a framework for a single caller is how a guess reaches eight files, which is the
mistake FS-473 spent a pass undoing. Rule 98 cuts both ways: do not spread a guess, and do
not build the thing that would let you.

The guard's first version flagged `await asyncio.sleep(1)` inside the per-message handler —
a legitimate pause after ONE message failed, which seeks back to the offset before
re-entering. Nothing to do with reaching the broker. It distinguishes structurally now:
reconnect handling sits at the top level of the `while` body, per-message handling inside the
`async for`. **A guard that cannot tell a real pause from a defect gets turned off by the
next person**, and this is the sixth detector this week that was wrong before the code was.

## Classes 98 and 99 carried across (FS-475)

The other two classes from the reconnect work, asked of the backend and the frontend.

### Class 98 — a guess spread across files. **One real instance, and it is not a guess.**

The sweep looked for named constants with the same name and value declared in more than one
module. Two hits, and both are the same thing: `MAX_DRIVE_HOURS_DAY` and
`MAX_ON_DUTY_HOURS_DAY` — the FMCSA driving limits from 49 CFR 395 — declared in
`api/transportation.py` and again in `services/transportation_management.py`. A third file,
`api/fleet_logistics.py`, reached them through the compliance class.

**These are law, not tuning, which makes the duplication worse rather than better.** The two
copies feed different answers about the same driver: `api/transportation.py` computes hours
REMAINING, which a dispatcher reads before assigning a load, and the compliance service
decides VIOLATIONS, which is read afterwards. Edit one and not the other and the platform
tells a dispatcher a driver may keep driving while recording that same driver as in breach.
Both numbers look authoritative and neither says which is stale.

**Why it survived review** is the part worth keeping. The duplicate carried a reason:

> *Kept beside the serializer that needs them rather than imported from the compliance
> service, which would drag its session dependencies into this module.*

That objection was true. It was also already being ignored, since `fleet_logistics` imports
the same class for the same purpose. **A justified duplicate is harder to spot than an
unjustified one**, because the comment answers the question a reviewer was about to ask.

The answer was a module with no imports: `backend/app/core/hos_limits.py`. A constant cannot drag a
session dependency if it lives somewhere that has none. All three access paths now resolve to
the same object, asserted with `is` rather than `==` so a second set of values that happens to
match today still fails.

### Class 99 — a pattern copied without its seams. **Clean.**

* **Service classes**: only two accept an injected collaborator at all, so there is no
  population of siblings where some are injectable and some are not.
* **The four workers**, which genuinely are copies of one another, all take the same
  `stale_after_seconds` seam — and use it deliberately: ingestion at 300 seconds because
  telemetry is continuous, the other three at 0 with comments explaining that scheduled and
  orchestrating work is legitimately bursty. That is the pattern applied well.

### The frontend — no instance with a consequence

`MOCK_DELAY` is declared in nine api clients at two different values (300 and 500), and
`REFRESH_MS = 30_000` in two hooks. Both are duplication; neither has a consequence, since
one is development-only and the other is a polling interval where the two copies agree.
Recorded rather than "fixed" because unifying them would be motion, not work.

**And the documentation guard caught this entry twice.** The first citation of the new
module omitted its `backend/` prefix; the paragraph written to explain that then spelled the
bad path out, and the guard reads a backticked path as a citation whether it is being made or
quoted. Fourth time prose explaining a defect has tripped the detector for it — describe the
shape, do not reproduce it.

**One detector note.** The frontend scan reported `REFRESH_MS = 30`, having read `30_000` as
`30` — a numeric separator the regex did not expect. Thirty milliseconds would have been a
hot refresh loop and a real finding; it took one look at the file to see it was thirty
seconds. Seventh detector this week to be wrong before the code was, and the first where the
error was in the reported VALUE rather than in what it selected.

## The plan overstated again (FS-476)

`fixed-sprints-241-343.md` was written from the task pools, and five of the eight items
examined described work already delivered. `fixed-sprints-344-393.md` was written **from the
codebase specifically to avoid that**, and by 2026-08-06 eight of its own entries no longer
reproduced — `FS-266`, `FS-272`, `FS-345`, `FS-350`, `FS-354`, `FS-357`, `FS-359`, `FS-361`.
A ninth, `FS-368`, is half true: the defect is fixed and the capability is not.

**Overstating is the harder direction to catch.** A plan that flatters gets checked, because
somebody eventually goes looking for the thing it claims is finished and does not find it. A
plan that inflates is never investigated — nobody audits a backlog for being too long — and
the cost is paid quietly, in work planned twice and estimates built on a number that was
never true.

**Why it happened twice** is the part worth keeping, because the second plan did everything
the first got wrong. It was derived from the code, every item carried a file and a line, and
unverifiable claims were marked as such. None of that helped, because the failure is not in
how a plan is written — it is that **a plan is a snapshot of a belief about a repository, and
the repository does not update it.**

The documents in this repository that have not drifted are the ones written as things happen:
the delivery log, and this file. The ones that drift are written in advance. That is not an
argument against planning; it is an argument for a plan carrying a *dated verification pass*
rather than a status column, and for the checkable part of it being asserted like everything
else here.

`backend/tests/test_the_plan_does_not_claim_finished_work.py` holds the narrow part: an item
recorded as delivered must stay delivered, a fix cited as closing one must be findable, and no
item may appear in both the delivered table and the still-open list. It cannot judge whether
a multi-day item is done — but it can stop the document contradicting itself, which is how
both drifts began.

## Rule 100 — a plan overstating what is left is harder to catch than one that flatters

Nobody investigates a backlog for being too long.

### FS-355 was the ninth, and my own verification pass missed it

The pass above checked whether `error_events` has an RLS policy. It does not — and that was
recorded as "still open" without asking the next question.

The absence is deliberate. The table is keyed on `fingerprint` alone **by design**: one row
per distinct error for the whole platform, because a bug that two tenants hit is one bug. The
disclosure risk was found, reproduced against a real database, and fixed by redacting the two
payload-bearing fields from viewers outside the row's organisation; the write side 403s when
the caller does not own the row. And `test_error_triage_sample_redaction_realdb.py` records
why scoping the view by organisation was **rejected** — a shared row's `organization_id` names
only one of the tenants that hit the bug, so filtering on it would hide errors that genuinely
are the caller's.

Adding RLS there would not harden the table; it would break the view it is meant to be. The
question that remains is FS-311's — there is no platform-admin role, so tenant admins are
doing platform triage — and that is a decision already on the page.

**This is the same error as FS-460, in a different costume.** There I concluded a field
reached nobody after finding one of its two consumers; here I concluded a policy was missing
after finding it absent. Both are negatives asserted from half a search. The saving grace both
times was the same: the answer was one grep away, in a file whose whole purpose was to record
it.

It is also the argument for verifying before building. The plan sized this L — a primary-key
grain change, a composite foreign key, and a rewritten upsert — against a working feature whose
current shape is documented and intentional.

## Rule 101 — absence is not evidence of a gap until you have checked whether it is deliberate

"No RLS policy" is a fact; "missing an RLS policy" is a conclusion. The difference is a second
search, and the reasoning is often in a test docstring rather than in the code.

## FS-477 — a refusal offered as a stack trace

Found while looking for an untested page to write a test for, which is the argument for
FS-364 in one sentence.

`error_events` is a platform-wide table by design, so the server withholds another
organisation's `message_sample` and `traceback_sample`, substituting
`[redacted: belongs to another organization]`. The detail page renders that placeholder in
its code block **on purpose** — `ErrorTriageDetail.test.tsx` asserts it, because "No traceback
captured." is a claim about the error while a redaction is a claim about the viewer's
permissions, and showing the first where the second is true tells an operator the wrong thing.
That decision is right and was not touched.

**What was wrong was the frame around it.** The card's subtitle read "Latest occurrence ·
scrubbed of PII" over a sentence that is neither. And the Copy button was **enabled** — the
marker is a truthy string — so an operator could put `[redacted: belongs to another
organization]` on the clipboard and into a bug report, believing it was a stack trace, and
find out from whoever read it.

Both now read `samples_redacted`, a boolean the server derives from the same condition that
does the withholding. **Matching the marker text on the client would have worked today and
broken the day somebody improved the wording**: prose is not an API. The flag is also
narrower than the condition — an outsider viewing a row that captured no samples has had
nothing kept from them, and a withholding notice over an error that never had a traceback is
an absence dressed as a refusal.

### Two things this pass got wrong first

**The page was not untested.** A detector matched test files by filename and reported
seventeen routed components with no coverage; the real number is four. `ErrorTriageDetail`
was on the false list, and I began writing a duplicate test file for a page that already had
a thorough one. The tool's read-before-write guard stopped it — not the reasoning.

**And the first fix reversed a deliberate decision.** Before checking the existing test, I
had replaced the code block with prose for redacted rows, which would have failed an
assertion written specifically to keep the placeholder visible. The existing test explained
why in its docstring.

Both are the same error as FS-355 and FS-460: **a conclusion drawn from half a search.** Three
times in two days, in three different costumes — a missing consumer, a missing policy, a
missing test. The correction each time was cheap and the same: read the thing that would have
told you.

## Class 74 — a guard scoped to one idiom, and the same defect in another (FS-478)

`mutationFailureIsVisible.test.ts` sweeps every `useMutation` for options that handle only
success, and its docstring is emphatic about why: a failed mutation renders as **nothing at
all**, and the user pressed the button on purpose, so the absence of a response is
indistinguishable from the moment before the list refreshes.

It reads `useMutation` call sites. **Five mutations in this codebase are hand-rolled** — an
`async` handler that awaits an api call and catches into `console.error` — and were
structurally invisible to it while being exactly the defect it exists to prevent.

| where | what a failure looked like |
|---|---|
| `IntakeInbox.handleAnalyze` | the spinner stops, the row stays pending — which is what an item with nothing to analyse looks like |
| `IntakeInbox.handleUpload` | the file simply does not appear in the list |
| `ContextManagementModal` ×3 | the modal stays open, which is what it does while saving |

The analyse case is the sharpest: the page shows a risk score once analysed, so "no score"
reads as "not analysed yet" rather than "the analysis failed", and the operator's remedy is
to wait.

**The heuristic is deliberately narrow.** It requires an awaited `…Api.<verb>` call in the
preceding window and a catch whose body only logs. A broader version flagged every defensive
`catch { console.warn }` around optional enrichment — not this defect, and enough of them to
make the list unreadable. A sweep that spends the reader's trust on noise stops being run.

**Found while writing a test for a page that had none**, which is FS-364's argument. The e2e
route sweep covers these pages for `undefined` and `NaN`; it has nothing to say about a
button that does nothing and admits nothing.

## Rule 102 — a sweep scoped to one idiom is blind to the same defect in another

State a guard's scope, and when a class has two idioms, sweep both. An unstated scope reads
as "everywhere", which is how five mutations sat inside a swept class without being swept.


## Class 75 — a caveat that reaches the screen and not the file (FS-479)

`Historian.exportCsv` wrote the header and the points and stopped.

The query is capped. `hasMore`, `limit`, `offset` and `count` all come back, and the page
renders them: "2 points (more available)". The CSV carried none of it — and **the CSV is the
artefact that leaves the building**: filed, mailed, opened in a spreadsheet by somebody who
never saw this page and reads it as the history of that metric over that window.

```
# PARTIAL: the first 2 points of a larger result (limit 2, offset 0).
# Narrow the window or raise the limit for the rest.
timestamp,average,minimum,maximum,sample_count
```

**The preamble goes at the top.** Spreadsheet software shows the first rows; a caveat below
ten thousand points is a caveat nobody reads. And it appears only when `hasMore` — a warning
on every export is one nobody reads either, and it would make the capped case
indistinguishable from the complete one.

The same shape as the intake risk score (FS-456), one boundary further out: there, a partial
reading produced a confident number on screen; here, a complete-looking screen produces a
partial file. **Ask of every export what the screen beside it knows that the file does not.**

`Historian` also announced its first failed query as an empty window — `error && points.length
=== 0` fell through to "No data points in this window", which tells an operator their machine
was idle when the truth is that nobody knows. Now `role="alert"`, and it says which it was.

## Class 74, third hiding place — the mutation defined in a hook (FS-480)

Class 74 closed the hand-rolled idiom. Both sweeps scan `.tsx`, because that is where
components live. **Mutation hooks live in `src/hooks/*.ts`** and were outside both.

Sixteen of them. Seven had call sites that read nothing:

| hook | what a failure looked like |
|---|---|
| `useYankAgentRelease` | the release stays listed — which is what it does for the moment before the refetch |
| `useCancelAgentRollout` | the badge still reads "running", which is also what a successful cancel looks like until the refetch |
| `usePauseAgentRollout` | same |
| `useCreateAgentRelease` / `usePublishAgentRelease` / `useCreateAgentRollout` | nothing appears |
| `useAcknowledgeAlarm` | the alarm stays unacknowledged, which is what it looks like mid-flight |

The two safety actions are the sharp ones. A yank pulls a release that is going badly; a
cancel stops a rollout mid-flight. Both failed silently, and both look — for a second or two
after a success — exactly like what the operator just saw.

**The obligation is the caller's, not the hook's.** A hook returning `useMutation` is a
library: it has no screen to render on. So the new check asks of each *used* hook whether its
call site surfaces the failure, by any of the three idioms this codebase actually uses —
`.isError`, `mutateAsync` inside a try, or `mutate(x, { onError })`. An earlier version knew
only the first two and reported `ErrorTriageDetail` as silent when it was not.

**And only where the hook is used.** Eight of the sixteen have no caller at all — exported
from `src/hooks/index.ts` and never imported. There is no user to fail in front of; flagging
them would be noise. Dead exports are a different and much smaller problem.

## Class 76 — the label moved and the content did not (FS-481)

Every check above asks whether a failed **write** reaches the user. This is a failed **read**,
and it is worse than any of them.

```tsx
const handleSessionSelect = async (session) => {
  setCurrentSession(session)                                  // the label moves now
  try   { setMessages(await api.getSessionMessages(session.id)) }
  catch { console.error(e) }                                  // …or never
}
```

On failure the header, the data-sources panel and the suggested-questions effect have all
moved to session B, and the message list still holds **session A's conversation**. A silent
write leaves the screen truthful-but-stale. This makes it *actively wrong*: another
investigation's transcript, under this session's name, with nothing about it that looks
wrong. An operator has no reason to doubt it.

The fix is two things, and the first matters more than the second: **clear the stale content**,
then say why it is empty. Announcing the failure while leaving the wrong transcript on screen
would be worse than the original.

The same ordering exists in `bootstrapSession`, where `messages` is empty at boot — so there
the failure mode is only the milder one, a named session with no history, indistinguishable
from a session nobody used. Both now say so.

Two more from the same file: `handleAddIntakeData` dropped its failure to the console, so the
document never appeared and the next answer was computed from a data set the operator believed
contained it. And widening the Class 74 verb list (`add`, `remove`, `attach`, `cancel`,
`pause`, `resume` — `add` and `remove` were simply missing) surfaced
`DataSourcesPanel.handleRemove`: a failed removal left the row exactly where it was, which is
also what a click that never registered looks like, so the reasonable second reading is that
it worked and the list is stale. It did not. The file is still attached, and still feeding
answers.

**The sweep is narrow on purpose**: the setter must be called with the handler's *own*
parameter, the awaited read must come after it, and the catch must neither set state, alert,
nor rethrow. Loosening any of the three floods the list with ordinary loaders. It found one
occurrence in the codebase — the one above.

## Rule 103 — ask of every export what the screen beside it knows that the file does not

A caveat rendered next to a number is not attached to it. The file leaves; the screen does
not. Anything the producer knows about the completeness of a result belongs in the artefact,
at the top, and only when it is true.

## Rule 104 — clearing the stale view comes before announcing the failure

When a fetch fails after the thing it belongs to has already changed, the first obligation is
to remove what is now mislabelled. A message beside the wrong content is worse than no
message, because it invites the reader to look at the content.

## Rule 105 — a verb list is a scope, and an unlisted verb is an exemption nobody granted

`add` and `remove` were absent from the Class 74 verb list. Nothing recorded that decision
because nobody made it. When a sweep enumerates what it matches, the enumeration is the
guard's real boundary — re-read it when the class turns up somewhere new.

## Class 77 — a failed read defaulting into the branch that causes harm (FS-482)

`failureIsNotEmptiness.test.ts` has covered this class since `YardManagement` rendered "No
trailers found" at a yard manager. It carries two detectors: one keyed on an **empty-state
phrase**, one on a **widget gate**. Both need something in the render to key on.

Neither can see a query whose failure falls through to something with no string of its own.

**`ShopFloor.ClockTime`.** `{ data: open, isLoading }` — no `isError`. On failure `open` is
`undefined` and `isLoading` is `false`, which is the exact shape of *"no clock is running"*.
So the card offered **Clock in** to somebody who may already be clocked in.

The page already knew what that costs. The message under that very button reads:

> two open clocks produce overlapping hours and payroll cannot tell which is real

A failed read defaulted into the state the page warns about, on the page that warns about it.
The fix shows **neither** button and offers a retry — because falling back to "Clock out"
would be the mirror defect, telling an operator who is not clocked in that they are.

**`YardManagement`, doors tab.** `{ data: doorsData, isLoading: doorsLoading }`. A failure
rendered the same blank grid as a dock with no doors configured. The trailers and appointments
tabs in that same file both distinguish the two — written by somebody who had already met this
class and fixed it twice. The doors tab was one short, which is the shape a per-tab fix always
leaves.

**The new detector keys on the destructure, not the render.** Reading `isLoading` is a
component saying out loud that it models "not yet known" as its own state. Having said that
and then omitted `isError`, it has collapsed "the request failed" into "the answer is no". A
component reading neither flag is not flagged — that is `data ?? []` with no loading state
either, a different and far more visible kind of unfinished.

Two occurrences in the codebase, both above, both now closed.

## Rule 106 — when a failure has to default somewhere, default away from the irreversible side

Every unhandled read lands in some branch. Ask which branch costs more when it is wrong.
`ClockTime` had two: offering to clock in (creates a duplicate payroll record) and offering to
clock out (a no-op that fails loudly). It defaulted to the first. Where neither direction is
safe, show neither and say why — a screen that declines to guess is usable; a screen that
guesses wrong is not.

## Rule 107 — a fix applied per instance leaves the instances nobody was looking at

`YardManagement` handles this class on its trailers tab and its appointments tab. The third
tab, in the same file, under the same author, was never touched — because the fix was made
where the bug was reported rather than where the class lives. When you fix a class in a file,
enumerate that file's other instances before you leave it.

## Class 74, fourth hiding place — the mutation that is not an api call (FS-483)

`silentHandRolledMutations` keys on `await …Api.<verb>(`. `Kanban.handleDragEnd` awaits
`moveTask(…)` — destructured from the kanban store — and the `api.post` it wraps lives in
`kanbanStore.tsx`, two files from the `catch`. No window over `Kanban.tsx` could have seen a
mutation happening at all.

`moveTask` posts to the server *before* it updates local state, so on failure the card
re-renders in the column it came from. **That is also exactly what a mis-drop looks like.**
The operator reads it as their own miss, drags again, and the board and the server go on
disagreeing about where the task is. A snap-back is not a message; it is a shrug.

The fifth check keys on the **verb in the callee's name** rather than on an api object, with
two exemptions taken on principle rather than by name:

- **A catch that `return`s is propagating the failure by value**, not swallowing it.
  `CorrelationAIPane.handleSessionMissingForUpload` returns `null`, and `DataSourcesPanel`
  branches on that and rethrows into a surfaced `uploadError`. Same lesson as the hook check:
  the obligation can live at the call site, and a sweep reading one file cannot see it.
- **A catch that only `console.warn`s is the defensive-enrichment shape** the first heuristic
  in this family was deliberately narrowed to exclude. A failed `generateSessionTitle` costs a
  session its auto-title and nothing else.

Without those two the check reports two offenders that are not offenders. It was measured
before it was added: two hits, both false, zero true — the exemptions are what make it worth
running, and both were verified by reading the callers rather than assumed.

**Four hiding places for one class**, found in order: the `useMutation` options object, the
hand-rolled `async` handler, the hook file the sweeps did not scan, and now the store action
whose api call is in another file. Each was invisible to every check written before it.

## Rule 108 — measure a proposed guard's yield before adding it, and read every hit

A new check earns its place by what it finds, not by what it could find. This one was run
across the tree first: two hits, both false positives on inspection. Adding it unread would
have put two permanent lies in a report people are meant to trust; discarding it unread would
have left the class open. Reading both is what produced the two exemptions, and the exemptions
are the guard.

## Class 78 — a resolver that reports "none left" for everything reached another way (FS-484)

FS-364 listed eight routed pages with no test. Answering "which are left?" meant reading the
lazy imports out of `App.tsx` and looking for a sibling `.test.tsx`. That walk reported zero
remaining — **twice** — while `Fleet` (574 lines) and `ErrorTriage` (371) had no test at all.

Both are imported through a barrel:

```tsx
const Fleet = named(() => import('./pages/admin'), 'Fleet')
```

The string `pages/admin/Fleet` appears nowhere. A resolver keyed on the import path goes
looking for a test beside the *barrel directory* rather than beside the page, finds no page
there either, and reports nothing missing.

**A walk that under-reports is worse than no walk**, because "none left" is the answer nobody
re-checks. The same shape has appeared in this document before under different names — a
detector that matched test files by filename, a sweep that scanned `.tsx` while the code lived
in `.ts` — and it will appear again. What they share is a resolver that models one way of
reaching a thing and silently returns nothing for the others.

The guard now follows `named(loader, 'Export')` into `pages/<dir>/index.ts` and resolves which
module actually exports that name, including exports renamed on the way out (`UsersPage as
Users`) — without which the four AdminPages routes resolve to nothing and drop out of the
check, which is the same defect one level down.

Its vacuity tests assert three things separately: it resolves a direct import, a barrel
import, and a renamed barrel export. A broken resolver returns an empty list, and an empty
list passes every comparison in the file.

## Rule 109 — a walk that finds nothing must prove it can find something

Any sweep that answers "which are left?" needs a test that it can still resolve a known
member. Otherwise the day its resolver stops matching, its answer becomes "none" — which is
indistinguishable from success, arrives without a failure, and is believed.

## Class 79 — a flag the server went out of its way to send, dropped by the client (FS-485)

`mark_truncated` selects `limit + 1` rows and sets `X-Result-Truncated`. Every endpoint that
does it has already been judged worth the extra row: somebody decided the difference between
a full page and the complete set mattered enough to change the query.

Then the client returns `response.data`, and the flag is gone. Nothing fails, no type
complains, and the page renders a page of the list as the whole list.

**`notificationsApi.deliveryLog`** was the one. The log is ordered newest-first, so a cap
removes the *oldest* attempts — and the question that card answers is "was that alert
delivered?". A row absent from a list presented as complete says the alert was never sent,
which is a statement about the notification system rather than about the query.

**One deliberately left.** `CommandPanel`'s history is capped at five and reads
`response.data`. Checked rather than skipped: it is newest-first, the heading reads "Recent
commands", and the command an operator just sent is in the first five by construction. The
label already carries the caveat. That decision is recorded *in the guard's allowlist with
its reason*, and a second test asserts the exemption still names an endpoint the frontend
calls — a stale permission is how an allowlist stops describing the code it guards.

**The guard is a backend test because the question needs both trees.** The backend is the
only side that knows which endpoints signal; the frontend is the only side that knows which
of them are called.

### Three detector defects before one code defect

Worth recording, because the detector was wrong three times and the code once:

1. **Slicing on `@router.get` alone.** A `@router.post` between two GETs put a later
   handler's `mark_truncated` inside an earlier handler's slice. It reported
   `DELETE /{id}/mappings` as a truncating route.
2. **Matching on the last path segment.** `/erp/integrations/{id}/events` collided with
   `/fleet/security/events` — unrelated endpoints, one of which does not truncate.
3. **Capturing the URL up to the first `${`.** ``` `${BASE}/log` ``` became the empty
   string, which then matched every route whose prefix failed to resolve. Eleven reported
   offenders, none real.

And the prefix resolution had its own hole: three routers — `registries`,
`analysis_sessions`, `erp_integrations` — declare the prefix on their own `APIRouter` and are
included bare, so reading only `main.py` dropped all three *silently*. That is Rule 109
again, one week later, in a sweep written by somebody who had just written Rule 109. The
vacuity test that now fails on an unresolved prefix is the fix.

## Rule 110 — an exemption belongs beside the guard, with its reason and an expiry check

"Checked and deliberately left" and "never looked at" are indistinguishable afterwards, and
only one of them justifies not looking again. Put the decision in the allowlist, put the
reason next to it, and add a test that the exempted thing still exists — otherwise the
allowlist slowly stops describing the code and starts excusing it.

## Class 80 — a capability that ships and cannot be reached (FS-486)

Every sweep in this document so far asks whether what the UI does works. None asks **what the
UI cannot do**.

`ERPIntegrations.tsx` builds its create-form dropdown from `erpApi.supportedTypes()`, a
hand-written array of seven strings. That array is the entire surface through which an ERP
integration can be created. It was compared against nothing.

`ERPConnectorFactory._REGISTRY` has eight entries. The missing one is `intuit` — QuickBooks
Online — a 384-line connector with OAuth token rotation, webhook signature verification, a
health check, and two test files including a sandbox suite. It works. Nobody could select it.

**The guard runs in both directions**, because the other one is worse when it happens:

- *Offered but unbuildable* — the operator picks a type, fills in credentials, submits, and
  `ERPConnectorFactory.create` raises. They have done work and have nothing to do about it.
- *Buildable but unoffered* — a shipped capability nobody can reach. Silent forever, because
  nothing in a test suite asks about the absence of an option.

It compares against the **factory registry**, not the `ERPType` enum. The enum has nine
members; `generic` is in it and correctly not offered, because the factory cannot build one.
The enum says what the codebase has words for; the registry says what it can construct, and
only one of those is a promise to a user.

The label followed the same logic. Uppercasing the type is the product name for every entry
but that one — `intuit` is the vendor, QuickBooks Online is the product — and an operator
connecting QuickBooks does not scan a list for "INTUIT".

## Class 81 — the number is right and the label is wrong (FS-486)

Two in the same sweep, and this is the harder direction to notice: nothing on the screen looks
incorrect.

**`PerformancePanel`'s range selector** offered "Today / This Week / This Month / This Quarter
/ This Year". `app/api/kpi.py` computes `now - timedelta(days=_RANGE_DAYS[range])` — a
**rolling window**. On the 6th of August, "This Month" is the 7th of July to the 6th of
August, and most of what it reports happened in a month the label does not name. Fuel
efficiency, idle time, on-time performance and cost per mile all hang off it, and each figure
is one somebody compares against last period's.

Every other range selector in the application — Historian, ErrorTriage, AnalyticsPages —
already reads "Last N days". This one was the exception, so the fix was to make the label
agree with the computation and with the rest of the product, not to change what is computed.

**`AnalyticsPages`' metric chart** called `telemetryApi.getHistory`, which returns
`response.data.items` and discards the `{items, meta}` envelope — a documented choice, so
short-window chart consumers keep a plain array. But that page offers a 30-day range against a
1000-point server default: at minute resolution the cap is ten times under, so a chart headed
"Last 30 Days" plotted one end of the window with nothing saying which end, or that there was
another. **A trend taken off the wrong end of a window is not a partial answer; it is a wrong
one, and it looks exactly like a right one.** It reads `getHistoryPage` now and says so when
`meta.hasMore`.

`TelemetryHistoryChart` had already been doing this — it gates a "Load older" control on the
same flag. The pattern existed; one page had not adopted it. Rule 107 again.

Note the mechanism: this is a fourth spelling of the truncation signal, and the FS-485 sweep
could not see it. That sweep keys on `mark_truncated` and `X-Result-Truncated`; this endpoint
carries `has_more` inside a JSON envelope. Same claim, different wire, different guard.

## Rule 111 — ask what the interface makes impossible, not only whether it works

Every check that starts from the UI's behaviour is blind to the option it never offers. When a
list in the frontend enumerates what a user may choose, compare it against what the backend
can actually do — in both directions. The absent option produces no error, no log line and no
failing test, and it can outlive everyone who knew the feature existed.

## Class 82 — the poll that stopped, on a screen with no error state (FS-487)

`/ws/fleet-tracking` and `/ws/geofencing` do not exist on the backend; both were replaced with
REST polls when that was found. Each poll's catch ended at `console.error`.

**A subscription has no promise for a caller to catch.** The failure happens fifteen or thirty
seconds after anyone was looking at it, on a screen built to show a stream rather than a
result — so there is no loading spinner that fails to clear and no empty state to fall into.
Both surfaces below render *correctly* while being wrong.

**`FleetTrackerMap`** kept drawing the last positions it received, for as long as the tab
stayed open. An operator looking at a live map that has stopped updating is looking at where
the vehicles **were**, with every reason to believe it is where they are. A stationary fleet
and a frozen map are the same picture. (Its initial load had the same catch, and an empty map
reads as "nothing is being tracked" — a statement about the fleet, from a failure of the
request.)

**`GeofencingPanel`** is the sharper one, and the reason this is its own class rather than an
instance of the silent-failure one. **The display of "no alerts" is an empty list.** A poll
that has stopped produces exactly the same empty list as a fleet where nothing has happened.
There is no stale value to notice and no pin in the wrong place — *the absence is the
display*. A truck leaves its zone, the alert exists on the server, and the panel goes on
saying nothing at all.

Both clients now take an optional `onError` alongside `onUpdate`/`onAlert`, called with the
error on a failed tick and with `null` on a successful one, so a recovered poll clears its own
warning — a banner that survives recovery is one people learn to ignore, and these need to be
believed the one time they fire.

The wording is about the meaning of the display, not about the request. "Alert checks are
failing — an empty list right now means nobody knows, not that nothing has happened" is what
an operator can act on. "Poll failed" is not.

## Rule 112 — when absence is the display, absence cannot report failure

A screen whose normal state is "nothing here" has no room left to show that it stopped
working: the broken rendering and the healthy one are the same pixels. Streams, alert feeds,
live maps and empty queues all have this shape. They need an explicit health signal beside
the content, because nothing about the content can carry one.

## Class 83 — a mode that mocks half a surface (FS-488)

`userContext.ts` mocked its READ and not its four WRITES. `getUserContext` returned a fixture;
`updateUserContext`, `addUserGoal`, `updateGoal` and `deleteGoal` went to the API in every
mode. So in the demo, `ContextManagementModal` showed a context, accepted edits, and failed on
Save against a backend that is not running.

It had been that way quietly. FS-478 gave the failure a message — which turned a silent oddity
into a **visibly broken button**, and is how it was noticed at all. Fixing one thing making
another legible is the usual way this happens.

Every other client here mocks its writes: `erp.createIntegration` pushes to an array,
`notifications.createSubscription` assigns an id, `kanbanStore.moveTask` updates local state.
The convention existed and this file had adopted half of it. **A double that covers half a
surface is a double for exactly the half nobody was testing** — and worse than none, because
the half that works implies the whole.

## The count that was wrong twice, and the guard that ends it

The number of clients still lacking a real-mode test was carried by hand across several
sessions. It was written as **six**, beside a list of **seven**, when the true figure was
**eight** — `fleetTracker` had been crossed off because its *component* got a test in FS-487,
which is a different file and exercises none of the client.

Deriving it takes one line: walk `src/api/*.ts` for a `USE_MOCK` with no sibling
`.realmode.test.ts`. That is now `everyMockedClientHasARealModeTest.test.ts`, and the list is
empty — every client with a mock fork has a test that runs its real branch.

This is the fourth time in this document that a hand-carried figure drifted, and every one
drifted in the flattering direction: fewer items left, more work done. That is not a
coincidence about arithmetic. **A number nobody derives is a number that agrees with whoever
last recalled it.**

## Rule 113 — mock the whole surface or none of it

A demo mode that fakes reads and lets writes through produces a UI that displays, accepts
input, and then fails — and the failure is in the half nobody exercised, because everything
visible worked. If a client has a mock branch, every method needs one.

## Class 84 — the state between loading and failed (FS-489)

Three source sweeps cover failure-as-emptiness, and all three read one file at a time. So the
browser sweep was written to ask the question they cannot: **with every `/api/v1/` call
aborted, what does a whole page say?** It needs no backend — auth is seeded into localStorage
and requests are failed at the network layer — so it runs beside the smoke tests rather than
in the job that stands up Postgres.

It found two, and both had already been fixed for the case they were fixed for:

**`Historian`'s asset picker** reads `assetsError ? 'Asset list unavailable' : 'No assets'`.
That is FS-479's fix, and it is correct. But **react-query retries by default**, so `isError`
stays false for seconds while the retries run — and during that window `assets` is empty and
`assetsError` is false. The branch it renders for most of any outage is *"this plant has
nothing instrumented"*.

**`ErrorTriage`'s summary tiles** read `summary.data?.open_count ?? 0`. A summary that has not
arrived renders **"Open errors 0"** — on the page an engineer opens to find out whether a
deploy broke anything. That is FS-191's shape returning in a new place: *a complete,
error-free dashboard of zeros*, which is the exact defect `frontend-e2e-authenticated` exists
to catch. Zero open errors is the most reassuring lie this product can tell.

**The missing state is the same in both**: `isError` was handled, `isLoading` was not, and the
gap between them is where a retrying request lives. A three-state chain is not a style
preference — with retries on, the two-state version shows the wrong state for longer than the
right one.

### The sweep was vacuous first, and would have shipped that way

Its first version routed `**/api/**`. The frontend's own source lives in `src/api/`, and Vite
serves those modules over HTTP — so the pattern aborted the application's own JavaScript.
React never mounted, every body was empty, and **all 32 assertions passed**: a page that
rendered nothing claims no emptiness. It reported green.

`assertTheAppRendered` now fails any route whose body is under twenty characters, before any
claim about its text is made. That is the difference between a guard and a decoration, and the
only reason it was caught is that the *other* half of the same file — "does not go blank
instead" — failed on three routes and had to be explained.

## Rule 114 — a two-state read is wrong for as long as the retries last

`isLoading` and `isError` are not the same absence, and with retries enabled the window
between them is seconds, not milliseconds. A component that branches on `isError` alone shows
its not-yet-known state as a fact about the world for the whole retry window — which is most
of every outage a user actually sees.

## Rule 115 — a negative assertion needs a positive precondition

"No route claims emptiness" is satisfied by a route that renders nothing at all. Any sweep
asserting the *absence* of something must first assert the presence of the thing it is
searching — the page mounted, the file parsed, the list is non-empty. Otherwise the greenest
possible result is a total failure of the harness.

## Class 85 — the set of things that do not run, which nothing counts (FS-490)

Rule 49 is *"a suite that skipped is not a suite that passed"*, and this repository has the
near-miss on record: **"'25 passed' would have confirmed the migration against tests that never
ran the code it can break."**

Six suites in `backend/tests/` carry a module-level `pytest.mark.skipif` on credentials — SAP,
Dynamics, Dataverse ×2, Odoo, QuickBooks. Between them they are the entire vendor-facing
surface, and in the ordinary run every one of them skips. **That is correct.** A fork PR has no
secrets, and a red build for a key nobody can provision teaches people to ignore the colour.

What is not correct is that **the set can grow and nothing counts it**. A seventh suite added
tomorrow with the same marker joins a green run as a silent skip, and the honest reading of
"3,564 passed" quietly stops being honest. That is the same shape as every hand-carried figure
in this document that has drifted — and all of them drifted the same way, toward more work
done.

So the register is the claim and the test is the check on it: a credential-gated suite must be
listed, listing it names the variable that enables it, and that variable must appear in the
suite's own skip reason. Adding one now costs a line, which is the only moment anybody decides
*on purpose* that a suite may run nowhere.

**It found one immediately.** `test_erp_platform_integration_realdb.py` — 23 tests — skipped
with *"needs live Dataverse credentials (see docs/erp/dynamics-dataverse-setup.md)"*, naming no
variable at all. Its three sibling Dataverse suites all spell theirs inline. A reader of the CI
log learned that 23 tests did not run and was sent to a document to find out why.

The register also caught **me**: my first entry for the QuickBooks suite said
`INTUIT_SANDBOX_REALM_ID`, and the variable is `INTUIT_REALM_ID`. The check that the reason and
the register agree is what made the register worth having rather than a second place to be
wrong.

## Rule 116 — count what does not run, not only what does

A pass count answers "how much worked". It does not answer "how much was asked", and the gap
between those is invisible by construction: every skipped suite is a green line. Any mechanism
that lets a test opt out — credentials, markers, CI `--ignore` — needs a register that fails
when the set grows, or the suite's headline number slowly stops describing the suite.

## Class 86 — correct field name, wrong type, latent until the data arrives (FS-303)

Two sweeps already pair a response model with its table: one asks whether a declared field is
produced by anything, the other whether a produced field is declared. This is the third
direction and the quietest, because the name is right.

```python
Decimal("12.0")  ->  int field  ->  12          # validates
Decimal("12.5")  ->  int field  ->  ValidationError
```

A model declaring an integer over a numeric column is **not wrong in any way a fixture can
show**. Whole-numbered rows validate, so it passes every test, every review and every staging
run — and 500s on the first fractional row that reaches it. FS-284b caught two of these by
eye, after they had shipped.

**The defect is a property of the schema and the failure is a property of the data**, which is
why a static pairing is the only instrument that can find it early. Nothing else in this
repository is looking at the two together.

It reports **nothing today**, and that is worth writing down rather than deleting. Class 25 is
the standing warning: a sweep reported clean, recorded as deliberately unguarded, and it was
not clean — the reader had covered a seventh of its subject. So this one carries three proofs
alongside the check: that the pairing reaches fractional columns at all, that the check fires
on the defect built from a real SQLAlchemy column, and that it stays quiet on the two correct
shapes (`float` over `Numeric`, `int` over `Integer`). It was also mutation-verified against a
real model — `AlarmRuleResponse.threshold` retyped to `int` over its `Float()` column, which it
names.

## Rule 117 — a defect that needs data to appear needs a check that does not

Some faults are invisible to every dynamic test because the input that triggers them has not
occurred yet: a fractional value, a null in a column that has never been null, a string longer
than the widest row so far. Testing harder does not find these. Comparing the declaration
against the storage does, and it costs one pass over a schema.

## Class 87 — a gate that cannot fail in the dimension it is cited for (FS-307)

The schemathesis contract job connected as the postgres service container's `POSTGRES_USER`.
The official image makes that role a **superuser**, and a superuser bypasses `FORCE ROW LEVEL
SECURITY` outright — not "mostly", not "unless a policy says otherwise". Every policy in the
schema is simply not applied to its sessions.

So ~375 operations were exercised against a database with tenant isolation **switched off**,
and the gate's conformance number could not have moved if every RLS policy had been dropped in
the same commit.

Demonstrated rather than argued, on a throwaway database with `FORCE ROW LEVEL SECURITY` on
and a tenant policy in place:

```
superuser (owner)             sees 2 rows   <- both tenants
NOSUPERUSER NOBYPASSRLS role  sees 1 row    <- its own
```

**A red gate is a task. A green gate that cannot fail in a whole dimension is a belief** — and
this one was cited in the burn-down as evidence about the API's behaviour. That is the harm:
not the missing coverage, but the coverage everyone thought they had.

The role already existed. `tests/conftest.py` has provisioned a `NOSUPERUSER NOBYPASSRLS`
non-owning role since the RLS work, for exactly this reason, and the contract gate never used
it. The grant list now lives in one script both callers use, because **a second copy of a
security-relevant grant list is a second thing to forget**.

Two details that decide whether the fix survives:

- **Migrations still run as the owner**, as they do in production. The obvious way to "fix" a
  permission error after this lands is to grant the app role DDL — which makes it an owner,
  and an owner defeats a FORCE policy as surely as a superuser does. The guard asserts the
  migration step still uses the owner, so that repair is visible as a change.
- **The script verifies the role it just created**, reading `rolsuper` and `rolbypassrls` back
  out of `pg_roles` rather than trusting its own DDL. A pre-existing role of the same name with
  the wrong attributes would otherwise be used in silence.

The guard reads the workflow YAML and needs no database, deliberately: a check that only runs
where postgres is available does not run on the machine where the mistake is made.

## Rule 118 — ask what a passing gate would still pass with

Point at the property a gate is cited for and ask what would have to break for it to notice.
If the answer is "nothing in that dimension" — a superuser bypassing RLS, a mock standing in
for the boundary, an assertion that holds for both branches — the gate is not weak, it is
*mute*, and its green is being spent on a claim it never made.

## Class 88 — a private copy of the list the guard checks (FS-492)

`controls-do-not-break.spec.ts` exists because `dispatchShipment` returned 422 on every call
since the day it was written, and **no test could see it because no test clicked anything**.
Its own docstring says so.

It swept **8 of 33 routes**, from a private array with an honest comment attached: *"the routes
with the most interactive surface, not all 32 — this costs a click each."* That was a
reasonable cost decision when it was made, and it silently became a coverage claim. The
twenty-five routes it skipped were every admin page, every engine, all three analytics pages,
OEE, shop-floor, intake and NLP — three quarters of the product still in exactly the position
the file was written to fix.

**And it could not drift into view.** `everyRouteIsSwept.test.ts` compares `App.tsx` against
`e2e/routes.ts`; a private copy inside a spec is invisible to the guard that exists to catch
this. The list was moved to `routes.ts` in FS-489 for an unrelated reason — Playwright forbids
spec-to-spec imports — and this file was not looking at it.

Adding a route to the shared list therefore extended two sweeps and not the third, which is
the quiet version of the same failure: the guard was right, the coverage was wrong, and
nothing connected them.

### The cost that hid the coverage, and what removing it cost instead

Pointing it at all 33 routes made it time out — first at the original 240s, then at 396s after
the budget was made per-route. It ran **6.6 minutes** and still failed. Raising the constant
again would have bought an eleven-minute serial job whose failure is one red line naming a
list.

The loop became one test per route, and `test.describe.configure({ mode: 'parallel' })` — the
half that pays for the split, since tests in one file run serially by default. **2.4 minutes
for 33 routes, against 6.6 for 8.** Four times the coverage in a third of the time, and a
failure now names its route in the test title rather than inside an accumulated array.

The per-route split loses one thing worth keeping: each route passes trivially if it finds no
buttons, so a separate test asserts the sweep still clicks more than fifteen controls. Without
it a selector change turns thirty-three green ticks into thirty-three no-ops.

## Rule 119 — a subject list belongs in one place, and the guard must read that place

Two copies of "the things we check" drift, and the drift is invisible from either side: the
list that grew looks complete, and the list that did not looks deliberate. When a guard exists
to keep a list honest, every consumer of that list has to read the same one — a private copy
is not a shortcut, it is an exemption nobody granted.

## Class 89 — a double that is wrong at exactly the seam that is broken (FS-495, FS-497)

Two defects, one shape, both in the edge agent, both invisible for the same reason. The agent
has a 289-test suite and neither was caught, because in both cases the test substituted
something at the join where the disagreement lived.

**The live forward has never worked.** `main.py:259` builds the Kafka producer with
`value_serializer=lambda v: json.dumps(v).encode('utf-8')` and hands it to the coordinator
(`:270`). The coordinator pre-encoded and passed the bytes as the value
(`coordinator.py:334-337`), so aiokafka ran `json.dumps(b'{...}')` — **TypeError on every
message, since the day it was written.**

The double: `tests/test_edge_agent_integration.py:47-55` defines a `FakeProducer` whose
`send()` appends `value` to a list. It applies no serializer, so it accepts bytes happily.
`test_coordinator_roundtrip.py:95` passes `kafka_producer=None` and skips the path entirely.

It cost latency, not data — the message is buffered before the forward is attempted and the
backfill path serialises correctly, so everything arrived by the slow road. But the fast road
never once carried anything, and the only witnesses were a `logger.debug` line and a counter
nobody alerts on. **A path that fails 100% of the time and a path that fails occasionally were
logged identically**, which is what FS-496 corrects: the first failure since the last success
is a warning, the rest stay at debug so an offline broker does not flood the log.

**The heartbeat has always reported five zeros.** `heartbeat.py:48-52` reads `buffer_pending`,
`dead_lettered`, `dropped`, `active_collectors`, `total_collectors`. `_health_snapshot()`
returned `collectors_total`, `collectors_active` and no buffer keys. Every read has a `, 0`
default, so every field defaulted, every time.

The double: `tests/test_heartbeat.py:9-16` supplies its own `health()` dict with the *correct*
names. It is a good test of the reporter and can say nothing about the producer, because the
two were never connected in a test. **Both halves were individually right and disagreed about
the contract between them.**

That one reaches production monitoring: `backend/app/services/edge_fleet.py:69` sets
`edge_agent_buffer_pending` from that field and `alerts.yml:241` alerts on it above 5000. A
fleet backing up on disk looked idle.

### The rule the two share

A fake is a claim about the real thing. `FakeProducer` claimed "a producer accepts whatever
you give it"; the real one applies a serializer. The heartbeat test claimed "the health
snapshot has these keys"; the real one has different ones. In both cases the test passed
because the substitute agreed with the caller — which is the one party whose agreement proves
nothing.

## Class 90 — an alert that parses, and cannot fire (FS-498)

`promtool check rules` validates an expression's syntax. It says nothing about whether the
series exists, or whether it can ever cross the threshold. So `EdgeAgentBufferHigh` was
syntactically perfect for exactly as long as it was useless.

The gap is not the rule, it is the missing half of the test suite: five promtool test files
existed, covering errors, subsystems, platform, workers and security — and none covered edge.
`tests/edge_alerts_test.yml` now drives the gauge past the threshold and asserts the alert
appears, plus the three cases that must stay quiet: below threshold, exactly at it (`> 5000`
must not fire on 5000), and a blip that drains inside the `for: 10m` window.

Mutation-verified by raising the threshold to 500000 — the firing case then reports the alert
it expected and got `[]`.

## Rule 120 — a fake is a claim about the real thing, and only the real thing can refute it

When a double stands in at a boundary, it encodes somebody's belief about the contract there.
If that belief is wrong the test agrees with the caller and the defect survives every run. Make
the double do the one thing the real collaborator does that could fail — apply the serializer,
return the real key names — or the test is asserting the caller against itself.

## Rule 121 — "it parses" is not "it works", for anything declarative

Alert rules, manifests, schemas and config files all have a validator that checks form and a
much smaller number of tests that check effect. A rule that cannot fire, a manifest that
cannot apply, a schema no payload satisfies — each passes its linter. Ask what would have to
happen for the declaration to *do* something, then assert that.

## Rule 122 — when two components must agree, something has to read both

The backend knows which command action ids it dispatches. The agent knows which handlers it
registers. Both are correct about themselves, and for as long as nothing compared them the
cloud sent `model_update` to a fleet that answered `unknown_action` (FS-505). Same shape as the
truncation signals (FS-485) and the ERP connector list (FS-486): the defect is not in either
list, it is in the absence of a third thing that reads both.

The guard belongs wherever it can see both sides, which is often neither component's own test
directory. When one side is out of your lane, the pairing test is still yours to write — it
changes no behaviour and makes the gap impossible to keep missing.

## Rule 123 — a test proves the code is correct, never that anything calls it

Three edge-agent modules had passing tests, green coverage, and no production caller (FS-506).
Nothing in the ordinary signals distinguishes that from a working feature: the suite counts it,
the coverage report shows it, and a reader browsing the tree finds documentation and
assertions. This is FS-490's class — counting what does not run — one layer up from skipped
tests.

Whenever a sweep asks "is this tested?", ask the second question: **is it reached?** They are
independent, and the combination that hides longest is *tested and unreachable*.

## Rule 124 — a commented line documents an intention; it configures nothing

Four edge-agent safety switches — TLS required, Kafka SSL, explicit sources, CA pinning — were
"set" in exactly one place: a commented block headed "Production posture" (FS-508). They grep
as present. Every shipped deployment ran the permissive default, while the production overlay
set `MTLS_ENABLED=true` on the other side of the same connection.

Two consequences for detectors. First, parse the artefact — YAML as YAML, not as text — or the
sweep passes on the broken tree for the same reason the reviewer did. Second, treat *unset* as
a value the manifest chose: a switch that is neither set nor explicitly deferred with a reason
is a default nobody picked, and only a default somebody picked is safe to ship.

## Rule 125 — an unreachable path in a fully-swallowing component fails invisibly forever

The HTTP collector catches `httpx.HTTPError`, then bare `Exception`, and its poll loop wraps
the same call in a second handler (FS-507). It cannot crash, cannot restart, and cannot tell
supervision anything is wrong — so a poll that raises every cycle is indistinguishable from one
that works, and the asset just goes quiet.

Swallowing is often right at a poll boundary. What makes it dangerous is swallowing *plus* no
assertion that the happy path produces anything. The pairing to look for is a component with
broad handlers and zero behavioural tests: neither alone is alarming, and together they mean
nothing has ever confirmed the component does its job.


## Class 91 — a recovery path that only works if the work is idempotent (FS-578)

`migrate.py` executes each statement in autocommit, correctly: TimescaleDB continuous
aggregates and `add_retention_policy` refuse a transaction block. The undocumented consequence
is that **a migration failing at statement 7 has committed 1–6 and recorded no version**, so
the only recovery is running the file again, and that works only if every statement tolerates
running twice.

The static check over-reports five to one, which is why the convention went unenforced for
sixty-two files. Postgres has no `IF NOT EXISTS` for a policy, trigger or constraint, so the
idiom is `DROP … IF EXISTS` before the `CREATE` — and a text sweep sees only the `CREATE`.
Twenty-two files look wrong; four are. The difference is only visible by running them.

## Rule 126 — when a convention is documented and unenforced, ask whether the cheap check is wrong

Nobody was ignoring the rule. The check that would have enforced it reported 22 defects where
4 existed, and a guard with an 80% false-positive rate is a guard nobody adds. The reason a
written rule has no gate is often not neglect; it is that the obvious detector is unusable, and
the useful question is what a *correct* detector would cost.

## Rule 127 — a detector that must skip a case has to say so, not count it clean

Two statements in the chain cannot be retried at all — Postgres will not roll them back. The
guard records them as unchecked and asserts the set does not grow. A skipped case counted as a
pass is the same lie as an alert that cannot fire.

## Class 92 — a check scoped to a path, and the prose moved (FS-584)

Splitting a 7,239-line document into six files silently disabled three guards. Two read only
the index, found none of the sections they check, and passed over empty sets. The third names
the document in a list of prose whose citations must resolve — its entry still resolved, so
**7,100 lines of citations left the check while the file count went up**.

The comment predicting this was already in the third file, written when the delivery log moved
out of the README: *"Moving prose out of a checked document moves it out of the check unless
the scope moves with it."* Being right in a comment stopped nothing.

## Rule 128 — moving prose is a code change, and the checks that read it are its callers

Before splitting or relocating a document, grep for the path the way you would before renaming
a function. A guard keyed to a filename is a caller; it just fails by passing.

## Rule 129 — cite a section, never a line

a citation reading *defect-class-sweeps.md, lines 777–786* was written when those lines held an argument about a route
prefix. They now hold an unrelated paragraph about a provenance flag. Nothing can catch it: the
file exists, the lines exist, and only a reader who already knows what they expected to find
can tell that they are the wrong ones. A section heading moves with its text.

(Written out in words rather than in the citation's own form. The guard matches the shape, and rule 37 says the prose describing a defect gathers around the defect — a document is allowed to describe one without committing it.)

## Class 93 — a modal that catches nothing over a store that re-raises (FS-651)

Two kanban modals, 820 lines between them, held every task mutation the product has: create,
assign, unassign, approve, reject, start, complete, move, save, delete. Ten writes. Not one of
them could tell the operator it had failed.

The two halves failed differently and neither was visible:

`CreateTaskModal` called a store function that **answers `null`** on failure and logs to the
console. The modal read the answer, found it falsy, skipped the close, and returned. The
spinner stopped. Nothing else changed. A refused create and a slow one were the same screen.

`TaskDetailModal` called nine functions that **re-raise**. Its handlers were `try { … }
finally { … }` — a shape that resets the spinner and swallows nothing, because there was
nothing to swallow it with. Each rejection went to an unhandled promise, which in a browser is
a console line. On the three routes that close the modal (approve, complete, delete) a failure
at least left it open, which is a weak signal but a signal. On the six that do not — start,
move, assign, unassign, save, reject — **a rejected write and a successful one were pixel
identical.**

Both halves passed `mutationFailureIsVisible`. That sweep reads `useMutation` hooks; these are
hand-rolled `async` calls on a store. The sweep was not wrong, it was scoped — and its scope
was a hypothesis about where mutations live, which stopped being true the moment somebody
wrote one a different way (rule 62).

The reason both sat this long is the same reason: `pages/Kanban.test.tsx` mocked all five
kanban components to `() => null`. The page suite proved the page mounts them. Coverage
counted the stub. Nothing rendered a real one until FS-651.

## Rule 130 — `finally` without `catch` is a spinner reset, not error handling

`try { await write() } finally { setSubmitting(false) }` reads like care and is the opposite:
it guarantees the UI returns to rest whether the write landed or not, which is precisely the
state that makes success and failure indistinguishable. Whenever the pattern appears, ask what
the caller does with a rejection. If the answer is "the browser logs it", the operator has
been told nothing.

## Rule 131 — a store that returns `null` and a store that raises need the same call site

The two modals sat in one directory over one store and handled failure in two different ways,
because the store itself does — `createTask` catches and returns `null`, `updateTask` catches,
logs and re-raises. A caller cannot get this right by reading its own file. Both are now
routed through a single `runAction`-shaped helper per modal, so the question "what happens
when this fails" has one answer per component rather than one per button.

## Class 94 — a polled reading that cannot say it stopped arriving (FS-655)

Class 93 closed by asking what a modal does when a write fails. The carry-across is the read
side, and it is worse, because a read has no button to press: **what does a POLLED value show
when the poll starts failing?**

react-query keeps the last successful `data` across a failed refetch, and that is the right
default — a screen that blanks on every blip is unusable. But a component that destructures
only `data` cannot tell a live reading from one taken an unknown time ago, and on a *poll*
that is not a transient state. The retry runs forever, so the wrong reading stays for as long
as the endpoint is down and nothing on the page changes.

The cold-start form is the one that matters. With no data yet, `data?.count || 0` is **zero**,
and zero renders as a fact:

* **`Header.tsx`** hid the alarm badge behind `count > 0`. An alarm feed that had never
  answered rendered as a plant with **no active alarms** — in the corner of every page, on an
  industrial monitoring product, on the one indicator that must never quietly read all-clear.
* **`Alarms.tsx`** showed "Active 0", and the card beside it computes `total − count`, so it
  reported **every alarm on the page as acknowledged**. This is the page an operator opens
  because they are worried.
* **`kanbanStore`** swallowed a failed 30-second metrics poll into the console and kept the
  last figures, so an hour-old throughput, WIP and cycle time read as the current floor.

Three sites, one missing `isError` each.

`failureIsNotEmptiness` could not see any of them. It looks for a rendered *phrase* — "No
vehicles", "None found" — and these render a **number**. A confident `0` is the same lie with
better typography.

## Rule 132 — a poll turns a transient failure into a permanent wrong answer

A one-shot fetch that fails leaves a blank, which is at least a question. A poll that fails
leaves the last answer, forever, with a retry running behind it that keeps not working. When
reviewing an error path, the first question is not "is this handled" but "how long does this
state last if nobody intervenes" — and for a `refetchInterval` the answer is: until somebody
notices, which is what the missing indicator was for.

## Rule 133 — `|| 0` on a value that might be absent is a measurement invented from nothing

`data?.count || 0` reads as a safe default and is a fabricated reading. Zero is not the
neutral value for a count the caller could not obtain; it is the most reassuring possible
answer, and it is produced precisely when nothing is known. The same line also swallows a
genuine zero, so the one case where the number is true becomes indistinguishable from the case
where it is invented. `?? null` and an explicit branch, every time.

## Rule 134 — the numbers a component derives inherit the honesty of their inputs

`Math.max(0, total - (activeAlarms?.count || 0))` was written as arithmetic, not as a claim,
and it is the more dangerous of the two cards: an unavailable active count did not merely
default it to zero, it **turned the whole page into "acknowledged"**. Whenever a fabricated
default flows into a subtraction, a ratio or a percentage, look at what it computes before
deciding the default was harmless.

## Class 95 — two normalisers for one question, and the caller cannot tell which it has (FS-656)

Rule 133 said `|| 0` on a possibly-absent value is a measurement invented from nothing. The
sweep that followed found the pattern **31 times in the frontend**, and the honest result is
that almost all of them are fine — which is worth recording, because "proven clean" and "never
checked" look identical afterwards.

* Ten are `?.items || []` on a list, which is `failureIsNotEmptiness`'s existing subject.
* Three are inside `if (USE_MOCK)` blocks, where the miss is a fixture lookup rather than a
  network failure — including a **compliance score** and a **freight charge**, either of which
  would be serious on a live path and neither of which is on one.
* `Dashboard.tsx` renders `fmtNum(...)`, which answers `—` for absent, and its widget carries
  `isError`; the `|| 0` there picks a *colour* beside a number that already says unknown.
* `OEE.tsx` early-returns on `isError` before the expression can render.

**One was live, and it was in the client every page depends on.** `handleApiError` computed
`error.response?.status || 500`, so a request that never reached the server reported that the
server had answered 500.

The reason it survived is the interesting part. `src/api/errors.ts` already contains
`normalizeApiError`, which answers `status: null` and `code: 'network_error'` for exactly this
case. **Two normalisers, one directory, different contracts** — and no caller could see which one it
had. Nearly all of them read only `.message`, so nothing was visibly wrong.

I first reported that *all* of them did, from a regex matching `handleApiError(...).field`. It
cannot see a destructure, and `ComplianceAssistant.tsx` destructures `{ status, message }` and
compares `status === 503` to distinguish a RAG outage from a failed answer. Its behaviour is
unchanged — `null === 503` is false exactly as `500 === 503` was — but the trap was one caller
closer than the sweep said. The next one to write `status >= 500` would have retried requests
that never left the machine, and error triage would have attributed every network outage to a
server fault.

The crude one also could not read the backend's actual `{ error: { message } }` envelope,
which the delegation fixed as a side effect and which no test had noticed.

## Rule 135 — when a sweep comes back clean, the reason is the result

Thirty-one hits, one defect. The value of the pass is not the fix; it is that the other thirty
are now known-checked, with the reason each is acceptable written down. A sweep reported as
"clean" and nothing else is indistinguishable from a sweep nobody ran, and the next person
pays for it twice — once redoing the work, or once assuming a class was handled when it was
not. Both have happened in this document.

## Rule 136 — two implementations of one question is a defect before either is wrong

The `|| 500` was the visible half. The durable half is that a second, correct normaliser sat
beside it and callers had no way to know which they were holding — so the honest one could be
fixed forever and the UI would never benefit. Look for the duplicate before debating the
behaviour, and guard the agreement rather than the delegation: "A must call B" passes for any
delegation and fails for any honest reimplementation, which is backwards. Assert that both
answer the same thing.

## Class 96 — a gate in a workflow that branch pushes never reach (FS-657)

The previous entry ends with my own miss: a test file that was green under `vitest run` and
did not compile, because `vitest` transpiles and discards types. I recorded it as a local
process failure — run `tsc` last, not first — and then asked the obvious follow-up, which was
whether CI would have caught it.

It would have, in a workflow that does not run on the branch.

`ci-cd.yml` has carried a blocking `npx tsc --noEmit` since FS-53 and a blocking
`npm run lint` since FS-54. It triggers on `push: branches: [main]` and `pull_request`.
`quality-gates.yml` is the workflow that fires on every developer branch — `hamad/**`,
`hridyansh/**`, `htreinen`, `HARSH-CONTRIBUTION`, `alex` — and it had **neither**.

Every branch in this repository has been running with no typecheck and no lint, for as long as
both workflows have existed. The consequences were already sitting in the tree:

* my non-compiling test file, green under every job that runs on a branch push;
* **fifteen lint errors** across e2e specs, adapter tests and page tests — none behavioural,
  every one of them enough to fail the gate the moment a pull request opened, which is the
  worst moment to discover them.

The fifteen are worth reading, because seven of them were not defects at all. They are the
omit-a-key idiom — `const { alertType, ...withoutType } = WIRE` — where the discarded name is
the documentation: it says which field the test is proving the adapter cannot invent. The rule
wanted them renamed `_alertType`, which destroys the one thing the line exists to say. The
correct fix was `ignoreRestSiblings: true` in the config, not eight underscores in the tests.
**A linter demanding a change that makes the code say less is a misconfigured linter**, and
answering it literally would have been the lasting damage.

The other eight were genuinely dead: three pairs of `EMAIL`/`PASSWORD` constants left behind
when FS-452 moved authentication into a Playwright setup project, and a per-route counter made
vestigial by the file's own vacuity test.

### What the hole was hiding

Wiring the frontend checks in was the cheap half. The backend has the same arrangement —
`flake8 app --count --select=E9,F63,F7,F82` has been blocking in `ci-cd.yml` from the start,
on `main` and pull requests only — and its **first run against this branch** reported:

    app/api/transportation.py:723:30: F821 undefined name 'driver_id'

`POST /transportation/shipments/{id}/dispatch` built its reply with a bare `driver_id`. The
request body is `request.driver_id`; there is no such name in that scope. So every dispatch
raised `NameError` and answered 500.

**And a 500 is the mild reading.** `dispatch_shipment` sets the status, assigns the driver and
trailer, and **commits** before returning — the NameError fires afterwards, while the route is
building its response. The shipment really was dispatched, and the operator was told it was
not. That is the one error that makes somebody do the thing twice.

Two guards had a claim on this and neither could reach it. `tests/route_walk.py` drives every
route against a real Postgres looking for 5xx, but a generated `shipment_id` matches no row, so
the service raises `ValueError("Shipment not found")` and the route answers 400 — **the defect
is reachable only by succeeding, and the smoke test never succeeds**. And the one check that
names this exact class, by error code, ran in the workflow nobody's push reaches.

## Rule 137 — a gate that is never reached and a gate that does not exist are the same gate

This repository has now paid for the same shape three times. `develop` sat in a branch-trigger
list for months without existing on any remote, so the dev branches that *did* exist ran zero
CI. The coverage thresholds in `vitest.config.ts` were enforced by no job in either workflow —
`npm run test` is `vitest run` without `--coverage` — and had already gone false when somebody
finally looked. And now two blocking checks that only fire where nobody pushes.

None of the three announces itself. Every job is green, the gate is present in the repository,
and "we have a typecheck" is true and useless. When adding a check, the question is not "is it
blocking" but **"which pushes reach it"** — and the answer has to be checked against the
branches people actually use, not the ones the trigger list mentions.

## Rule 139 — a smoke test that only ever fails has not tested the success path

`route_walk` covers every route and looks for 5xx, which reads like complete coverage of "does
it crash". It is not: with generated inputs, most write routes reject before they do anything,
so what is proven is that the REFUSAL path does not crash. The dispatch NameError sat behind a
real shipment, a real driver and an HOS check. When a smoke test reports a route clean, ask
which branch it actually reached.

## Rule 138 — the check you skipped is the one that finds your mistake

I ran `npx tsc --noEmit`, then appended a test block, then ran only `vitest`. The order was the
whole defect: every check I ran passed, and the one I had already run was the one that
mattered. Run the compile last, after the final edit — and when a run is green, ask which
tools did not look at the thing you just changed.

## Class 97 — a parameter the endpoint reads from the query, sent in the body (FS-658)

Rule 139 said a smoke test that only ever fails has not tested the success path. The
carry-across is to ask which write routes have a success path nothing asserts — and the answer
in `transportation.py` was four, measured with a detector carrying a positive control (the
dispatch route fixed an hour earlier, which must show one success assertion or the measurement
means nothing).

One of the four was `POST /shipments/{id}/status`, the route **immediately below** the one
FS-420 fixed, carrying FS-420's exact defect.

FastAPI reads a non-Pydantic scalar with no `Body(...)` marker as a **query parameter**.
`async def update_shipment_status(shipment_id: UUID, status: str, ...)` therefore requires
`?status=`. The client posts `{ status, note }` as JSON. So **every status update answered
422**, and the two buttons that call it — "Mark Delivered" and "Cancel" on the Transportation
page — had never worked once.

Third instance of this class. FS-379 on Strategic approve/reject, FS-420 on dispatch, and now
the route twenty lines below the one FS-420 fixed. **Fixing an instance is not fixing a class**,
and the neighbouring route was never looked at.

`note` is the smaller half and worth its own line. The client sent one on every call; `Shipment`
has no note column and the service never read the field. Pydantic drops unknown fields silently
by default, so accepting the body would have made the API appear to record something it
discards. The model declares `extra: "forbid"` and the client no longer offers the parameter —
a field a caller can pass and the server cannot keep is a promise the API does not make.

### Why the server side is still full of this shape

The sweep across every router found **22 routes** taking bare scalars. Nearly all are correct
in practice, and the reason is written in the client: FS-379 and the maintenance-mode and
NLP-chat routes were each closed by moving the **frontend** onto the contract the server
already published — cheaper, and it crosses no lane boundary. `api/engines.ts` says so
explicitly.

That was the right call every time, and it means the server-side shape survives 22 times over,
each one client-edit away from breaking. The next person to write the obvious
`api.post(url, { field })` gets a 422 and no clue why.

So the guard does not demand 22 refactors in other people's lanes. It asserts the thing that
actually matters — that **the two sides agree** — and fails when a caller posts a body to a
route whose parameters live in the query.

The detector took two corrections before it was worth reading. The first excluded four FastAPI
markers and flagged 48 sites, including a correctly-declared `Header(...)` webhook signature.
The second matched routes by their last path segment, so `/insights/activations/{id}/reject`
was reported as a defect in `/strategic/recommendations/{rec_id}/approve` — two unrelated
routes sharing one word.

## Rule 140 — fixing the caller closes the instance and preserves the class

Three times this defect was closed by correcting the client, each time for a good reason: the
route belonged to another lane, and moving the caller needed no agreement. The instance really
was fixed. But the server still publishes a contract nobody would guess, in 22 places, and the
next caller written against it fails the same way. When the cheap fix is on the other side of
the seam, record what the expensive one would have been — and guard the seam, since that is
what the cheap fix leaves undefended.

## Class 98 — a scope that stops at a lane boundary, and nothing records where (FS-659)

Rule 140 said fixing the caller closes the instance and preserves the class. The carry-across
is to ask where else this repository fixed one side of a seam — and the codebase answers in its
own comments. Six of them admit a one-sided fix; three are distinct sites, and two were already
closed by the previous guard.

The third is `IdempotencyMiddleware`. It dedupes retried mutations by prefix, and `main.py`
says the scope stops on purpose:

> Correlation/kanban/intake/OTA/auth/RBAC surfaces are deliberately excluded — they are owned
> by other lanes.

That is the right call, and it leaves **167 of 208 mutating routes** outside the middleware
with nothing distinguishing the ones that were considered from the ones nobody has looked at.
A new mutation surface added to a protected lane lands outside protection in silence: the
middleware does not fail, it simply does not apply.

The guard asserts nothing about which surfaces *should* be protected — that is each lane's
decision. It asserts that every mounted mutation surface is **accounted for**: protected, or
named with the reason it is not. Thirty-one are named. "Lane ownership" is a reason;
`/api/v1/api-keys` carries the sharpest one — it **must not** dedupe, because every call is
required to mint a distinct key, and a replay guard there would be the defect.

### A sweep that came back clean, and why it was worth running

Three routers mount under `/api/v1/fleet` and two under `/api/v1/compliance`, so a route
declared twice would be shadowed by whichever mounted first — FastAPI resolves first-match-wins
and says nothing. **524 route-methods, zero collisions.** Recorded because a shared prefix
looks exactly like a collision waiting to happen, and now nobody has to wonder.

## Rule 141 — before writing a walker, look for the one that already exists

Three detectors failed in a row on the way to this entry. A prefix matcher whose direction was
inverted, so `/api/v1/assets` "covered" `/api/v1` and the whole tree read as protected. A
module name taken as `name.split(".")[-1]`, which is `"router"` for every `include_router` call.
And a hand-rolled route walk that reported **six routes** for an app with 524, because
`app.routes` holds lazy `_IncludedRouter` entries whose children carry RELATIVE paths.

That third one is the lesson. `tests/_route_tree.py` has existed the whole time and its
docstring opens by naming that exact pitfall. The cost of not looking was two wrong answers,
and the second of them — a clean tree — is the kind that gets believed.

Grep for the thing you are about to build before building it. In a repository with 140 rules
about detectors being wrong, the odds are good that somebody has already been wrong in this
particular way and left the fix behind.

## Class 99 — a field the schema declares, the response returns, and the route drops (FS-660)

Rule 139's question asked of a second file. `yard.py` is in far better shape than
`transportation.py` — eleven of its twelve mutating routes have a test asserting a 2xx. The
twelfth was `POST /checkpoints`.

`YardCheckPointCreate` declares `inspector_id` and `metadata`. `YardCheckPointResponse`
returns them. `YardCheckPoint` has an `inspector_id` column and a `meta_data` column. **The
route passed neither to the service.** Both were accepted, discarded, and echoed back as
`null` and `{}` from columns that stayed empty — a complete round trip that loses the value in
the middle and reports success at both ends.

`checkpoint_type` is gate_in, guard_shack, weigh_station or gate_out, and `inspection_status`
is passed/failed/pending. On a weigh-station or guard-shack checkpoint the inspector **is** the
audit trail: the record says an inspection happened and cannot say who made it. A failed
inspection with no inspector is a finding nobody owns.

### The same class, resolved the opposite way, an hour apart

`POST /shipments/{id}/status` accepted a `note` the client sent on every call, and `Shipment`
has no note column — so the fix was `extra: "forbid"`, refusing the field rather than appearing
to record it. Here the column exists and was simply not wired, so the fix is to store it.

Two opposite corrections for one shape, and the discriminator is not how harmless the field
looks. **It is whether the field has somewhere to land.** Ask that first; the answer decides
which fix is the honest one.

## Rule 142 — a declared field that is dropped is worse than one that is refused

A refused field is a 422 the caller can read and act on. A dropped field is a 200, an echo of
the default, and a column that stays empty — the caller has every reason to believe the value
was kept. Both ends of the round trip report success and the middle loses it. When a schema
declares a field, follow it to storage before assuming the wiring exists; `metadata` and
`inspector_id` were declared on the way in, declared on the way out, and connected to nothing.

## Rule 143 — when a boolean is stored, find the field that bounds it

Three instances of one shape landed in a single day, and only the third made it obvious.

| route | stored | dropped |
|---|---|---|
| `POST /yard/checkpoints` | an inspection happened | **who inspected** |
| `POST /yard/trailers/checkin` | which seal | **whether it was intact** |
| `POST /transportation/carriers` | certified, insured | **until when** |

Every one keeps a flag and discards the field that says what the flag is worth. A certification
with no expiry, a seal with no status, an inspection with no inspector: each reads as a positive
claim that cannot be checked, and each is the more reassuring of the two possible readings.

The carrier case is the one to remember, because **the reader already existed and already
depended on the dropped field**. `get_carrier_compliance` computes

    is_valid = certified AND expires_at AND expires_at > now

so a NULL expiry makes it false. Every carrier created through the API reported its C-TPAT and
its insurance **invalid**, whatever the caller sent, having been told 200 on the way in. Not
merely incomplete data — a wrong answer computed from it.

The habit that catches this: whenever a handler passes a boolean, look for the neighbouring
field that qualifies it — an expiry, a status, an actor, a timestamp — and check it goes too.
The pair is almost always adjacent in the schema and split by the call.

## Rule 144 — assert the round trip through the reader, not the hand-off

`assert kwargs["ctpat_expires_at"] is not None` would have passed for a value the compliance
check still could not use — a string in the wrong shape, a naive datetime, a date the comparison
rejects. The test that matters runs the **reader's own expression** over what the writer stored:

    is_valid = stored["ctpat_certified"] and stored["ctpat_expires_at"] \
               and _as_utc(stored["ctpat_expires_at"]) > now

and its companion asserts an expired certificate still reads expired — because a fix that makes
everything valid is worse than the defect it replaces.

## Rule 145 — read the reader before deciding which way a dropped field is wrong

Class 99 has two fixes and they are opposites: wire the field through, or take it off the
schema. Three routes settled it three different ways, and in every case the answer came from
reading what consumes the field — never from how the field looked.

**Wire it.** `POST /carriers` dropped `ctpat_expires_at`, and `get_carrier_compliance` computes
`certified AND expires_at AND expires_at > now`. `POST /drivers` dropped four HOS figures, and
`check_compliance` refuses to assess a driver without them. Both had readers already depending
on the dropped value, so both were wrong answers rather than absent data.

**Take it off the schema.** `POST /driver-wait-times` drops `detention_charge`,
`demurrage_charge`, `total_wait_minutes` and four more — and `close_driver_wait_time` **computes
every one of them** at checkout from the timestamps and the rates. Dropping is correct here, and
honouring them would be worse than the defect: an operator could post their own detention charge
on create and the system would bill it. The lie is the schema's, for accepting them.

The discriminator is not severity, plausibility, or whether the column exists — the wait-time
columns all exist. It is: **does something else already produce this value?** If yes, the
schema should not accept it. If no, and something reads it, the handler must pass it.

## Rule 146 — a field name is not a field; check the module before believing the reader

The sweep that found these ranked routes by "has a reader" and its first answer was mostly
wrong. `approved_at` was reported read by `kanban.py` — a *task's* approval, nothing to do with
a freight charge. `duration_seconds` by `dashboard.py` and `alarm_rules.py`, `priority` by
`data_shedding.py`. Common column names appear on a dozen models, and matching `\w+\.field`
finds all of them.

The signal that survived was **same-module readers**: `total_distance_miles` read by
`transportation_management.py` for a route created in `transportation.py`, the wait-time figures
read by `yard_management.py`. Third name-collision false positive this week, after
`/insights/activations/{id}/reject` reported as a defect in `/strategic/recommendations/{id}/
approve`, and a tail-match that conflated two unrelated routes. Anchor on the module, not the
name.

## Class 100 — two fabricated defaults compounding into a billed figure (FS-665)

Rule 133 said `|| 0` on a possibly-absent value is a measurement invented from nothing. That
sweep ran over the frontend. Running it over `app/services/` finds ten numeric fallbacks, of
which most are harmless — sort keys, a peak-hour range the pattern misread — and two are in the
same call chain:

    get_shipment_costs:   distance = route.total_distance_miles if … else 500.0
    calculate_linehaul:   rate_per_mile = rate_per_mile or 2.50

Neither knows about the other, and neither reports that it fired. A shipment with no route and
no contract rate is billed **500 invented miles at an invented $2.50** — quantified rather
than asserted:

    linehaul        $1,250.00
    fuel surcharge  $   83.33
    total           $1,333.33

and the endpoint returns `distance_miles: 500.0`, which the Transportation page renders as
"500 mi".

**A fabricated rate and a contracted one at the same value produce byte-identical results**, so
no caller can distinguish them. That is what makes the number dangerous rather than merely
wrong, and it is the property a fix has to remove.

Why each survived is worth recording, because neither looks careless in place. The 500 sits
under a long correct comment about a Decimal/float `TypeError` — a real fix, beside which the
fabrication went unremarked. The 2.50 is labelled *"Default rates if not specified"*, which is
true and says nothing about the result being billed.

Not fixed here: `linehaul.amount` and `total_cost` are non-optional floats, and answering 0 for
an unknown distance fabricates a cheap shipment exactly as 500 fabricates an expensive one.
There is no honest number — the endpoint needs to be able to say "not estimated", which is a
contract change and a decision about what the figure means. Pinned as a passing test that
states the amount, so the finding lives beside the code rather than in a commit message.

## Rule 147 — defaults compound, and no single site looks wrong

Each of these two literals is defensible alone: a nominal distance for an unrouted shipment, a
list rate for an uncontracted carrier. Neither function can see the other, so neither can know
it is the second guess in a chain. The damage is the product, and the product is invisible from
either site.

When a sweep finds fabricated defaults, do not rank them individually — **follow the call
chain** and ask what the caller does with the result. Two three-line defaults produced a
four-figure invoice that no reader of either function would predict.

## Rule 148 — turn your own regression into the guard that would have caught it

An hour after shipping `temperature_zones=temperature_zones or {}` on a column declared
`Column(JSON, default=[])`, the sweep for that shape found **eighteen container defaults and
zero other disagreements**. The tree was clean; I was the defect.

That is the argument for the guard rather than against it. The failure mode is a 500 **on the
success path only** — the wrong container is stored, the response model refuses to serialise
the row, and `route_walk` cannot see any of it, because with generated inputs a create rejects
before it ever reaches the response (rule 139). What caught mine was a real-database test in a
file I had not touched, in a run I could easily have skipped as unrelated.

A bug you have just made is the best-specified guard you will ever write. You know the exact
line, you know why the existing checks missed it, and you can use the line itself as the
positive control — `test_the_pattern_matches_the_line_that_caused_this` asserts the detector
flags the literal text that shipped, and asserts the column still declares a list so the
control cannot go stale silently.

The corollary is the harder half: **write it when the sweep comes back clean.** Zero other
instances is exactly when the guard feels unnecessary and exactly when it is cheapest to add.

## Rule 149 — when a fix trips a guard, ask whether the premise broke or only the string test did

Widening `ShipmentUpdate` so a shipment's origin could be corrected failed a guard I had
written days earlier: it asserts that **every** declaration of `origin` in the backend schema
reads `Dict[str, Any]`, and the new one reads `Optional[Dict[str, Any]]`.

Two readings, and they lead opposite ways. *The guard is right and the fix is wrong* — but it
isn't: the guard exists because five entries sat in a ratchet asking "does the backend send
`contactEmail`" of a field the backend contracts no keys for, and an **optional** untyped dict
contracts no keys either. The premise is intact. *The guard is noise, loosen it* — that is how
a guard dies, one accommodation at a time, until it asserts nothing.

The third reading is the right one: the premise is the property, the `startswith` was only its
spelling. So the repair strips exactly one `Optional[...]` wrapper and nothing else, carries
the reason in a comment naming the fix that provoked it, and was mutation-verified in the
direction that matters — `Optional[Location]` still fails, because that is a field that has
gained a real contract and the exemption would then be hiding debt.

A guard written against one spelling of a type will meet the second spelling eventually. Name
the property it is checking; do not widen the pattern until it stops complaining.

## Rule 150 — `git checkout <file>` to undo a mutation test throws away everything uncommitted in it

Immediately after: mutation-verifying rule 149's repair meant editing `schemas.py`, checking
the guard failed, and reverting. I reverted with `git checkout app/models/schemas.py`, which
does not undo *the mutation* — it restores the file to **HEAD**, and the entire FS-671
widening, twenty-six fields across three schemas, was still uncommitted in it.

It vanished silently. The mutation test reported exactly what I wanted to see, and the fix it
was verifying no longer existed. The next command I happened to run was `git status`, which is
the only reason this cost minutes rather than a confused re-derivation later.

A mutation test is a deliberate temporary edit to a file you are actively changing, which makes
it the worst possible place to reach for a HEAD-restoring command. Mutate a copy, or `git
stash` first, or re-apply from the diff still on screen — and run `git status` after any
revert, because "did my work survive that" is one command and noticing at commit time is luck.

## Rule 151 — a validation block that cannot run is a defect report someone else already filed

`update_asset` opens with a tenant-scoped check: if the caller sent `workcell_id`, look the
workcell up **within the caller's organization** and 404 if it belongs to somebody else. It is
the same cross-tenant check `create_asset` performs, written out in full — the scoped `select`,
the `scalar_one_or_none`, the explicit 404.

`AssetUpdate` declares no `workcell_id`. The condition has always been False.

So the product cannot move an asset between workcells — a sensor registered against the wrong
line stays there for the life of the row — and the file *looks* like it supports exactly that.
The dead branch is what separates this from a missing feature. A feature nobody built has
nobody's intent behind it and no artefact to find; this had a design decision (scope the
lookup, 404 rather than 403) sitting unreachable in the handler, which is a note from a
previous developer saying what the endpoint was meant to do.

Read the branch before deleting it. The instinct on finding unreachable code is to remove it,
and here that would have converted a defect with evidence into a missing feature with none.

## Rule 152 — mutation-test the justification, not just the guard

Two claims went into this fix. Both were false, and the only thing that said so was running the
mutation and watching nothing fail.

*"Adding a foreign key to an Update schema without the create path's existence check turns a
bad id into a 500."* Removing the check left all five behavioural tests green. `core/errors.py`
already maps a foreign-key violation to a 400 reading *"Reference in 'asset_type_id' does not
exist in 'asset_types'"* — more specific than the message my copy produced. The check was
deleted, and the test that was written to pin it now pins the platform's handler instead.

*"This test proves the workcell lookup is tenant-scoped."* Deleting
`Workcell.organization_id == org_id` also left all five green, because RLS hides the other
tenant's workcell from that session anyway.

A mutation that does not fail is not a formality you have discharged. It is your stated reason
turning out to be wrong, and there are only two honest responses: change the code, or change
the claim. Keeping both — a redundant check plus a comment explaining a danger that does not
exist — is how a codebase accumulates defences against imaginary things while the real ones go
unguarded.

## Rule 153 — a control that another control shadows can only be held statically

The workcell tenant predicate is not redundant. RLS holding depends on the database ROLE, and a
connection with BYPASSRLS turns the same request into a genuine cross-tenant write — the
argument `create_dock_door` already makes a few files over, about the same pair of controls.

But it cannot be observed. While RLS is also blocking, no behavioural test can tell a handler
that scopes its lookup from one that does not, and the mutation above proves it: the suite is
green either way.

Defence in depth is precisely the situation where each layer is individually invisible. That
makes "assert the predicate is present in the source" not a weaker substitute for a behavioural
test but the only test available — and it should say so, in the test, so the next reader does
not delete it as a tautology or trust it as proof of behaviour. Both files here now name which
control they actually hold.

## Rule 154 — read the runner's own output, not only the pass count

The frontend suite finished **1,056 passed**, and underneath it, in the same block as the
timings, **`Errors 1`**.

Nothing had failed. An unhandled rejection escaped during a kanban test, `vitest` noticed, and
reported it in a place a green run trains you not to read. It had been there for as long as the
test had.

The pass count summarises what you thought to assert. The error line is what the runtime
noticed without being asked, which makes it strictly more informative — it is the only part of
the output that can tell you about a failure mode you did not think of. A run that is green
except for a line nobody reads is exactly where the next real one will sit unnoticed.

## Rule 155 — `() => Promise<void>` is assignable to `() => void`, and that is where rejections go

`KanbanBoard.handleDrop` is `async`. It is passed to `KanbanColumn`'s `onDrop`, declared
`(columnId: string) => void`, and called from a DOM drop handler that discards the return
value. TypeScript permits this assignment deliberately — a caller that ignores a return value
should not care that one exists — so the compiler has nothing to say, and the rejection has
nowhere to go.

What makes it worth a rule rather than a fix is the comment that sat above it: *"the error
still propagates to the caller."* Written in good faith, plausible on the line, and false —
there is no caller, only an event dispatcher. The claim survived because nobody traced the
prop through the child component's type, and a claim about error propagation is exactly the
kind that is never tested, because testing it means asserting on something invisible.

When a handler is async, find who awaits it before believing anything about where its failure
goes. If the answer is "a JSX prop", the answer is nobody.

## Rule 156 — a scripted bulk edit needs a per-file compile check, not a satisfying diff

Migrating ten `create_task` sites meant inserting `from app.core.tasks import spawn` into eight
files. The script placed it after "the last import line in the first eighty", which in
`workers/ingestion.py` was a line **inside** a multi-line `from app.services.alarm_rules import (`.
The file stopped parsing.

Nothing said so. The script printed `patched` eight times and exited zero. The tests I would
normally have run next import that module, so they would have caught it — but what actually
caught it, first, was the **new guard's own AST walk crashing** with a `SyntaxError` naming a
line I had never looked at.

Seven of eight files were correct, which is precisely the ratio that makes a bulk edit feel
finished. `ast.parse` on each touched file costs a second and answers the only question that
matters before any test runs: is this still Python.

## Rule 157 — carry a class across runtimes, not just across files

Twenty minutes after fixing an unowned promise rejection in the browser, the useful question
was not *"where else in the frontend?"* — it was *"what does this look like in Python?"*

The answer is `asyncio.create_task(coro)` with the result discarded: the event loop keeps only
a weak reference, so the work may be collected mid-flight, and an exception inside it is never
retrieved. Ten of the twenty call sites in `app/`, including one fired **per request** on the
edge ingest path. The same defect — a failure whose owner is nobody — in a different language,
with a different symptom, and no shared code between them for a grep to find.

The carry-across method usually moves sideways: same shape, next module. It moves just as well
across a runtime boundary, and that side is where nobody has looked, because it is somebody
else's language and the previous fix left no trace there to grep for.

## Rule 158 — after finding the shape, ask per site: which thread calls this?

The discarded-`create_task` sweep (rule 157) crossed into the edge agent and found six sites.
Reported as a set, they all look the same: *a task nobody holds, which may be collected
mid-execution.* A hazard. Worth fixing, not urgent.

Then, per site, *who calls this method?*

* `paho.mqtt` with `loop_start()` runs the client on its own network thread and calls
  `on_message` from there.
* `watchdog`'s `Observer` dispatches `on_created` and `on_modified` from its own thread.

`asyncio.create_task` on a thread that is not running the loop does not schedule anything — it
**raises** `RuntimeError: no running event loop`. In `MQTTCollector._on_message` that raise
lands in the method's own `except Exception` and is logged as `mqtt_message_handler_error`. So
every reading from the agent's flagship collector was being dropped, and `orca_file`, a
registered collector type, could not process one file.

The other three sites really were only hazards: asyncua invokes its handler on the agent's own
loop, and the adapter already handled the missing-loop case by hand.

The structural sweep finds candidates. Only the call path separates the theoretical from the
live, and a report of six equal hazards would have buried the three that were costing data.

## Rule 159 — a test for threaded code that does not use a thread proves nothing

The first version of the guard called `_on_message` directly from the test's own coroutine. It
passed — against the broken code — because a test coroutine runs *on the loop*, which is the
one place `asyncio.create_task` works.

The defect is not in the function. It is in the relationship between the function and the
thread that calls it, and a test that supplies the wrong thread has quietly replaced the
condition under test with a friendlier one. It reads like a real reproduction, produces a green
tick, and certifies the bug.

Reproduce the *conditions*, not just the call. For anything a third-party library dispatches —
paho, watchdog, a driver's callback, a signal handler — that means a real `threading.Thread`,
and the test above keeps a two-line `_call_off_loop` helper so there is no way to forget.

## Rule 160 — excluding a file to suppress self-matches suppresses its real uses too

The question was: which write schemas does nothing reference? Searching the whole tree answers
"none of them" — every class matches its own `class X(BaseModel):` line. The obvious fix is to
search everywhere *except* `schemas.py`.

That reported three unused schemas. Two were wrong, and the reason is the same for both:
`class AlarmResponse(AlarmCreate)` lives in `schemas.py` too. Inheritance is a use, it is
frequently the *only* use, and it is exactly the kind that lives beside the definition.

Exclude the **definition**, not the file. Parse the module, collect every name it references,
and subtract only the class statement's own name. It is four more lines than the file-level
exclusion and it is the difference between one real finding and three, two of which would have
sent someone deleting live code.

## Rule 161 — a schema with no caller is a design decision that was written down and dropped

`DataCorrelationUpdate` had eleven fields' worth of intent behind three declared, sat in
`schemas.py`, and was referenced by nothing. Meanwhile `PUT /correlations/{id}` — the route it
so plainly belonged to — declared three bare scalars, which FastAPI serves as query parameters,
so a client sending the obvious JSON body got 200 and no change.

This is not dead code in the usual sense. Dead code is something that was live and got
orphaned. This was never wired: someone designed the update contract, wrote the model, and
stopped. The model is the only surviving record of what the endpoint was meant to accept, and
to the next reader it looks like a promise the API already keeps.

Sweeping for it is cheap — write schemas, minus everything any module references — and the
finding is unusually actionable, because when the route exists you can tell from the file
whether the answer is "wire it" or "delete it". Where you cannot tell, name it in a register
with the reason, which is what `TruckAssetCorrelationCreate` got: a table with five
relationships, no reader, no writer, and a question for whoever designed it.

## Rule 162 — a detector that names ninety-five defects in a tree with five is not a first pass

The question was: which entities can be created and never updated? The obvious detector walks
route paths — every collection `POST` should have a sibling `PUT`.

It reported **95 of 123 POSTs**. Most POSTs are actions, not entity creation: `/auth/login`,
`/engines/cloud/flush`, `/data-retention/enforce`, `/alarms/acknowledge-all`. And it reported
`POST /api/v1/assets/` as unupdatable next to `PUT /api/v1/assets/{id}`, because one has a
trailing slash and the other does not.

The instinct is to tune: strip trailing slashes, add a denylist of action verbs, exclude paths
under `/auth`. Every one of those is a heuristic that will itself need calibrating, and a
denylist of verbs is a list somebody has to maintain against a growing API.

The fix was a different join. Pair by **schema**, from the OpenAPI document: find the operation
whose request body is `XCreate`, find the one whose body is `XUpdate`, require that if the
first exists so does the second. There is no heuristic in it — an action endpoint has no
`*Create` model, so it never enters the comparison — and the answer came back as five, one of
which my own hand-written summary of the problem had missed.

When a detector's output is mostly noise, look for the join that makes the question exact,
not the filter that makes the noise smaller.

## Rule 163 — `head` truncates evidence, and truncated evidence reads like a complete answer

    grep -rn "TruckAssetCorrelation" app/ | grep -v "models/schemas.py" | head -6

Six lines came back, all from `db/models.py`. I concluded the entity had no reader and no
writer anywhere, wrote that into a register entry with a reason, and shipped it in a delivery
log.

The class definition and its five `relationship()` lines are exactly six lines.
`logistics_correlation_engine` reads the entity twice and writes it once, and none of that was
ever displayed. The output did not look truncated — it looked like a short, clean answer to a
narrow question, which is the most convincing kind of wrong.

`head` is for sampling a large result. *Does anything use this?* is not a sampling question:
the informative part is the tail, and the whole point is whether it is empty. Count first
(`| wc -l`), or drop the limit. The correction, once made, made the decision easier rather than
harder — the entity is derived and never posted, so the create schema could simply go.

## Rule 164 — widening a schema whose handler does not use `exclude_unset` reintroduces the last bug

FS-671's fix was mechanical because every update handler in this codebase does the same thing:
`model_dump(exclude_unset=True)` and `setattr`. Add a field to the schema and the handler
applies it, untouched when the caller omits it.

`update_task` does not do that. It hand-writes an `if x is not None` block per field, because
it builds an activity-log changelog as it goes. Adding twelve fields to `TaskUpdate` alone
would have left all twelve **declared, accepted, validated and silently dropped** — which is
precisely FS-676, the defect fixed two commits earlier, recreated by the fix for FS-671.

The mechanical change is only mechanical where the handler is generic. Read the handler before
widening its schema, and if it enumerates fields by hand, the schema edit is the smaller half
of the work.

## Rule 165 — assert the denominator, not just the absence of findings

A sweep that finds nothing wrong and a sweep that examined nothing print the same thing.

The singleton-attribute guard nearly shipped in the second state. Its detector resolves
`app.services.*` modules with `importlib` to get the real objects, and during its own mutation
test it was run as a **script file** rather than through stdin. Python puts a script's own
directory on `sys.path`, not the working directory, so every import raised
`ModuleNotFoundError`; the `except Exception` that exists for genuinely unimportable modules
swallowed all of them; the local name map stayed empty; zero of 211 accesses were checked; and
the output read `MISSING []`.

Nothing about that output looks wrong. It is the same string a healthy tree produces, from a
detector that has been blindfolded.

Every guard that resolves something at runtime — imports, reflection, a database lookup, a
parsed file — needs an assertion about **how much it examined**, separate from what it found.
`test_the_sweep_examined_something` fails if fewer than a hundred accesses resolve, and it is
the most important test in that file.

## Rule 166 — a mutation that produces no failure is the detector confessing

The vacuity above was undetectable in the passing run. What exposed it was putting the real bug
back — `broadcast_to_org` for `broadcast_to_organization` — and watching the detector report a
clean tree anyway.

That is the most informative thing a mutation test does, and it is not the thing it is usually
run for. The expected use is confirmation: the guard catches the defect, so the guard works.
The valuable use is the opposite result — silence, which says the guard was never looking at
all, and which no amount of reading the code would have revealed.

Mutate the **original line**, not a synthetic example. A constructed case can be crafted, often
unconsciously, to suit the detector you just wrote; the line that actually shipped cannot. And
when the mutation is silent, the finding is about your detector, not about the tree.

## Rule 167 — ask the compiler before writing the detector

The question: can a nullable value reach `new Date(x)` and render `12/31/1969` to a user?

Three attempts. A name-based pass gathered every optional field name from `types/` into one
set and reported **eighteen** unguarded sites — all artefacts, because `timestamp` is optional
on one model and required on `TelemetryPoint`, and a single global set cannot tell them apart
(rules 160 and 162, for the third time). A TypeScript compiler-API pass walked every
`new Date(x)` in the program, resolved each argument's type through the checker, and reported
**zero of 236** — the correct answer, arrived at properly, except that its positive control
never fired, so the zero was not yet worth anything.

The check that settled it took one command:

    // src/__probe.ts
    export const probeA = (d?: string) => new Date(d).toLocaleDateString();

    $ npx tsc --noEmit
    error TS2769: Argument of type 'string | undefined' is not assignable ...

`strict: true` makes the whole class a compile error, and the typecheck is a blocking gate.
There was nothing to sweep, and the two detectors were re-implementations — with worse
calibration — of an analyser already in the repository and already wired into CI.

When the property you are about to detect is one the type system, the linter, or the database
already enforces, borrow its answer first. Plant the defect and see who complains. If nobody
does, then write the detector.

## Rule 168 — mutate both ends of a contract, not just the side you were looking at

`background_tasks.add_task(broadcast_task_update, org, event, payload)` is a contract with two
ends. It breaks if the **call site** gains an argument, and it breaks identically if the
**target** gains a required parameter. Same failure, opposite edits.

The natural mutation is the one you were thinking about while writing the guard — here, the
call site, because that is the line the guard reads. Testing only that direction leaves the
other unverified, and the other is the likelier one in practice: adding a parameter to a
function feels like changing *the function*, and the fifteen places that schedule it are not
on screen at the time.

Both were run. Both fail the same assertion, which is the answer you want — a guard that
watches the relationship rather than one of its participants.

The general form: when a check asserts that two things agree, mutate each of them separately.
If only one direction fails, the guard is pinned to one side and will be looking the wrong way
when the other moves.

## Rule 169 — "untested" and "untestable here" look identical in a coverage report

Thirteen of 251 mutating routes are named by no test. Four are in this lane, and they are not
the same kind of gap.

`POST /commands/cancel/{command_id}` and `POST /shop-floor/postings/drain` were simply never
driven. Nothing stopped anyone; the success path just had no test, which is where
`broadcast_to_org` lived until something happened to execute it.

`POST /bulk/alarms/acknowledge` and `POST /bulk/kanban/tasks/{operation}` create a
Redis-tracked job as their first act, and this harness has no Redis. Every attempt to drive
them ends in a 503 before the interesting code runs. That is a property of the harness, not a
lapse.

A coverage report shows four uncovered routes and cannot tell you which two are which. So the
next person spends an afternoon rediscovering the difference — and, worse, may read all four as
equally neglected and lower their opinion of the suite accordingly.

Write it down where the tests are, name the reason, and pin whatever *is* reachable. Here the
synchronous validation runs ahead of the job store, so the argument checks are testable even
though the job is not; and the 503 itself is worth an assertion, because the handler catches
`Exception` broadly and a real bug inside the job store would reach the caller wearing the same
message as an outage.

## Rule 170 — a test that asserts on a random draw is flaky by construction

`geotab_service.get_exceptions` fabricates `range(random.randint(0, 10))` rows. Zero is a legal
draw, about one time in eleven. The provenance test asserts `rows` is non-empty before checking
that each row is stamped `simulated: true`, so once every eleven runs it failed for a reason
with nothing to do with provenance.

The tempting repair is to drop the emptiness assertion — the test is about stamping, after all,
and an empty list has no unstamped rows in it. That is exactly why it is wrong: *every one of
zero rows carries provenance* is vacuously true, so the test would go green permanently and
stay green through any regression. A flaky test converted into a vacuous one is a downgrade
disguised as a fix.

Seed the generator, say which seed and what it draws (`seed 0` draws six), and the test keeps
both its determinism and its teeth.

## Rule 171 — when an unrelated test fails, read its source before reaching for `git stash`

The full suite failed on a geotab provenance test. Nothing in this work touched geotab, so the
natural move was to stash the working tree and re-run. It passed.

That looks like proof the working tree caused it. It is nothing of the kind: a test that fails
one run in eleven passes the other ten, and stashing had merely bought a fresh draw. Following
that evidence would have meant hunting a regression that did not exist, through changes that
were not responsible, with a "reproduction" that confirmed the wrong hypothesis nine times out
of ten.

Bisecting is the right instinct for a deterministic failure and an actively misleading one for
a flaky test — and the two are indistinguishable from the outside. What separates them is
reading the assertion and the code under it, which took about ten seconds here and pointed
straight at `random.randint(0, 10)`.

## Rule 172 — some classes are not statically sweepable, and saying so is a result

A standing plan item lists twelve non-null assertions on nullable network fields as a defect
class worth closing. Driven through the TypeScript checker: 27 assertions, 24 whose operand
type genuinely includes `null` or `undefined`, **zero defects**.

Each of the 24 is guarded somewhere the narrowing cannot reach:

    carriers.filter(c => c.insuranceExpiry && …).map(c => … c.insuranceExpiry! …)
    doc.s3Key && <Button onClick={() => link.mutate(doc.s3Key!)} />
    rec.approvedAt || rec.rejectedAt ? fmt(rec.approvedAt || rec.rejectedAt!) : '—'

A `filter` does not narrow the `map` that follows it without a type predicate. A closure
discards narrowing because it may run later. A short-circuit chain never evaluates the branch
that would be undefined. In all three the `!` is the author correctly telling the compiler
something the compiler cannot see.

A detector keyed on "operand type is nullable" therefore reports 100% false positives here.
Making it useful means modelling narrowing across `filter`/`map`, closure capture and
short-circuit evaluation — reimplementing TypeScript's control-flow analysis, and then
exceeding it, to find a class that currently has no members.

The right output is not a guard. It is a written record that the class was examined, what the
answer was, and why nothing was built — otherwise the item stays open forever, and the next
person to reach for it builds the noisy version and spends a day dismissing its output one site
at a time.

## Rule 173 — key the guard on the property, not on the API the defect happened to use

FS-675 found that MQTT and the file watcher lost every reading, because they called
`asyncio.create_task` from a thread that was not running the loop. The guard it produced sweeps
for discarded `create_task` calls.

`sparkplug_b.py` registers a paho callback and calls `loop_start()`, exactly like `mqtt.py`. It
is the same shape, the same hazard, the same seam — and the guard cannot see it, because that
file delivers through `run_coroutine_threadsafe`. It happens to be correct. Nothing in the
sweep would have said so if it were not.

The defect was never *"a `create_task` in the wrong place"*. It was *"a driver thread calls back
into us"*, and `create_task` was merely the API two of the three files reached for. A guard
keyed on the accident finds the instances you already know about and is blind to the class.

The check now looks for the thread markers — `loop_start(`, `Observer(` — and requires that any
file containing one captures the loop in `start()` and delivers across the boundary by some
means. A fourth such collector cannot arrive silently, whichever API its author prefers.

## Rule 174 — before building the fix, grep for someone who already built it

`sparkplug_b.py` opens with:

    paho delivers messages on its own network thread, so decoded readings are handed to the
    asyncio loop via ``run_coroutine_threadsafe``.

and its handler is documented *"paho callback (network thread) -> decode -> deliver on the
event loop"*. That is FS-675's fix, written out, with the reasoning, in a sibling file — while
`mqtt.py` two entries earlier in the same directory was dropping every message.

FS-675 instead reasoned from first principles, built a helper, and migrated six sites. The
result is better — `spawn` retains the future and logs the no-loop case, which the hand-rolled
version did not — but the shortest path to it was `grep -rn run_coroutine_threadsafe`.

This is rule 141 wearing different clothes, and it recurs because the reflex on understanding a
defect is to write the cure. The moment you can describe the fix is the moment to search for
it: a codebase that made the mistake in two places has often got it right in a third, and that
third file usually explains why.

## Rule 175 — a measurement taken while something else is writing is not a measurement

A coverage run reported twelve failures across four file-walking guards, each timing out just
past the 5-second default. `quality-gates.yml` runs `npm run coverage` as a blocking step on
every branch push, so the conclusion was immediate and alarming: the gate is red for every
developer, right now, for a reason unrelated to what it gates.

The same output contained the answer:

    Something removed the coverage directory ".../coverage/.tmp" Vitest created earlier.
    Make sure you are not running multiple Vitests with the same "coverage.reportsDirectory"
    at the same time.

Three of my own coverage runs were racing. A single clean run: 131 files, 1,063 tests, zero
failures. Every timeout was contention I had created, and the "finding" had to be withdrawn
after it was stated.

Earlier in the same session, two pytest suites against one Postgres produced the identical
class of phantom. Different tool, different shared resource — a directory instead of a
database — and the same failure of method: I had a hypothesis before I had a clean measurement,
and the noise obligingly confirmed it.

Two habits follow. Before believing a failure, ask what else was touching that resource. And
read the whole output, including the part that looks like environmental chatter: the tool
usually names the problem, in the lines you skip once you think you know what you are looking
at.

## Rule 176 — a ratchet with no margin fails on the next unrelated change

`vitest.config.ts` sets its coverage thresholds with a stated design: *"~1 point of margin:
enough that a single refactor does not fail the build, not enough to absorb a real
regression."*

Measured, statements cleared by **0.02 points** — about one and a half statements out of 7,486.
Nothing was broken. Every gate was green. And the next uncovered statement added anywhere in
the frontend would have turned the build red for a change that had nothing to do with coverage.

That is worse than it sounds, because of what happens next: a developer whose unrelated
one-liner fails a coverage gate does not write tests for somebody else's untested module. They
lower the threshold, and the ratchet loses a point permanently. The margin is not slack — it is
what keeps the gate's failures attributable to the change that caused them.

The repair is tests. `src/api/shopFloor.ts` was at 0% with 228 lines behind a live page; 21
tests took statements from 49.02 to 49.38.

And then, deliberately, **do not raise the threshold to the new floor.** Raising it to 49.38
would restore exactly the condition just escaped. Raise a ratchet when the margin is comfortable
and the direction is proven, not the moment the number moves.
