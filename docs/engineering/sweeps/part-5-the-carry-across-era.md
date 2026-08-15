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

## Rule 177 — a test that only runs in one environment is a test nobody has watched run

`e2e/authenticated.spec.ts` contained this, and had since it was written:

    await page.getByLabel(/username/i).fill(EMAIL)

Nothing in the file defines or imports `EMAIL`. It is a local `const` in `auth.setup.ts` and in
`writes-actually-persist.spec.ts` — near enough to read as if it were in scope, and it is not.
Every execution ended in `ReferenceError` before the click.

What kept it hidden is that the file skips unless `E2E_LIVE_BACKEND=1`. On a laptop the test
reports as skipped, which looks like a choice rather than a defect. In CI it fails inside a job
whose overall result is the only line anyone reads.

So the claim — *a wrong password does not log you in* — had been taken entirely on trust, and
it is not a claim anyone would want to take on trust.

Anything gated behind an environment flag needs at least one deliberate run under that flag
before it counts as coverage. A skipped test and a passing test are the same colour in most
reports, and a test that has never once reached its assertion is worse than no test, because
its name appears in the list.

## Rule 178 — an assertion satisfied by the state *before* the action is not an assertion

    await page.getByRole('button', { name: /sign in/i }).click()
    await expect(page).toHaveURL(/\/login/)

`toHaveURL` polls and resolves the moment it matches. A quarter-second after the click the URL
is still `/login` — whatever the server is about to answer — so the assertion resolves against
the *pre-action* state and the test passes unconditionally. Supplying the correct password
proved it: still green, while a probe watched the same flow navigate to `/`.

The shape generalises past URLs. Any assertion about "it did not change" is satisfied by the
instant before it changes, and any polling matcher resolves at the first moment it can. Assert
on something only the outcome can produce — the response status, the error the page renders,
the navigation that did or did not happen after the request settled.

## Rule 179 — rendering more correctly can break a test that was passing by racing

`/accept-invite` had no `<main>` landmark. Adding one is a plain accessibility improvement: it
and `Login` are the only pages outside `Layout.tsx`, so a screen-reader user had nothing to
skip to on either.

It broke `data-reaches-the-screen.spec.ts`, which opens with:

    await expect(page.locator('main, body')).not.toBeEmpty()

That locator matches **two** elements the moment React has mounted a layout, which Playwright
treats as a strict-mode violation and fails immediately. It had passed on every route only
because it evaluated in the instant after `goto`, when `<body>` exists and `<main>` does not
yet. The page that mounts fastest loses that race — and making a page render *more* correctly
made it mount fast enough to lose.

The instinct when a change breaks a test is that the change is wrong. Check the other direction
first: whether the test was depending on the timing of the thing you just fixed. Here the test
had been one fast render away from failing on any route, and the accessibility fix simply
collected the debt.

## Rule 180 — check that every directory of code you own is read by some compiler

`e2e/authenticated.spec.ts` referenced a name nothing in it declared, and did so for its whole
life. The question worth asking is not how that was written — it is how it survived.

`tsconfig.json`:

    "include": ["src"]

That is the entire explanation. The six Playwright specs and their setup project are outside
it, so `tsc --noEmit` never opened them. `vitest run` does not typecheck — it transpiles and
throws the types away. No linter was configured over that directory either. The one class of
defect a compiler catches for nothing was invisible in precisely the directory whose tests skip
silently without a live backend and whose assertions include *"a wrong password does not log
you in"*.

Nothing about the directory looks neglected from inside it. The imports resolve, the tests run,
the suite is green. The gap is only visible from the config outward: which paths does any
compiler actually read?

Widening the include cost nothing — zero new errors — and `npx tsc --noEmit` was already a
blocking CI step, so the gate widened with it. The guard that keeps it is about the config, not
the code, because narrowing an include back is the edit that looks harmless in review.

Worth adding: the first thing I reached for was a hand-written scanner for undeclared
identifiers. It matched every capitalised word in every comment, including the ones in the note
I had just written about this defect. The compiler answered the same question in one command
(rules 37 and 167).

## Rule 181 — a guard whose subject list is hand-typed is blind exactly where nobody was looking

`test_branch_pushes_reach_the_gates.py` exists for one purpose: to refuse the arrangement where
a check lives in the workflow that runs on `main` and not in the one that runs on every branch
push. It is a good guard, written after a real incident, and it passed continuously while the
entire edge agent — 386 tests, including the collector suite where FS-675 was found — ran on
`main` and pull_request only.

The reason is in its first ten lines:

    REQUIRED_ON_BRANCH_PUSH = {
        "a typecheck": …, "a lint": …, "vitest …": …, "flake8 …": …, "the build": …,
    }

Five gates, typed by hand. Everything else in `ci-cd.yml` is outside the comparison, so the
guard could only ever find the gaps somebody had already thought of — and the gap somebody has
thought of is not usually the one that bites.

Adding a sixth entry is not the repair; it leaves the next omission exactly as invisible. The
repair is a second check **derived from the other workflow**: every directory that has tests in
`ci-cd.yml` must have tests in the branch-push workflow. Coarser, and it cannot be blind to
something nobody listed.

A note on the entry I did add. The obvious spelling for the new gate was `("edge-agent",)`, and
it passes with the suite step deleted — `pip-audit -r edge-agent/requirements.txt` is also a
run command containing that string. A matcher that cannot fail is worse than no matcher, so it
came back out.

## Rule 182 — a comment describing an intention is not the intention being carried out

Above the flake8 step in `quality-gates.yml`:

> `scripts` as well as `app`, which `ci-cd.yml` does not cover. Both were measured at zero the
> day this step was added — along with `backend/tests` and `edge-agent/opsgrid_agent` — so
> widening the scope costs nothing now and is the only moment it ever will.

The command beneath it:

    flake8 app scripts --count --select=E9,F63,F7,F82

The comment names two more directories, measures them, argues for including them, and explains
why the moment is cheap. It does not include them. 379 backend test files and 120 edge-agent
files stayed outside the only check that catches an undefined name.

This is worse than an absent comment, because it reads as evidence the work was done — by the
author, later, and by anyone reviewing. It is the same shape as a stale docstring or a
`TODO(fixed)`, except that it is arguing a case, which makes it more convincing.

When a comment states a scope, a count, or a guarantee, read the line below it as though the
comment were not there.

## Rule 183 — point the question at the configuration, not at the code

Three findings in a row came from one question, asked three times, and never from reading a
source file:

* `frontend/e2e` was outside `tsconfig`'s `include`, so seven Playwright specs — the ones
  making the most security-relevant claims in the repository — were typechecked by nobody, and
  one of them had carried `ReferenceError: EMAIL is not defined` since it was written.
* The edge agent had no gate at all on a branch push: 386 tests that ran on `main` only.
* 528 Python files across `backend/tests`, `edge-agent/` and the repository root were read by
  no linter, including the cluster checkers CI itself executes.

None of this is visible from inside those directories. The imports resolve, the tests run, the
suite is green, and every file looks like every other file. Nothing about `e2e/authenticated.spec.ts`
suggests it has never once reached its assertion.

It is visible immediately from the other direction. `"include": ["src"]` is one line.
`flake8 app scripts` is one line. Both are short, both are legible, and neither is ever read
during the work they fail to cover.

So make the configuration a subject in its own right. List the directories that hold code you
own; list the paths each checker is pointed at; subtract. The answer takes minutes and does not
depend on suspecting anything in particular — which matters, because the places this finds are
the ones nobody suspects. A directory nobody checks is usually a directory nobody visits, and
those two facts protect each other.

## Rule 184 — a citation is a claim, and claims decay

This repository explains itself by cross-reference. Comments say *"asserted by X"*, *"the guard
that keeps this is Y"*, and 256 distinct test filenames are named in prose across the tree.
That habit is most of what makes the reasoning followable a year later.

Two of those names pointed at nothing:

    # per driver — `test_fleet_health_filters_in_sql.py` asserts these reads do not loop.
    * `test_production_settings_are_validated.py` refuses `GEOTAB_SIMULATED` in production.

The first property is real and lives in `test_fleet_health_query_shape.py`. The second is real
and lives in `app/core/config.py::validate_settings`. Both guards existed; both trails were
broken.

That is worse than no comment. A reader who follows a citation into nothing has to choose
between two conclusions — the protection was deleted, or they searched wrongly — and neither is
cheap. Do it twice and they stop following citations, which costs the codebase the thing that
made it legible.

A number in prose gets a guard here (rule 44). A filename in prose is the same kind of claim
and had none.

## Rule 185 — narrow the scope until the detector is right, rather than adding exclusions until it is quiet

The first citation checker flagged thirteen lines. Among them: its own docstring, which names
the missing files while explaining that they are missing; and the corrected sentence in the
geotab test, which names the file that never existed in order to say so. Prose describing a
stale filename matches a detector for stale filenames perfectly — rule 37, arrived at from a
new direction.

The obvious repair is an exclusion list: this file, that file, those four documents. It would
have worked, and it would have grown with every future explanation anybody wrote, until nobody
could tell which entries were reasons and which were surrender.

The repair used instead was a principle. **A comment in a source tree naming a test file is a
claim about the present; a test or a document may legitimately narrate history.** So the guard
reads `app/`, `opsgrid_agent/` and `src/` only. 48 citations, all resolving, and it fails when
the original stale line is restored.

Scope states a reason. An allowlist records the occasions on which the reason was missing.
Where both are available, the reason is the artefact worth keeping.

## Rule 186 — writing up a defect can trip the guard for that defect, and that is the guard working

Two comments cited test files that do not exist. Fixing them was a minute's work; documenting
them meant naming both files in the delivery log, and `test_documented_files_exist.py` — which
has checked every backticked path in `docs/` since FS-513 — failed on that prose in the same
run.

The reflex is to read that as an over-eager check catching prose it should not. It is the
opposite. The document really does contain a name that resolves to nothing, and a future reader
following it really would find nothing; the fact that the surrounding sentence explains why
does not change what the string does. Rule 37 has been arrived at from several directions in
this repository — a detector matching the comment that describes a defect — and this is the
same shape with the roles swapped: the comment describing a defect *is* an instance of it.

The answer is the register that guard already carries. Each name goes in with a reason, so the
exception is stated rather than the check quietly widened. Three entries, three sentences, and
the next person sees both the exception and why it is one.

Two smaller lessons came with it. The documentation half of this class already existed and I
built the source half without looking — rule 141, twice in one session, and reading the old
guard first would have been the shortest route to the new one. And I claimed the existing guard
shared a dotted-name bug I had just fixed in mine; it does not. Its pattern captures
`geofencing.realmode.test.ts` whole. It flagged a fragment because I had written that fragment
in backticks while explaining my own bug — a fault in my prose, reported accurately.

## Rule 187 — a ratchet that counts correct code names a change that would do harm

`test_the_swallow_surface_only_shrinks.py` tracks broad `except` handlers that do not re-raise.
Twelve of them are in `api/health.py`, the largest block in that file, and every one is right:

    async def _check_database(db) -> tuple[str, dict]:
        try:
            ...
            return "ok", {}
        except Exception as exc:
            return f"error: {exc}", {}

The failure is not swallowed. It is translated into a value, and `_run_health_checks` reads
every value, reports each component, and grades the whole as `ready` / `degraded` / `not_ready`.
The ratchet excludes `raise` and does not exclude this, so correct code reads as debt.

That would be a harmless miscount if nobody acted on it. But the cheapest way to remove twelve
entries is to raise instead — and a readiness probe that raises returns 500 the moment any one
dependency is unavailable. Kubernetes restarts a pod whose only problem is that Redis is slow,
and the operator loses the per-component report naming the dependency that actually broke.

So the question to ask of any ratchet is not just *is the number honest* but **what would the
cheapest reduction do?** If the answer is harm, the population is defined wrongly, and the
response is to pin the property — a guard whose mutation test is exactly that tempting change —
rather than to reduce the number or quietly edit the definition.

Not edited here, deliberately. 37 of the 201 handlers return a value carrying the exception, and
excluding them by shape was rejected because a returned error is only propagation if the caller
reads it, which the shape cannot show. Demonstrating that the caller reads it is worth more than
redefining the population.

## Rule 188 — stub the failing state the code actually has, not the one you imagine

To test that the health aggregator survives a broken dependency, the obvious double is a checker
that raises:

    async def _raise(*_args, **_kwargs):
        raise RuntimeError("database is down")

Every assertion failed with that `RuntimeError`, and for a minute it looked like a finding: the
aggregator does not catch it, so surely a broken dependency 500s the endpoint?

No. `_run_health_checks` deliberately does not wrap its checkers, because **each checker catches
its own failure and returns it**. The failing state of `_check_database` is a returned
`("error: …", {})`, not an exception. The stub had removed the behaviour under test and then
reported its absence as a defect.

Read how the real thing fails before writing the double that stands in for failure. A test
double is a claim about the system, and a wrong one produces a confident failure that costs more
than no test — it points at working code and takes the reader with it.

## Rule 189 — a document that states the same quantity twice will eventually disagree with itself

The README's run-command block said:

    cd backend && pytest          # ~3,200 pass, ~92 skip

and two hundred lines below, in the CI table:

    `backend-full` (**4,090+ tests** … the figure is a FLOOR asserted by
    `test_readme_test_count_is_not_stale.py`)

Both describe the same suite. The second is guarded and stayed true; the first is not and
drifted by thirteen hundred. The document contradicted itself, and no check in the repository
could see it, because the check was pointed at the other sentence.

This is worse than a single stale number. A reader who finds two answers in one document has no
way to tell which is current, so the accurate one loses its authority along with the stale one
— and the guarded figure was the accurate one.

Where a quantity appears twice, either guard both occurrences or make one point at the other.
The cheap version of "point at" is a sentence: *"the floor stated in the CI table below"*. What
does not work is assuming the second mention will be updated alongside the first, which is the
assumption that produced this.

## Rule 190 — guard the number a newcomer meets first

    cd frontend && npx vitest run  # ~525 across 73 files

The real figures are 1,089 across 133. This line had no guard of any kind, while the backend
floor beside it had one — and of the two, this is the one a new contributor meets first,
because it is in the block titled "run the tests".

Staleness costs most where it is met earliest. A developer who runs the suite and sees twice
the documented count cannot distinguish a stale document from a broken checkout, and the
natural reading is the unflattering one: *I have done something.* The cost is not the wrong
number, it is the half hour spent proving the number wrong, and the small permanent discount
applied to everything else the document says.

So when choosing which prose numbers deserve a guard, weight them by who reads them and when.
The figures deep in an architecture table are read by people who already know the system. The
one in the quick-start block is read by someone with no way to check it.

## Rule 191 — a fix verified against a double is a claim about the double

FS-675 found that every MQTT reading was dropped: `asyncio.create_task` raises on paho's
network thread, so the reading never reached the callback. The fix was verified with a test
that calls `_on_message` from a `threading.Thread`.

That test is worth having — rule 159 exists because the *first* version called it on the loop
and passed against the defect. But notice what it actually asserts: that Python raises when you
create a task off-loop. It does not observe paho at all. The premise *"paho dispatches
`on_message` from its own thread"* is read from documentation and assumed.

The infrastructure was one container away:

    docker run -d -p 21883:1883 eclipse-mosquitto:2

A real broker, the real collector connecting with `loop_start()`, a real second client
publishing three messages:

    pre-fix   0 delivered   mqtt_message_handler_error: no running event loop
    fixed     3 delivered

Same broker, same publisher, same payloads. The double proved the mechanism; the broker proved
the defect — and produced the exact error string a production log would have carried while the
agent quietly dropped everything.

The first attempt published to a topic of my own choosing and got zero deliveries from *correct*
code, because `_subscribe_to_topics` derives its topics from the asset id. The agent had logged
`mqtt_subscribed topic=device/printer-1/report` in the same run. When a live drive returns
nothing, read what the system said it was doing before concluding anything about what it did.

## Rule 192 — a guard that reads state written after an `await` can never win

    def on_modified(self, event):
        if event.src_path not in self._processed_files:      # the check
            spawn(self._process_gcode(event.src_path), ...)

    async def _process_gcode(self, file_path):
        await self._wait_for_file_stable(path)               # suspension
        ...
        await self.on_file_callback(message)
        self._processed_files.add(file_path)                 # the write

A single file write emits `on_created` and `on_modified` within milliseconds. Both handlers run
before `_wait_for_file_stable` has returned for either, so the set is still empty when the
second one checks it. The guard reads state that is written two awaits later, and therefore
never sees it.

Measured against a real `Observer`: every G-code file processed and emitted **twice**, one print
recorded as two, both messages carrying the same path and size so nothing downstream could
distinguish them. `on_created` compounded it by not checking at all.

The repair is the ordinary one for check-then-act: claim the resource *synchronously*, before
the first suspension, and let the claim itself be the check. `set.add` on the observer thread
is atomic under the GIL and both events arrive on that same thread, so a claim taken there
cannot be raced.

Whenever a check and its corresponding write straddle an `await`, ask what happens if the same
event arrives twice before the first completes. In an event-driven collector, "twice" is not a
rare interleaving — it is what the library does every time.

## Rule 193 — run the real thing twice: once to prove the fix, once to see what else it does

The live drive of the file watcher was set up to answer one question — does FS-675's fix work?
It did: 0 files processed with the old code, 2 with the new.

The answer contained a second finding. **2 was wrong.** One file should produce one reading, and
the log showed `gcode_file_processed` twice for a single write.

The unit tests could not have found it, and are not deficient for that: they deliver one
synthetic `on_created` event and assert one call, which is precisely the behaviour the code gets
right. The question they cannot ask is *what does the environment actually send?* — and watchdog
sends two events for one write, always.

So when a live drive is already standing up, read the whole of its output rather than the line
that answers the question you came with. The environment is being honest about itself for a few
seconds; most of what it says is about something other than the bug you are chasing.

## Rule 194 — count a metric's call sites against what it claims to cover

The carry-across from rule 193 was mechanical: the live drive of the file watcher had already
paid for itself twice, so the same treatment went to `http_rest`, the other collector whose
tests drive the real object through a stubbed transport. Its own docstring names the risk:
*"a poll that raises on every cycle looks exactly like a poll that works."*

Against a real `http.server` returning 500, for three seconds:

```
readings from a server returning 500: 0
collector reports running: True
what the metrics say about press-2: (nothing — no counter names this asset)
```

The first two lines were expected. The third was the finding.

**`metrics.errors_total` was incremented by nothing, in any of fifteen collectors.** Fifty-nine
`logger.error` sites across the package and not one `record_error` among them.

The instinct is to write the sweep that would have caught it — *find metrics nobody emits* —
and it is worth writing, but be clear that **it would not have found this one.** `record_error`
had a caller: the coordinator, at one site, for a counter labelled per asset and per collector
type across fifteen types. One call site is not zero, and a check for zero passes it.

The disproportion is the signal. A metric whose labels promise per-asset, per-type resolution
and whose emission happens at a single site is being fed by one path out of many — and here the
one path was `except` around a *message handler*, which cannot fire for a poll that failed,
because a failed poll produces no message to hand to a handler.

Run the zero-call-site sweep as well. It found one: `COLLECTOR_MESSAGES`, reachable only
through a helper nobody calls, a leftover of the merge that brought a second metric family for
a quantity the first already counted. `prometheus_client` publishes the whole default registry,
so it was not merely unwired — it was *exported*, at `/metrics`, reading zero, with a
description explaining what it would have meant. A flat line an operator would read as "no
telemetry" rather than "nobody connected this".

## Rule 195 — a shared seam covers one direction only

`metrics.py` opened by explaining why individual collectors needed no instrumentation:

> Instrumentation lives at the coordinator/adapter seam, which every collector — mature and
> BaseCollector-style — funnels through, so a single set of metrics covers all collector types
> without editing individual collectors.

Every word of that is true about deliveries. Every reading does funnel through that seam.

A failed poll delivers nothing. It never reaches the seam at all.

The property that made the design attractive — *one point that everything passes through* — is
the property that made it blind, because "everything" meant every success. This is worth
holding as a general suspicion rather than a fact about this file: when a design routes all
instrumentation, validation or logging through a single choke point, the question is not
whether the choke point is well built. It is whether the failing case arrives there, or dies
upstream of it.

The repair mirrors what was already there. `emit()` was the shared seam for a reading that
worked; `record_failure()` is now the shared seam for one that did not, logging exactly the
line it used to log and counting it as well. Ten collection-failure paths across ten
collectors now go through it. Startup refusals (`*_driver_missing`, `*_no_host`) and teardown
noise (`*_disconnect_error`) deliberately do not — a collector that never started has no
collection to attribute a failure to, and counting it would put a flat line on a collector
that is not running rather than one that is failing.

## Rule 196 — liveness derived from the worker is not liveness of the work

The last part of the finding is the one that makes it operational rather than tidy.

`connection_state` — the gauge an operator would consult to ask whether a collector is alive —
was set from:

```python
up=task is not None and not task.done()
```

A collector polling a device that answers 500 forever has a perfectly healthy task. It is
scheduled, it is not done, it will still be there next month. So the gauge reads **up**, for an
asset that has produced nothing since the device broke.

Then the alerts, which is where it stops being subtle. Nothing in `alerts.yml` keys on a
collector that is up and silent. `EdgeAgentOffline` watches `edge_agent_up`, which is 1 — the
agent is heartbeating fine, it is one of its collectors that is dead. `EdgeAgentBufferHigh`
watches buffer depth, which is 0 **because nothing was collected**. The alert that should have
caught the silence is silenced by it.

A machine that stopped reporting a month ago and a machine that is idle produced identical
monitoring, and the only difference between them was an ERROR line in a log.

Health derived from the mechanism will faithfully report the mechanism. If the question is
whether work is happening, the answer has to be computed from output — a counter that moves, a
timestamp that advances — and not from whether the thing that was supposed to do the work still
exists.

**A note on how the guard for this was nearly weaker than the fix.** The first version asserted
that the adapter still exposes `_collector`, the attribute the coordinator unwraps to find the
collector it must label. That pins the adapter. It does not pin that the coordinator *uses* it —
and replacing the unwrap with `inner = collector` leaves the adapter failing an `isinstance`
check, so labelling is skipped in silence and every wrapped collector reverts to its class name,
which no longer joins the gauge. That mutation passed the entire package. The test now drives
the real `_start_collector` and reads the label off the collector that will do the counting;
rule 191 applies to guards as readily as to fixes.

## Rule 196, carried into the backend — and the answer was the control path

Rule 196 was written about a collector. The obvious next question is where else a service
reports its own health from the existence of the thing doing the work, and the backend has
exactly two sites that call `.done()`. One is the task-ownership helper. The other is
`_check_command_dispatch`, and it was the whole of that check.

The loop it watches is written like this, and correctly:

```python
while self._running:
    try:
        await self.dispatch_pending()
    except Exception as exc:
        logger.exception("command_dispatch_iteration_failed", error=str(exc))
    await asyncio.sleep(self._poll_interval_seconds)
```

One poisoned command must not stop dispatch for the fleet, so the loop swallows and
continues. **A loop written never to die cannot answer a health check phrased as "have you
died".** `done()` is False for as long as the process lives, whether the loop is dispatching
commands or throwing on every single iteration.

The failure mode is the same as the collector's and lands somewhere worse: an operator sends
a command to a machine, the command sits in pending forever, and `/health/detailed` reports
`command_dispatch: ok` the entire time.

The repair is the same too — count what the loop achieves rather than ask whether it exists.
Consecutive failures, reset by a success, three of them being an error.

**The register is the more useful half of this finding.** Applying the same question to the
rest of the startup sequence: `main.py` starts eight background services and health reports
on one. Seven run for the lifetime of the process, watched by nothing. The one that most
deserves a note is `error_tracker` — if the error tracker dies, errors stop being reported,
and a system that has stopped reporting errors looks exactly like a system that has stopped
having them. That is rule 196 in one sentence, and it is the same sentence as
`EdgeAgentBufferHigh` watching a buffer that stays empty because nothing was collected.

Both of those alerts are silenced *by* the thing they exist to detect. When a health signal
is derived from the absence of bad news, check whether the failure being watched for would
also suppress the news.

## Rule 196, third application — the instrument this time

FS-691 was a collector whose task outlived its work. FS-693 was a backend loop whose task
outlived its work. FS-694 asks the question one level up: *the gauges those health checks
and alerts read — what happens to them when their writer stops working?*

The answer for `edge_buffer_messages` was: nothing visible. A gauge whose writer dies does
not zero and does not disappear from `/metrics`. It freezes. And a frozen buffer gauge is
worse than an absent one, because `EdgeBufferGrowing` keeps evaluating it, sees a steady
number, and stays quiet — while the heartbeat's snapshot freezes in the same loop, muting
`EdgeAgentBufferHigh` too. The failure of one 30-line loop silently disarms both alerts
that watch the agent's most important failure mode.

The pattern that fixes it is old and standard — a last-success timestamp beside the data,
an alert on its age — and the interesting parts are the two corners:

1. **The stamp lives inside `set_buffer_stats`, not beside its call site.** A stamp updated
   in the loop but outside the helper keeps reading fresh through any refactor that calls
   the helper from somewhere the stats are stale. The vouching must travel with the write.

2. **The baseline stamp at loop start closes the absent-series trap without `unless`.**
   A loop that never succeeds never creates the series, and `time() - <absent>` is nothing.
   FS-691's alert answered the same trap with `unless` in the query; stamping at startup
   answers it at the source, and the semantic is honest — "stats were current as of boot" —
   after which the age grows until the first real success.

When a health signal is itself produced by a loop, the loop needs a watchdog, or every
alert downstream of the signal inherits the loop's failure mode silently.

## Rule 197 — `task.exception()` on a cancelled task raises

FS-698's mechanism, stated as the API contract it violates. `Task.exception()` returns the
exception for a task that *failed* — and **raises CancelledError** for a task that was
cancelled. Code that inspects done tasks inside `except Exception` is therefore correct for
every outcome except cancellation, and cancellation is precisely the outcome an
administrative operation (restart, hot-reload, shutdown) produces on purpose.

The sweep across both codebases: three sites inspect task outcomes. The two `spawn`
helpers (`backend/app/core/tasks.py`, `edge-agent/opsgrid_agent/tasks.py`) both ask
`cancelled()` before `exception()` — that idiom was already load-bearing there. The
coordinator's health monitor was the one raw site, and it was also the one whose death
costs the most: sole writer of the liveness gauge, sole automatic restart path.

Worth keeping in the pattern library because the failure needs two ingredients that are
individually innocent: `except Exception` (correct — the loop must survive anything) and
`task.exception()` (correct — that is how you read a failure). Neither line looks wrong.
The bug lives in the pair.

## Rule 198 — sweep for endpoints nobody calls before features nobody built

The page-by-page arc opened with a survey rather than a backlog: four readers over all 37
pages, each asked what its page shows, what a user can do, and *what the router behind it
serves that the page never calls*.

The third question was the one that paid. The dominant gap was not missing capability but
unreached capability — nine export-schedule endpoints with zero frontend references, two
entire routers (`logistics_correlation`, `model_monitoring`) unreachable, six alarm filter
parameters of which the page sent one, three asset filter parameters of which it sent
none.

Twelve shipped enhancements then needed **two** new backend routes between them.
Everything else was a wire.

A product can be a full release behind its own API, and nothing inside either half
notices: the backend's tests pass because the routes work, the frontend's tests pass
because the pages render, and the gap lives precisely in the space no test on either side
is looking at. Enumerating routes against callers is a morning's work and it should
happen before any design conversation about what to build next.

## Rule 199 — assert the request, not the rendering

The historian's metric picker gained a state-sync effect: when the asset's metric list
arrives and the current selection is not among it, select the first one instead. The test
read `select.value` and passed.

It also passed with the effect deleted — because a `<select>` renders its first option as
its value whether or not state followed it. The display was derived, not bound, so it
agreed with the correct code and the broken code equally.

What matters is which metric the historian is actually *asked for*, and only an assertion
on the outgoing request could see the difference. Wherever a control's displayed value is
derived rather than bound to the state under test, the display is the weaker witness.

## Rule 200 — when the right answer's text is not unique, assert the absence of the wrong one

A paused export schedule shows "paused" twice: in its status badge, and in place of a
next-run date that is not going to happen. `findAllByText(/paused/i)` was therefore
satisfied by the badge alone, and passed while the cell still printed the stale date.

The check that distinguishes them asserts what must NOT be there — no date rendered for a
paused row — with a negative control that a live schedule does show one. Presence checks
are the default reflex and they are blind exactly when a word appears in more than one
role.

## Rule 201 — a surviving mutation is not automatically a weak test

Deleting the explicit `organization_id` filter from the new notifications PATCH did not
fail its cross-tenant tests. The instinct is to conclude the tests are weak and add
assertions until they bite.

The right move was to find out why. Migration 056 had given
`notification_subscriptions` a row-level-security policy — the file's own header still
said the table had none — so the other tenant's row was invisible to the SELECT whichever
filter the handler wrote. The mutation survived because a second layer caught it.

Both layers stay, for different reasons: RLS is the one a new handler cannot forget, the
explicit filter is the one that survives a session opened without the GUC — which is how
`_check_ingestion` and the FS-704 fleet sweep were each caught reading zero rows. The
test file now states which layer it is proving. Adding an assertion that pins the
redundant layer would have made the suite slower and no stronger.

## Rule 202 — an unused client with a guessed shape is the defect, written by the sweeper

While wiring the OEE loss breakdown I added a `getHistorical` client alongside it, on the
reasoning that the aggregation endpoint was in the same router and would be wanted soon.
It declared a `points` array of a `HistoricalOEEPoint` type.

The endpoint sends `data`, and the calculator owns the row shape, so there is no point
type to declare. `test_frontend_fields_exist_on_the_wire.py` refused it.

The method was deleted rather than corrected. An accurate type for a function nothing
calls is still a claim nothing exercises, and the next person to reach for it would
inherit whatever drift had accumulated. This repository has spent findings on declared
fields the server never sends; writing one speculatively, in the same arc as sweeping for
them, is the failure mode worth naming.

## Rule 203 — a guard that rejects your work is usually right

Five guards refused work in this arc. Four were straightforwardly correct:
`mutationFailureIsVisible` (a per-call `onError` reads as silent at the mutation
definition, which is where a reader looks), the truncation sweep (a hand-rolled header
read bypassing the shared `toListResult`), `frontendSafetyRatchets` (an inline
`toLocaleString`), and the route-auth walk (a new PATCH with no reviewed role policy).

The fifth was the detector's fault, and it looked exactly like the other four. The
truncation sweep matched its idiom only in the 200 characters *before* the `api.get`
call, which recognises `return toListResult(await api.get(...))` and not the
capture-then-wrap shape needed to read a second header off the same response. Widening
that window was right.

The order of those two conclusions is the whole rule. Reaching for the detector first
would have shipped four regressions with a green suite.

---

## Rule 204 — a register entry about a field the service honours is worse than none

The declared-body-fields extractor reads the handler body. Five correlation routes hand the
whole request to a shared executor — the shape that appears the moment three routes want the
same work, one synchronous, one queued, one preview — so by that measure each read *nothing*
and all five were candidates for the register.

One of them was `POST /answer`, whose dropped field was `question`.

A register entry is a claim that somebody looked and decided the drop was acceptable. Adding
five would have recorded the reverse of what the code does, and the next reader would have
had no reason to doubt it. The extractor now follows a forward two hops, across a
`from app.api.… import` as well as within a module, and checks the `model_dump()` exemption
against the followed reads rather than the handler text — `POST /answer` dumps the body one
call away, inside the helper.

Before registering a batch, ask whether the detector can see the shape the code is written
in. A register is where findings go to be remembered; it must not be where a detector's blind
spot goes to be believed.

## Rule 205 — notice when you have just taken the cheapest reduction

Twenty new routes needed a `response_model`. Their payload keys are chosen by the engine per
request, and `response_model` deletes what it does not declare, so a closed model would
silently drop tomorrow's keys. `response_model=Dict[str, Any]` answers that: it does not
filter, it is precedented in this tree, and it satisfies the coverage ratchet.

It is also precisely what `test_a_permissive_response_model_is_not_a_contract.py` exists to
refuse, and that guard caught it about an hour later. Rule 187 says to ask what the cheapest
reduction of a ratchet would do; the harder half is recognising that the reasonable-sounding
thing you just did *is* that reduction.

The real answer was a model with `extra="allow"` — named fields in the schema, the SDK and
the contract gate, with every undeclared key still passing through. That last claim was
**measured against a live response** and the measurement kept as a test, because an exemption
resting on framework behaviour nobody checked is how a real drop gets waved through. The
drop-detector now exempts open models for the same measured reason.

And `extra="allow"` protects nothing against a declared field of the wrong type: two of the
twenty were annotated from the field's NAME rather than the callee's return type, and both
would have answered 500 to every call.

## Rule 206 — a guard can pass its own mutation test for the wrong reason

A new rule accepted a JSX gate as safe when the failure path cleared the state behind it,
implemented as "a `setX(null)` within 600 characters of the word `catch`".

Deleting the real fix changed nothing. A reset helper elsewhere in the file called
`setEvidenceResult(null)` shortly after an unrelated `catch`, so the rule had been reading
the wrong evidence from the start and the mutation could not move it. Brace-matching the
actual catch body fixed it, and the mutation then failed exactly where it should.

Run the mutation. If it does not fail, that is a finding about the guard — not a formality
that passed.

## Rule 207 — a line break can empty a sweep, and only the vacuity check will say so

`idKeyedFetchesDoNotGoStale` recognised a fetch by `Api\.`, requiring the receiver and the
dot to be adjacent. The tree's one id-keyed fetch is a wrapped promise chain:

    transportationApi
      .getShipmentCosts(shipment.id)

so the population fell to **zero** and every id-keyed detail view went unchecked. No code
changed; formatting did. The count-based honesty check is the only thing standing between
that and a permanently green guard over an empty list — the third time in this repository a
sweep has been caught measuring nothing, and the first where the cause was whitespace.

## Rule 208 — scope a per-file sweep to the component, not the file

`failureIsNotEmptiness` already held the principle that a presentational list given its rows
as props cannot fail a request, and tested it — but applied the query check per FILE. A
1,900-line page module that declares its own drawer beside it therefore put every phrase in
that drawer in scope, because the *page* fetches.

Two more false positives in the same run came from matching the argument of
`setEvidenceError(...)`. That string is the failure branch; reporting it as an empty state
inverts the finding exactly.

Both narrowings are safe for the same reason: a component with no fetch of its own has no
failure of its own, and text passed to an error setter is displayed only on failure. Neither
can hide a page that renders its own failure as emptiness — which the same run found three
times in that very file, where a `catch` set an error and left the previous answer on screen.

## Rule 209 — a session handed across a module boundary is still your session

`operations_assistant.py` took `Depends(get_db)` and named no RLS-backed model anywhere in
the file. It passes the session to `_execute_evidence_request`, imported from the
correlation router, which reads `intake_items` — FORCE ROW LEVEL SECURITY since migration
011. The static guard asks whether a router *names* a model whose table is under RLS, so
this one was never a candidate, and `POST /operations/answer` and `POST /operations/briefing`
answered **404 "One or more intake sources were not found"** for the caller's own uploads.

One layer down it cost more. The asynchronous job rebuilds its session in a nested
`async def run(report)` whose entire body is a call, under a comment claiming every query
was scoped explicitly. It was `AsyncSessionLocal()`, which sets no GUC, so **every queued
evidence job failed** — with an error a caller reads as "I passed ids that do not exist",
while the synchronous preview returned 200 for the same ids on a `get_tenant_db` session.

A background task is where this always hides. It has no request to take a dependency from,
so it builds its own session, and the query it feeds is always somewhere else. Both halves
of the guard now follow the call — one hop into a same-module helper, one across a
`from app.api.… import`.

Note what found it. Not the guard, and not a unit test: the services under these routes have
900 lines of direct coverage and every one of those tests calls the service, not the route.
It was found by driving the pipeline over HTTP the way a user drives it — upload, catalog,
correlate, ask — which nothing had ever done.

## Rule 210 — the same bug can live in two halves of one file

This guard learned in FS-431 that prose is not code. A comment explaining that a handler no
longer takes the unscoped session was being counted as a handler that does, so the
`Depends(get_db)` sweep started stripping comments and docstrings first.

The `AsyncSessionLocal` half of the same file still read raw source.

The cost was a mutation test that lied. Reverting the FS-718 job fix left behind a comment
saying why the GUC matters; the words `current_org_id` appeared in the function body; the
guard exempted the very function whose session had no GUC; and the mutation passed, which
reads as "the guard is fine". Only reverting the comment *as well* exposed it.

When you fix a detector flaw, grep the file for every other place that makes the same
assumption. One fix in one half is not the same as the file having learned.

## Rule 211 — recognise the extracted helper, or the false positive writes an exemption

Stripping comments made the inline check honest, and it immediately flagged
`erp_integrations.run_erp_sync` — which binds its tenant correctly, through
`_set_tenant_guc(db, organization_id)`. The check knew only the inline `set_config`
spelling, so the literal it looks for lived in the helper rather than the caller.

That function's own comment records this defect class in detail, having been fixed for it
once already. Reporting it as unscoped would have been the guard calling its best-documented
success a failure.

The natural response to a false positive is an exemption entry, and an exemption is
permanent in a way the false positive is not: the next real offender in that file is now
invisible. Following the call one hop keeps both the check and the list honest.

## Rule 212 — no org column means no RLS, whatever the session is

`operations` has no `organization_id`. Its tenant is whoever owns the asset the operation
ran on, which means no policy of the usual shape exists and `get_tenant_db` — the dependency
every handler in the file takes — protects this table not at all.

Four of the router's five handlers relied on it anyway:

    GET  /operations/                    select(Operation)                  every tenant
    GET  /operations/{id}                where(Operation.id == id)          any tenant's
    GET  /operations/{id}/packml-summary where(Operation.id == id)          any tenant's
    POST /operations/{id}/complete       where(Operation.id == id)          any tenant's

The last one WRITES. An authenticated operator could finish another organisation's
production run by id, and the row would record their outcome, their duration and their
PackML rollup, with a 200 in reply.

The fifth handler, `/active`, joins `assets` and filters on the caller's organisation —
under a comment reading "THE TENANT JOIN IS NO LONGER OPTIONAL", added when exactly this
defect was found there. It was fixed on one handler and the other four kept the shape.

That is the lesson worth carrying: **when the fix is a join somebody has to remember, the
next handler will not remember.** All four now go through `_own_operation(id, org)`, so the
shortest way to select an operation in this file is the scoped way.

How it was found is also worth recording. Not by a guard — the tenant guards look for
`get_db` and for unbound sessions, and this router uses `get_tenant_db` correctly
throughout. It surfaced from writing the first test that had ever driven
`POST /operations/{id}/complete`, where a cross-tenant case was added out of habit and
came back 200.

## Rule 213 — keep the redundant predicate, and record that it is redundant

The scoped query carries both a join to `assets` and an explicit
`Asset.organization_id == :org`. Mutation says the predicate is dead weight: delete it and
no test changes, because `assets` is FORCE RLS and the join inherits that filter.

It stays. RLS filtering is a property of the SESSION, and the defect above existed because
someone assumed the session was doing the work — an assumption that was true of every other
table in the file's neighbourhood and false of this one. A handler that is ever moved to
`get_db`, or a query that is ever run from a background task, still returns the right rows.

The rule is not "keep redundant code". It is that when you keep something a mutation cannot
justify, the comment has to say the mutation was run and what it showed. Otherwise the next
reader deletes it as noise — correctly, by the evidence available to them.

## Rule 214 — a gate that can hang reports nothing

`case.call_and_validate()` in the contract suite carried no request timeout. One
unresponsive operation therefore stopped the entire job — and not with a failure naming it,
but with silence: no junit XML, no conformance count, and `contract_ratchet.py` reading
"collected 1 operations" and printing *"Check that the schema still loads and the server
started."* Every visible signal pointed at the wrong thing.

It presents as slowness, which is the reason it survived. A run that is 40 minutes into an
8-minute job looks like a big surface, not a stuck one. The tell was CPU: one minute of it
in the last ten, on a process that should be saturating a core.

`timeout=30` turns that into a 15-minute run over 546 operations that fails one test with
the operation's name on it. Thirty seconds is far above anything this API takes under
generated input, so a hit is a finding rather than a flaky threshold.

The general form: **any long-running check that talks to something else should be asked what
it does when the other side never answers.** The answer "it waits" is a gate that can be
silenced by the thing it is meant to be testing.

## Rule 215 — when a guard refuses your number, measure rather than compute

Raising the without-broker contract floor to 436 left the with-broker floor at 393, and
`test_the_contract_gate_doc_matches_the_gate.py` failed: the configuration that reaches MORE
operations, because a dependency was present, cannot be held to a lower bar than one that
could not reach them.

There were two ways out. One was to write 445-something into the higher slot — arithmetic
dressed as a floor, in a file whose entire purpose is to stop exactly that. The other was to
take the run: seventeen minutes with a broker reachable, **449 of 546**, floor 440.

The measurement paid for itself by correcting the belief that would have justified the guess.
Three documents — this repository's README, the gate's own reference page, and a comment in
the ratchet — described the broker-dependent set as "~20 correct 503s". It is **four**: 449
with a broker against 445 without. The two floors stay separate because the distinction is
real and is probed rather than claimed, but the headroom it buys is small, and that is a fact
about the API rather than an error in either number.

A figure inherited across documents and never re-measured is one defect wearing three hats —
the same shape as `metadata` appearing on nine register entries, and as the operation count
reading 451 in two places and 452 in a third.

## Rule 216 — a foreign key is checked below RLS

`downtime_events.asset_id` is a foreign key to `assets`, and `assets` is FORCE ROW LEVEL
SECURITY. Three shop-floor writes took that id from the caller and never asked whose asset it
was, on the reasonable assumption that the database would refuse a reference the caller could
not see.

It does not. Referential integrity is enforced at a level the policy does not filter, so a
valid id belonging to another organisation was accepted: **org B logged downtime against org
A's machine and got a 201.**

The consequence is easy to under-rate because it is not a leak. Org B cannot READ org A's
asset — the row it wrote lands in org B's own tenancy, carrying a pointer across the
boundary. `/downtime/open` then returns an event whose asset the caller cannot resolve, and
downtime is an OEE input, so the figure it feeds is computed against a machine the tenant
does not own. A tenancy test looking for leaked reads sees none of this.

**Reading is protected; REFERENCING is not.** Ask of every caller-supplied id what proved it
belongs to the caller, and treat "the foreign key would have failed" as true only for ids
that exist nowhere at all.

## Rule 217 — put the hostile shapes in the test and let the library answer

A timezone validator caught `ZoneInfoNotFoundError`. An empty name raises `ValueError`, so
`{"timezone": ""}` answered 500 while every other bad value answered 400 — one of eight
operations the contract gate found returning a bare `internal server error`.

The fix caught `ValueError` as well, and the reasoning behind it was sound: `ZoneInfo` rejects
keys that are not normalized relative paths, and traversal-shaped names raise the same thing.

Then the test found a third. `ZoneInfo("x" * 300)` raises **`OSError: [Errno 63] File name
too long`** — because `ZoneInfo` resolves a name to a FILE, so its failure modes are the
filesystem's, not the timezone database's. That case was in the list because a 300-character
string is what a fuzzer sends, not because anybody predicted the exception.

The general lesson is about where the list comes from. Reasoning enumerates the failures you
have thought of; a test full of hostile shapes enumerates the ones that happen. When a check
wraps a library call, the honest question is not "what can go wrong here" but "what does this
library actually raise", and the cheapest way to answer it is to ask.
