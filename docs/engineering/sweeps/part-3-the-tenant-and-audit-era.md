# Part 3 — the tenant and audit era

Classes 30–54 and rules 22–62. Tenancy taken from the body, from a parameter and conditionally; audit writes with nothing bound; the write surface that had never been walked. The longest stretch, and the one where most of the rules were earned.

*One part of [Defect-class sweeps](../defect-class-sweeps.md), which carries the index of every class and links to the other parts.*

---

## Maintenance mode: a feature that could not work, and the fix that would have made it dangerous

`POST /admin/assets/{id}/maintenance` writes `assets.maintenance_mode`;
`TacticalEngine._is_maintenance_mode` reads it to decide whether a control command may be
dispatched to a machine. `frontend/src/api/assets.ts` calls the endpoint. **The column did
not exist in the schema.**

Three defects, stacked, each hiding the one beneath it.

**1. No column.** The endpoint raised `UndefinedColumnError` and returned 500 on every
call. Nothing in the product could put a machine into maintenance.

**2. The reader failed safe, so nobody found out.** Its `except` returned `True` — *in
maintenance* — with a comment already anticipating the missing column ("the query can also
error on deployments where assets.maintenance_mode doesn't exist"). Failing safe was the
right call and it is exactly what made the gap invisible: every asset looked suppressed,
which is indistinguishable from a working feature nobody had used.

**3. The read could never have worked either.** The body was

```python
row = result.fetchone()
return bool(row and row[0])
```

on `AsyncSessionLocal`, which sets no tenant GUC because nothing here runs behind a
request. `assets` is FORCE ROW LEVEL SECURITY and the app connects as `tenant_user`, a
non-owner, so the policy predicate is NULL and **every row is filtered**. `row` is `None`,
and `bool(None and ...)` is `False`: *not in maintenance*.

So **adding the column alone would have flipped the engine from suppress-everything to
suppress-nothing** — commands dispatched to machines an operator had explicitly locked
out. A migration that looked like completing a feature would have been the most dangerous
change in the sequence. The read had to be fixed in the same commit as the write, and this
is the general shape: *when a fail-safe has been absorbing a defect, removing the defect
releases whatever the fail-safe was hiding.* Check what the safe branch was covering
before you delete its cause.

The reader now has three outcomes rather than two — in maintenance / not in maintenance /
**could not determine** — with the last folded into "do not command" and logged as
`maintenance_mode_asset_not_visible`. It accepts an `organization_id` and binds the GUC
when given, so a caller that can name its tenant gets a real answer; one that cannot gets
a deliberate suppression instead of an accidental clearance. Nothing upstream carries a
tenant today (the feature vector is `asset_id`-keyed from the edge), which is itself worth
recording.

**The write had the class-10 defect too.** It updated by `id` alone — not scoped to the
caller — and ran on `get_db`. Under RLS an INSERT is rejected loudly and **an UPDATE is
filtered silently**: it succeeds having matched nothing. Adding an `organization_id`
predicate was not enough and testing it proved so — the caller's *own* asset came back
404, because RLS had already removed the row before the predicate could match it. The
handler is now on `get_tenant_db` with the rowcount checked, which is the only thing that
separates "done" from "matched nothing".

## Rule 22 — when a fail-safe stops firing, something it was hiding starts happening

A `try/except` that returns the conservative answer, an `or 0`, a `?? []`, a 404 branch
that is reached for two different reasons: each one converts a defect into a survivable
behaviour, and survivable behaviour does not get investigated. Before removing the cause,
work out what the safe branch was standing in for — the fix is complete only when the code
downstream of it is correct too, and the moment of maximum risk is the commit that makes
the error go away.

## Rule 23 — a suppression assertion is satisfied by a broken connection

Four of the new engine tests assert `is True`, and `True` is also what the `except` branch
returns for a database that never answered. Three of them passed on the first run against
`role "placeholder" does not exist` — the engine dials `AsyncSessionLocal` directly and
only the `app` fixture rebinds it at the testcontainer. Rule 21 again, one layer down: any
suite whose assertions are all on the safe side of a fail-safe needs a test that produces
the *unsafe* side through the same path, or it is testing that the code is unreachable.

## The third form: a falsy branch that is an assertion

The sweep for this class began with a phrase — "No trailers found" — and grew a second
detector for a widget that vanishes. `CloudGateway` is the third form, and the most
quietly wrong of the three, because the page renders its error banner **and then
contradicts it**.

With `data` undefined, four values were derived and printed as facts:

| rendered | from |
|---|---|
| `Disconnected` / `Offline` | `status?.connected \|\| false` |
| `Queue Depth 0 items` | `status?.queueSize ?? 0` |
| `mTLS Disabled` | `status?.mtlsEnabled ? … : …` |
| "Mutual TLS is not enabled on this gateway connection." | the same ternary's falsy branch |

Two of them are consequential. **Queue depth 0** says no data is stranded at the edge —
the exact check an operator runs after an outage, and the reading that stops them
looking. **mTLS Disabled** is a security finding, printed under a red shield with a
sentence explaining the consequence, about a link nobody managed to inspect.

The shape to look for is not `?? 0` on its own — it is **a ternary whose falsy branch
states something**. `x ? 'Enabled' : 'Disabled'` is a two-valued answer to a
three-valued question, and it is invisible in review because both branches look like
deliberate handling. A blank would have been safer than either word.

A failed status query means the STATUS is unreadable. It does not mean the gateway is
down, its queue is empty, or its encryption is off — the gateway may be perfectly
healthy while the endpoint describing it is not. Every field is now `known`-gated and
says "Unknown", and the security card says outright that this is *not* a finding that
mTLS is disabled, because a blank beside a security heading still reads as reassurance.

## Rule 24 — an error banner does not immunise the rest of the page

`CloudGateway` handled `isError`. It rendered a clear red notice, and then laid out four
cards asserting the opposite of unknown. Marking the failure and *acting* on it are
different jobs, and a reviewer who greps for `isError` finds the first and concludes the
second. The question to ask is not "does this component handle the error" but "what does
this component still claim while the error is on screen".

## The backend form: an except branch that fills the gap with zeros

The frontend variants of this class coerce `undefined`; the backend variant catches an
exception and appends a plausible-looking row. Both OEE fleet surfaces did it:

```python
except Exception:
    summary.append({..., "oee": 0, "availability": 0, "performance": 0,
                    "quality": 0, "runtime_minutes": 0, "status": "no_data"})
```

Zero OEE is not a null result. It is a machine that produced nothing for the entire
window — the worst number this platform can report about a piece of equipment.

**And the status named the one thing it was not.** `calculate_oee` returns zeros through
the *success* path for an asset that genuinely reported nothing, so this branch only ever
fired when the calculation itself broke. "no_data" was reserved for the case that was not
missing data.

Two consequences beyond the row:

**The fleet mean averaged the placeholders.** `sum(s['oee']) / len(summary)` divided by
every asset including the failed ones, so one broken calculation in twenty pulled the
average down and the plant read as a partial outage. This is the empty-set-average defect
one step removed — the set is not empty, it is full of stand-ins for absence, which is
harder to see and produces a number that looks entirely reasonable.

**The other copy renders to PDF.** `/exports/oee/summary` builds a document that gets
filed, printed and forwarded. Four numeric columns reading "0, 0, 0, 0" have told the
reader the machine was dead before their eye reaches the status column. Those cells are
em dashes now — deliberately not the CSV `_cell` helper, which maps None to `""`: a blank
in a spreadsheet reads as missing, a blank in a printed table reads as an omission and
the reader supplies the zero themselves.

The substitution is keyed on `is None` and never on falsiness, because a genuine 0 is a
finding and hiding it behind a dash is the same defect facing the other way.

## Rule 25 — a qualifier nobody renders is a qualifier that does not exist

Adding `assets_measured` / `assets_unavailable` to the OEE aggregate made
`test_qualifiers_reach_the_frontend` fail, which is the guard doing its job: a caveat the
UI never reads leaves the number rendered bare while the backend believes the caveat is
shown. The honest resolutions are to wire it, to drop it, or — as here — to record that
the field it qualifies is not rendered either, in an exemption that expires by itself the
moment anything renders it. `/oee/dashboard/summary` has no frontend consumer at all; the
dashboard reads `/dashboard/fleet/oee`.

## Rule 26 — a sweep that finds nothing has told you about the sweep

The emptiness sweep reported **zero offenders across the tree** while `StrategicEngine`
sat unguarded, telling anyone whose recommendations had failed to load: *"No pending
recommendations. Check back later for new suggestions from the cloud strategic engine."*
It escaped through two independent blind spots, and neither was visible from the clean
result.

**The length cap.** `EMPTY_PHRASE` matched up to forty characters after "No "; that
sentence runs to about a hundred. A helpful empty state is longer than a terse one, so
the cap bit hardest on exactly the pages that took the trouble to explain themselves —
the third time this pattern has had to be widened, and the first time something was
actually hiding in the gap.

**Proximity found the wrong error branch.** With the cap widened it *still* passed: the
nearest `isError` inside the 2500-character window was `{optimizeMutation.isError ? …}`,
a different mutation in a different card. The chain "contained an error branch" and the
file read clean. The page's own failure banner is a hundred lines above and guards
nothing below it either — rule 24 arriving inside the guard.

The fix is `guardsPosition`: when a JSX expression container OPENS with an error check
(`{someError && …}` or `{someError ? … : …}`) and closes before the empty state, that
occurrence is a banner and does not count. Brace counting, because nesting is precisely
what a regex cannot follow.

**It is deliberately narrow, and the first version was not.** Counting braces from
whatever `{` preceded the match, and defaulting to "does not guard", broke two correct
idioms at once: the `{ data, isError }` of the destructuring, and `isError={q.isError}`
passed as a **prop**, where the guard is the receiving component and position is
meaningless — that one flagged all six Dashboard widgets. Anything that is not the banner
idiom is now assumed to guard, so the rule can only remove a false negative, never
manufacture a false positive.

Three sweeps in this session came back empty. Two of those were true, and each is now
controlled against the real pre-fix file rather than a synthetic fixture — restore the
file from git, watch the guard name it, restore the fix, watch it go quiet. A synthetic
fixture proves the function works; only the real file proves the file-walking around it
does.

`ERPIntegrations` fell out of the same widening: its top-level list query did not
destructure `isError` at all, so a failed load rendered "No ERP integrations yet. Add one
to get started." — an instruction to go and configure something, given to someone whose
integrations could not be read. That file already defined an `EmptyOrError` component and
used it in every sub-panel. Only the first thing on the page skipped it.

**One false positive was found and exempted, not suppressed.** `PredictiveMaintenance`
says "No notification dispatched for this assessment" from `a.notificationDispatched ? …`
where `a` is an already-rendered assessment — the line cannot be reached by a failed
request. `NOT_A_QUERY_EMPTY_STATE` records it with the reason, and three tests keep the
entry honest: the phrase must still exist in the named file, the list must stay short
enough to read, and the pattern must still match the phrase — so the list cannot quietly
describe code that has moved on, or hide a sweep that has narrowed.

## The action side: a mutation whose failure reaches nobody

Every sweep so far was about reads. `useQuery` failures render as emptiness. **`useMutation`
failures render as nothing at all**, and that is worse in one specific way: the user pressed
the button deliberately, so they already expect a change, and no response is
indistinguishable from the instant before the list refreshes.

Nine silent mutations across three files, all of which had `onSuccess` and no `onError`:

**The stale success is the sharpest thing in this session.** `ERPIntegrations`'s
test-connection wrote its outcome into a per-integration map on success only. A failed test
wrote nothing, so the PREVIOUS test's *"healthy: connected"* stayed exactly where it was —
same place, same colour, nothing marking it stale — as the result of a test that had just
failed. The button exists to refresh that claim; the person pressing it is asking the
question again and getting last time's answer. That is not missing feedback, it is a false
one.

**The silent delete is the most consequential.** `AdminPages` deleted a user and said
nothing on failure. "Row still there" is exactly what a successful delete looks like until
the list refetches, so there was nothing to notice — and an admin who believes they revoked
someone's access, and did not, has a security problem they cannot see. `Notifications` had
the same shape for a subscription: an admin who thinks they stopped a webhook has not.

Both files already contained the right idiom and skipped it locally — `AdminPages` uses
`alert` from `useDialog` for its missing-field checks, `ERPIntegrations` has an `onError`
on `analyzeMut` and nowhere else. Rule 18 yet again, and `Notifications` was found *after*
being read for query defects and declared clean: the sweep for one class does not see the
next one.

`ERPIntegrations` also rendered every outcome in the accent colour, so even the failures it
did record were displayed identically to successes. The map now carries `ok` alongside the
text.

## Rule 27 — a window is a guess about code shape; bounds are not

The first version of the mutation sweep looked for `onError` within 600 characters of the
declaration and produced **two false positives out of four files**: `CommandPanel`, whose
`mutationFn` body is long enough to push `onError` past the window, and `AlarmRules`, which
handles failure in a `try/catch` around `mutateAsync`. Both were correct code.

The options object has exact bounds, so the guard counts braces instead, and recognises all
three real idioms: `onError` in the options, `name.isError` rendered by the component, and
`name.mutateAsync` awaited at a call site. It also treats a parse failure as "cannot tell"
and stays quiet — a sweep that turns a parse failure into a finding spends the reader's
trust on noise, and after two or three of those nobody reads the output.

The same lesson had already been paid for once in `failureIsNotEmptiness`, where a 2500-
character proximity window found an unrelated mutation's error branch and cleared a page
that was genuinely broken.

## A round trip that could not close: the maintenance schedule

Chasing the casing seam (`transformRegistry` converts snake_case to camelCase for
registered URL prefixes only) produced a clean result — every client on an unregistered
prefix reads snake_case, or its backend deliberately emits camelCase. But reading the
`/api/v1/maintenance` client to prove that turned up an adapter comment —

```ts
// component reads currentMileage.toLocaleString(); backend only has dueMileage
currentMileage: s?.currentMileage ?? s?.dueMileage ?? 0,
```

— and behind it, three defects in one round trip, each hiding the next.

**Creation always failed.** `create_schedule` raised 400 *"vehicleId is required"* unless
the payload carried `vehicleId`. `_schedule_out` emits the vehicle under **both**
`vehicleId` and `vehicleNumber`, from the same column, and the form sent what it had been
shown. Reading a field out under one name and refusing to accept it back under that name
is a round trip that cannot close.

**`priority` was collected, sent and dropped.** The form offers Low/Normal/High/Urgent;
the panel renders a coloured badge on every row. There was no column, so the handler
ignored it, the serializer never emitted it, and the client's adapter substituted the
literal `'medium'` — **not a member of its own declared union**. Every schedule displayed
the same invented priority whatever the operator chose.

**`currentMileage` was dropped too, and displayed.** The panel printed
`Mileage: {currentMileage}` from `dueMileage` — the odometer at which the service falls
DUE — which a technician reads as where the vehicle is now. The two differ by exactly the
distance left before the service. With neither value present it printed `Mileage: 0`.

Fixed by migration 054 (a real `priority` column), by accepting `vehicleNumber`, by
returning the whole row from create instead of `{id, status}`, and by **deleting**
`currentMileage` rather than manufacturing it — a schedule knows when service is due; it
does not know the vehicle's present odometer.

## Rule 28 — a mock more generous than the wire hides the defect it was built to catch

Every existing test passed. `maintenanceMocks.ts` supplied `currentMileage` and a real
`priority`, because the fixtures were written from the TypeScript type — and the type
described fields the API had never sent. `VITE_USE_MOCK` is set globally in
`test/setup.ts`, so *every* unit and Playwright test ran against those fixtures.

The fixture must be copied from **what the serializer emits**, not from the type the
frontend declares. When the two disagree, the type is the thing that is wrong, and a
fixture built from it will agree with the type forever.

Deleting `currentMileage` from the interface made `tsc` name every place the fabrication
had been propped up — the mocks, the panel, the form — which is the useful direction:
the type system finds the props once the lie is removed from the type.

## Rule 29 — a create that returns `{id, status}` cannot be checked

`create_schedule` returned two fields. A caller cannot tell from that whether what it sent
was stored, which is exactly how a silently dropped `priority` survived in a form that
posted it on every submission. Returning the stored row makes the round trip assertable in
one call — and the test that now pins it (`what was sent is what comes back`) is the one
that would have caught all three defects on the day they shipped.

## Sweeping the whole contract: TS fields the wire never carries

`currentMileage` suggested a general question — *which other fields does the frontend
declare, read and render that no backend source ever emits?* — and it is mechanically
answerable. The sweep builds the backend's **wire vocabulary** (every string key in a
dict literal across `app/`, every model and schema attribute, every `Field(alias=…)`,
each also in camelCase) plus the casing seam's `inAliases` values, then reports every
field declared in `types/*.ts` that is absent from it **and read somewhere in a component**.

Controlled against the real file: with the pre-fix `logistics.ts` and panel restored it
reports `MaintenanceSchedule.currentMileage` and a total of 61; with the fix in place, 60.

**53 after the alias correction**, and the `RepairOrder` cluster is the same defect family
in the same component — the adapter beside `adaptSchedule`:

| rendered | actually | consequence |
|---|---|---|
| `workOrderNumber` | `id.slice(0, 8)` | eight characters of a UUID, as the row heading a technician quotes to a vendor |
| `estimatedCost` … "estimated" | `repair_orders.cost`, `?? 0` | a repair with no cost recorded displayed as **"$0 estimated"** — a free repair, and an estimate nobody made |
| `priority` | `?? 'medium'` | see the enum note below |

Renaming is fine; inventing is not. `title → issueDescription` and `openedAt →
reportedDate` are honest maps onto columns that exist. The two above were not maps.

**Recorded, not fixed:** `repair_orders.priority` is `low | medium | high | critical` and
the TypeScript union is `low | normal | high | urgent`, so two of the four server values
arrive as strings the union does not contain and `getPriorityColor` falls through to its
default. Reconciling the vocabularies is a product decision — which words does the
operator use? — not a mechanical fix. `partsUsed`, `laborHours`, `assignedTechnician` and
`actualCost` have no columns at all; every one is rendered conditionally, so they are
simply never shown. That is a missing feature, not a false statement, and it is left as
one rather than faked.

The remaining ~45 entries are recorded here as a work-list rather than swept in one pass:
each needs the same judgement — is this field renamed, absent, or invented? — and the
three answers have three different fixes.

## The HOS clearance, found a second time in the same component

`hosDriveHoursRemaining` came out of the wire-vocabulary sweep, and it is the most serious
thing this session found.

Migration 042 added `drivers.hos_drive_hours_remaining` and `hos_duty_hours_remaining`
with no default and no backfill. **Nothing in this codebase has ever written to either** —
no ELD sync, no ingestion path, no computation. The model comment states what they were
meant to be (`# 11 - hos_drive_hours_today`) and nothing did the subtraction.

The transportation compliance tab counts a violation as `hosDriveHoursRemaining === 0`.
**`null === 0` is false.** Every driver was counted compliant, every fleet returned zero
violations, and the page rendered a green *"No HOS violations detected"* tick — on the
**success** path, with the data loaded, for DOT-regulated hours.

**This page had already been fixed for this exact class.** The earlier fix covered a
*failed* drivers query — `[]` also produces zero violations — and left the far more common
case untouched: the query succeeds and the field is simply null. Rule 18 in its plainest
possible form, and it took a different sweep to find the second instance.

Three more defects fell out of the same field:

**The list endpoint 500'd on any unreported driver.** `DriverBase` declared
`hos_drive_hours_today: float = 0` while the column is nullable, so `model_validate`
raised on a NULL and the entire `/drivers` response failed — one silent driver took the
page down for the whole fleet. The `= 0` was the sharper half: **a schema default is a
claim about the world just as much as a coalesce is**, and zero hours driven is a clean HOS
record, not an absent one.

**`formatDuration` crashed the tab.** It guarded with `hours === undefined`, and the API
sends JSON `null` — `null === undefined` is false, so it fell through to `null.toFixed(1)`
and threw, taking the whole drivers tab down. Never surfaced because the mock fixtures
supply a number for every driver (rule 28 again).

**`null < 2` is `0 < 2`.** An unreported driver was painted amber — the colour reserved for
one running short of hours — and captioned "N/Ah".

The fix is a derivation, not a default: remaining is computed from the consumed figure that
*is* populated, and stays NULL when that is missing too. A driver who has reported nothing
is unassessable, and inventing "11 hours left" for them clears them just as effectively as
null did.

## Rule 30 — `.test()` on a global regex is stateful, and a guard that uses it is lying

The emptiness sweep's own vacuity check —

```ts
const QUERYING = FILES.filter((f) => QUERIES.test(readFileSync(f, 'utf8')))
```

— uses a `/g/` regex, and `RegExp.prototype.test` advances `lastIndex` and resumes from
there on the next call. Consecutive calls over different strings therefore alternate
between matching and not matching identical content, so the count depended on how many
files preceded each one and how long they were.

It had been passing by luck. Editing four unrelated pages moved enough characters to drop
the count below its threshold and the check failed with nothing wrong in the tree it
guards. A guard whose result depends on iteration order cannot tell you anything about
anything. It now uses `.match()`, and a test asserts the count is the same twice —
because the failure mode is *inconsistency*, which a single run cannot see.

## The costs tab: three of five figures were manufactured in the client

`/maintenance/costs` returns `{ ytdTotal, byCategory }`. The tab renders five figures, so
the client filled the gap:

| rendered | from | what it said |
|---|---|---|
| Total YTD | `ytdTotal` | honest |
| Monthly Average | `ytd / 12` | wrong in every month but December — in February it understates roughly sixfold |
| Per Vehicle | `0` | a fleet whose maintenance costs nothing per vehicle |
| Upcoming (Est.) | `0` | in a **highlighted** box, so it reads as "nothing is coming up" rather than "nobody calculated this" |
| Monthly Cost Trend | `[]` | an empty chart |

Plus `(amount / costs.totalYTD) * 100` for the category breakdown, which is `Infinity`
when the total is zero and renders the literal string **"NaN"** through `.toFixed(1)` —
reachable exactly when a cost breakdown means least.

A figure the server does not send is now absent, and the panel says which ones are not
reported by this deployment. **An absent row prompts a question; a row reading `$0`
answers one** — that is the whole difference, and it is why omitting beats defaulting
every time the value is a measurement rather than a count.

Note the direction of the two hardcoded zeros. Both were written to make a layout look
complete, and both survived review because a zero in a currency column is unremarkable.
That is exactly what makes this class expensive: the fabricated value is always the one
that looks most normal.

## Rule 31 — a guard that derives its expected value from its own input asserts nothing

The wire-vocabulary sweep became a permanent guard, and the first version of it was
vacuous in a way worth recording because it looked completely reasonable:

```python
BASELINE = _declared_but_unsent()      # computed at import, from the current tree
...
new = sorted(_declared_but_unsent() - BASELINE)
assert not new
```

`new` is empty by construction. The guard could never fail, for any tree, ever — it was a
very expensive way of asserting that a set equals itself. Nine tests passed and one of
them was inspecting nothing.

A baseline must be a **literal**, written into the file, so the comparison is against what
was true when someone looked rather than against what is true now. The fix is mechanical;
noticing is the part that isn't, and the tell is that the expected value and the actual
value come from the same function call.

Controlled the only way that means anything: a fabricated field (`inferencesPerSecond`,
declared on a type and read by a component, emitted by nothing) was introduced into the
real tree, and the guard named it. Restored, it goes quiet.

Two other guards in this session had the same shape of problem and neither was caught by
running them — the emptiness sweep reported zero offenders while three pages were broken
(rule 26), and its vacuity check depended on iteration order (rule 30). **Three guards,
three different ways of being confidently wrong.** The only method that has reliably found
these is to break the real tree on purpose and check that the guard notices.

## Maintenance mode, finished: five defects in one feature

The wire-vocabulary sweep flagged `Asset.isInMaintenance`, and finishing that thread closed
the last two of **five independent defects in a single feature**. Worth listing together,
because each one alone would have broken it, and each was individually plausible:

1. **No column.** `assets.maintenance_mode` did not exist. The write endpoint 500'd on
   every call while the frontend called it (migration 053).
2. **The write was not tenant-scoped and did not check its rowcount.** Under RLS an UPDATE
   is filtered, not rejected — it succeeds having matched nothing and returns 200.
3. **The engine's read was blind to RLS.** `bool(row and row[0])` on a session with no
   tenant GUC turns an invisible row into *not in maintenance*, so fixing the column alone
   would have flipped suppress-everything into suppress-nothing.
4. **`AssetResponse` never declared the field.** FastAPI drops whatever the schema omits,
   so with the column present, the write working and the engine honouring it, **no client
   could see which assets were out of service.** The frontend's own name for it,
   `isInMaintenance`, had never been sent by any endpoint under any spelling.
5. **The one call site sent the flag where the server does not look.**
   `setMaintenanceMode` posted `{ inMaintenance }` as a JSON body; the endpoint declares
   `enabled: bool = True`, a scalar FastAPI reads from the query string. The body was
   discarded and the default took over, so **calling it to take an asset OUT of maintenance
   put it IN** — a 200, the opposite of the requested effect, and a response reading
   "Game-theoretic engine commands are blocked".

## Rule 32 — a feature is not one thing, and finding one defect in it says nothing about the rest

Four separate sweeps found these, weeks of work apart: an unchecked-UPDATE audit, a
fail-safe audit, a contract sweep in one direction, and reading a client while chasing
something else. Each fix looked complete at the time. What actually distinguishes them is
that every one sits on a different *seam* — schema, write, read-under-RLS, response model,
call site — and a sweep is organised by shape, not by feature. **When a sweep finds a defect
in something, walk the whole path by hand before believing the feature works.** The column,
the writer, the reader, the response model and the caller are five different places to be
wrong, and this feature was wrong in all of them.

The corollary is about direction. Defects 4 and 5 point opposite ways — the server not
sending what the client reads, and the client not sending what the server reads — and
neither sweep could have found the other. A contract has two ends and needs checking from
both.

## Every geofence alert read "Violation"

Triaging the wire-vocabulary baseline table-aware — *does the entity's own table have a
column that could feed this field?* — separated the entries into three real fixes: rename
the producer, expose an existing column, or delete the field. The geofence cluster was the
first kind, and the largest single finding left on the list.

`GET /geofencing/alerts` emitted `zoneId`, `eventType` and `createdAt`. The TypeScript
`GeofenceAlert` declares `geofenceId`, `alertType` and `timestamp`. **No overlap on any
field that matters**, and nothing in the frontend read the names being sent — the producer
and its only consumer had drifted completely apart.

`alertType` is the one that did damage. `GeofencingPanel` renders

```tsx
alert.alertType === 'entry' ? 'Entered' : alert.alertType === 'exit' ? 'Exited' : 'Violation'
```

An undefined field matches neither branch, so the last one fires — and the last one is an
assertion. **Every alert read "Violation"**: routine authorised entries, exits, everything.
That is the sixth time in this sweep that a falsy ternary branch has stated something it had
not earned, and it is now the most reliable single shape to grep for in this codebase.

`geofenceName` and `vehicleNumber` were undefined too, so a row could not say which zone or
which vehicle. Both live on other tables and are now resolved in two batched queries.

**Three separate corrections were needed to get that right**, and the second and third both
came from running things rather than reading them:

*The N+1 guard was vacuous.* It attached `before_cursor_execute` to
`app.db.database.engine` — but `conftest` builds its own `test_engine` and rebinds every
module's `AsyncSessionLocal` to it, so nothing was ever recorded and `len([]) <= 1` passed
for any implementation. A deliberate per-row-query mutation did not fail it. Fixed by
listening on the `Engine` **class**, which catches every instance, plus an assertion that
*something* was recorded at all.

*The batching 500'd on real data.* `geofence_alerts.zone_id` and `.vehicle_id` are
`String(36)` while the tables they reference have UUID primary keys, so `IN (…)` against a
free-form string raises `DataError: invalid UUID`. Integrations do write device identifiers
there — the existing tenant-isolation suite seeds `'VEH-a'`, which is what caught it. Only
parseable UUIDs are looked up now; the rest resolve to `None`, because a device reference
that is not an internal id is not a reason to fail the whole list.

## Rule 33 — fixing a correctness defect is where performance and robustness defects get introduced

The join that made the alert readable also added an N+1 and a 500-on-real-data, and neither
was in the code being fixed — both were in the fix. The correctness change is the moment the
code is least reviewed, because attention is on the defect. Run the **whole** suite, not the
new file: the isolation suite caught the crash, and the new file's own N+1 guard had to be
repaired before it could catch anything.

## Triaging the rest, table-aware: three fixes, not one

The wire-vocabulary baseline is a list of names, and a name alone does not say what to do
about it. The question that makes it actionable is **does this entity's own table have a
column that could feed the field, or a reference to one that does?** — and it sorts every
entry into one of three fixes:

| answer | fix | example |
|---|---|---|
| the producer uses a different name | rename the producer | `eventType` → `alertType` |
| a column or reference exists | expose it | `trailerLicensePlate` through `current_trailer_id` |
| nothing could ever feed it | delete the field | `workcellName` on a dock door |

The yard cluster needed **two of the three at once**. `dock_doors.current_trailer_id` and
`dock_appointments.trailer_id` both reference `yard_trailers`, where the plate lives — so the
door card was printing an empty line exactly where the trailer occupying the dock should be
named, and that is an expose. `workcellName` sat next to it and is a delete: `dock_doors` has
no workcell relationship of any kind, so the card was rendering a blank for an association
this schema does not have.

**The response model nearly ate the fix, again.** `GET /yard/dock/doors` declares
`response_model=List[DockDoorResponse]`, so resolving the plate in the handler without
declaring it on the schema would have deleted it from every response and changed nothing
visible — the same trap that hid `maintenance_mode` on `AssetResponse`, hit twice in one
session. Worth stating as a habit: **after adding a field to a handler, check what the
response model does to it.**

**And the fixture found a second, unrelated 500.** `dock_appointments.meta_data` is
`Column(JSON, default={})` — a *Python-side* default, so a row written by a migration, a
seeder or a raw INSERT holds NULL, the ORM hands the field an explicit None, and
`metadata: Dict[str, Any]` rejected it. `GET /yard/dock/appointments` answered 500 with
"metadata: Input should be a valid dictionary", an error naming our own schema rather than
the row. `DockDoorResponse` carries a long comment describing this exact failure being fixed
for `equipment_capabilities`; the appointment schema beside it was left alone. Rule 18, and
the fixture that caught it was not looking for it.

## Rule 34 — a global vocabulary passes a name that is wrong for the entity holding it

`DockDoor.workcellId`, `supportedEquipment`, `hasLoadingEquipment`, `maxWeightCapacity`,
`currentAppointmentId` and `estimatedReleaseAt` are all declared on a table that carries
none of them — `dock_doors` has `equipment_capabilities` as JSON and nothing else — and the
wire-vocabulary sweep reports **none** of them. Its vocabulary is global: a name that exists
as a column on *any* table passes, whatever entity declares it.

That is a deliberate trade (a per-entity vocabulary needs a type-to-table mapping the sweep
does not have), but it bounds the claim. The sweep finds names nothing anywhere produces; it
does not find names produced *somewhere else*. Auditing one interface against its own table,
end to end, is a different and narrower job — and it is where the rest of `DockDoor` lives.

## "Fleet Status (GeoTab Live)" — six blanks under a claim of live data

`geoTabApi.getFleetSummary` declared a return type of
`{ totalVehicles, vehiclesMoving, vehiclesIdle, vehiclesOffline, avgSpeed,
totalDistanceToday, fuelConsumedToday }` and returned `response.data` untouched.
`/geotab/fleet/summary` sends `total_devices, active_devices, total_drivers,
drivers_on_duty, drivers_driving, exceptions_today, hos_violations_today,
average_fuel_efficiency, total_miles_today`.

**Not one field overlapped.** Every figure on the card was `undefined`, two of them printed
beside bare units — `" mph"`, `" mi"` — which reads as a measurement rather than an absent
one. The declared shape was plausible enough that nobody compared it to a response.

**And the payload says it is simulated.** Every GeoTab response carries `simulated: true`,
`data_source: "geotab_simulator"` and the sentence *"Not measured from a device and not valid
for DOT/ELD compliance reporting"* — stamped server-side precisely so a consumer could tell.
Nothing read it, and the heading said **Live**. That is rule 25 on the most sensitive data in
the product: a qualifier nobody renders is a qualifier that does not exist.

The card now shows only the figures the endpoint reports, renders `—` rather than a bare
unit for the ones it does not, and labels the panel *simulated* with the server's own warning
when the flag is set. `avgSpeed` and fuel *consumed* were deleted: the server reports fuel
*efficiency*, which is a different quantity.

## Rule 35 — name the field after the wire, not after the nicer word

The first version of this fix mapped `active_devices` → `vehiclesActive` in the client, and
the wire-vocabulary sweep immediately reported `vehiclesActive` as unsourced — correctly, in
the sense that no server file spells it. The sweep cannot tell a client-side rename from a
fabrication, and neither can a reader six months later.

Renaming the TypeScript fields to `totalDevices` / `activeDevices` / `totalMilesToday`
removed the adapter entirely. It is also more honest: the endpoint counts **devices**, and
calling them vehicles was part of what made the original mismatch invisible — the shape read
plausibly while sharing no field name with any response. One name per concept means nothing
to drift and nothing for the sweep to report.

The same argument settled the geofence rename in the other direction: there, the producer had
the odd names and no consumer, so the producer moved. The rule is not "always change the
client" — it is "one name per concept, chosen where the concept actually lives".

## Working the list down: 53 → 32

Nine findings so far from the wire-vocabulary baseline, and the distribution is the useful
part. **Only three of the nine were false claims**; the rest were information the product
collected, or could have collected, and could not show:

| finding | fix | what the user saw |
|---|---|---|
| `currentMileage` | delete | the DUE odometer labelled as the current one |
| `workOrderNumber` | delete | eight characters of a UUID as a work-order number |
| cost figures ×3 | delete | "$0" per vehicle and upcoming, "monthly average" = YTD ÷ 12 |
| `Asset.isInMaintenance` | expose | nothing — no client could see maintenance mode at all |
| geofence names ×3 | rename producer | **every alert read "Violation"** |
| yard plate ×4 | expose | a dock door that could not name the trailer at it |
| `workcellName` ×2 | delete | a blank line for an association the schema lacks |
| fleet summary | rename client | six blanks under "GeoTab Live", two beside bare units |
| device ids ×2 | rename both ways | a "GeoTab Device ID" row that never appeared |
| carrier contact ×2 | delete | a "Contact" heading above two empty lines |

**The distribution matters more than the count.** A sweep that finds thirty "missing field"
entries and treats them all as bugs to fix would have added columns for carrier contacts and
a workcell relationship for dock doors — inventing product scope from a lint result. The
table-aware question (*does this entity's own table have a column, or a reference to one?*)
is what separates the three answers, and **delete was the most common one**.

Two entries stay on the list deliberately and are worth naming, because they look like
findings and are not: `LogisticsOverview.todayAppointments` is computed client-side by
filtering the appointments list, and the `Location` contact pair is a frontend-only shape a
caller may populate itself. The sweep cannot distinguish either from a fabrication, which is
exactly why the list is a baseline rather than a defect count.

**One gap recorded rather than closed:** carrier contact details have nowhere to live in this
schema. That is a real product hole — you cannot phone a carrier from this system — but
filling it is a migration plus CRUD plus data entry, not a sweep fix.

## Rule 36 — a request field checked against a response vocabulary is a false positive by construction

`ErrorListParams.sort` sat on the baseline as an unsourced field. It is not: `list_errors`
declares `sort: Literal["count", "last_seen", "first_seen"] = "count"` and the client sends
it correctly.

The sweep's vocabulary collected `AnnAssign` targets — class attributes — but function
**parameters** are `ast.arg` nodes, so every query parameter an endpoint accepts was
invisible to it. And a `*Params` interface on the frontend describes a **request**, whose
valid names are exactly those parameters. The sweep was checking what the backend *consumes*
against what it *produces*.

Fixed by adding parameter names to the vocabulary. Only one entry moved, so the gap was
narrow — but the cost of that class of false positive is not the entry, it is the reader who
investigates a working field and concludes the sweep is noisy. **A sweep gets one or two
false positives before people stop reading its output**, which is why every one found here
is removed at the source rather than exempted.

Nine of ten entries investigated so far were real. That ratio is the only thing that makes a
36-rule document worth keeping.

## FS-207: the CI quarantine now expires

`ci-cd.yml` passes three `--ignore` and two `--deselect` flags to pytest. Every one is
justified — the ignored files fail at **collection**, so without them the whole backend job
dies before running anything — but a flag in a workflow file has no expiry, no owner, and no
record of what would have to be true to remove it.

That is a suppression, and this document is largely a record of what suppressions do: they
convert a defect into a survivable condition, and survivable conditions are never revisited
(rule 22). Six tests were being skipped by a mechanism with no way to notice.

`test_ci_quarantine_expires.py` asserts four things:

1. **The list and CI are the same set** — in both directions. A new `--ignore` added to the
   workflow with no entry in the list fails the test, which is the only thing standing
   between "we skipped one broken file" and a job that quietly stops running half the suite.
2. **Each quarantined file still fails to collect.** A stale quarantine is worse than none:
   it hides a working test *and* makes the whole list untrustworthy. Run in a subprocess,
   because a broken import in-process would take the guard down with it.
3. **Each deselected test still fails.** Same question, one level finer; these fail on an
   assertion rather than at collection, so they can be run directly.
4. **The expiry has not passed**, and no expiry is more than a year out — a date far enough
   away is the same as no date.

Each entry carries the owner and the precise fix. The three collection errors are import
mismatches in the intake lane's scenario builders: two import `build_document_scenarios` /
`build_image_scenarios` where the modules export `build_scenarios`, and the third expects a
`CrossFileScenarioBuilder` class in a function-based module. **The code was deliberately not
touched** — that lane is still building those assertions, and renaming the import would
surface a body of expectations I would then be tempted to edit. Recording the mismatch makes
the owner's change a two-minute one; making it myself would make it somebody's afternoon.

Controlled both ways: an undocumented `--ignore` added to the real workflow is named, and a
back-dated expiry fails with the owner and the fix. **And the guard rejected its own first
draft** — one entry's `fix` field said only "as above.", which the `test_every_entry_says_who_and_how`
assertion refused as too thin to act on.

## The per-interface audit: DockDoor against its own table

Rule 34 says the global sweep credits a name that exists as a column on *any* table, so it
cannot tell whether a field belongs to the entity declaring it. `DockDoor` is what that
blind spot was hiding. The interface declared:

| declared | reality |
|---|---|
| `supportedEquipment: string[]` | the column is `equipment_capabilities`, a JSON **object** |
| `hasLoadingEquipment: boolean` | no column |
| `maxWeightCapacity: number` | no column |
| `currentAppointmentId` | no column — appointments reference doors, not the reverse |
| `estimatedReleaseAt` | no column, and **it rendered**: "Release: HH:MM" |

`dock_doors` carries `door_number`, `door_type`, `status`, `equipment_capabilities`,
`current_trailer_id`, `last_occupied_at` and `is_active`. Nothing else. Only
`estimatedReleaseAt` was reported by the global sweep, and only because no other table has a
column by that name.

**`last_occupied_at` exists and is not the same thing.** It records when the door was last
occupied — a fact about the past — where `estimatedReleaseAt` is a prediction. Mapping one
onto the other would have been the `currentMileage` defect exactly: the right number under
the wrong label, which is how that one shipped. The card shows "Last occupied" now.

The audit is pinned as an assertion rather than a one-off: `DockDoorResponse`'s declared
fields must all be columns of `dock_doors`, minus one explicitly-listed denormalised value
the handler resolves. That generalises to any response model, and is cheaper than the global
sweep because it needs no vocabulary — just the table.

## Rule 37 — prose about a defect gathers around the defect, so strip comments in every source assertion

`assert "currentMileage" not in logistics_ts` has now failed twice against **fixed** code.
First the comment explaining the deletion contained the word; then, months of work later in
the same session, a comment in the DockDoor audit cited `currentMileage` as the precedent for
*not* mapping `last_occupied_at` onto `estimatedReleaseAt`.

Method rule 14 said a substring match on source is satisfied by prose. Three occurrences in
one file say something stronger: **the prose density around a defect is highest exactly where
the assertion looks**, because that is where the explanation goes. Strip comments in every
source-text assertion as a matter of course, not when one fails.

## The narrow question beats the broad one: response models against their own tables

The wire-vocabulary sweep asks *does any backend file produce this name?* — a broad question
with a fuzzy answer, which is why it credited four of `DockDoor`'s five phantom fields (rule
34) and why it needed a request-vs-response correction (rule 36).

`test_response_models_match_their_tables.py` asks a narrow one instead: **is this field a
column of THIS entity's table, an alias of one, or an explicitly-listed value the handler
resolves?** No vocabulary, no heuristics, and the pairing is mechanical
(`DockDoorResponse` ↔ `DockDoor`). It covers 34 response models and it is *stronger* on every
model it covers, at the cost of covering nothing else.

It found **nothing new**, which is the result worth recording: the DockDoor audit was the last
of them, and 34 models are now proven rather than unexamined.

Two exceptions, both listed with who fills them: `DockDoorResponse.trailer_license_plate`
(denormalised by the handler in one batched query) and `TaskColumnResponse.task_count`
(computed with a batched `GROUP BY`). A third class needed crediting rather than exempting —
fourteen models expose the `meta_data` column as `metadata` through `AliasChoices`, and a
guard that reported all fourteen would have been ignored within a day.

**Both directions of the response-model trap are now guarded.** Declaring a field with no
source fails this test; failing to declare a field the handler resolves fails the per-feature
test that resolved it. The two defects look nothing alike and cost the same.

## Rule 38 — prefer the check with a definite answer, even if it covers less

Given a choice between a sweep that inspects everything approximately and one that inspects
part of the system exactly, the exact one is worth more per line. The broad sweep has produced
nine findings and needed three corrections (rules 34, 36, and its own vacuous baseline at rule
31); the narrow one was right first time and its false-positive surface is a two-entry list.

Breadth is not free: every heuristic that widens coverage also widens the space of results
nobody can act on, and a sweep is only useful while people still read its output.

## Fourteen handlers asked the caller which tenant to write to

The mirror of rule 38 — request models declaring fields no column holds — came back almost
clean: one finding, `UserCreate.password`, which is correct by design (hashed into
`password_hash`, never stored). But that clean result is misleading, and the reason matters
more than the result.

**The maintenance-schedule `priority` defect went through `payload: Dict[str, Any]`.** Twelve
route handlers take an untyped dict body, so there is no schema to check what they accept or
silently drop — the request-model sweep cannot see any of them. A sweep coming back clean over
the part of the system that *has* schemas says nothing about the part that does not.

Reading one of those handlers found this:

```python
organization_id=payload.get("organization_id")   # POST /transportation/vehicles
```

A guard written for that shape then found **thirteen more**, all identical
(`organization_id=data.organization_id`), plus `initialize_registries`, which did
`request.organization_id or current_user.organization_id` — preferring the client's value with
a fallback to the right one, so the fallback made it look safe.

**Thirteen of the fourteen were saved by row-level security, and one was not.** On an
RLS-covered table a FOR ALL policy's USING clause acts as the INSERT's WITH CHECK, so the
database refused the cross-tenant write and the caller got a 500 — bad error handling, not a
breach. `pg_class.relrowsecurity` is **false** for `vehicles`: migration 051's loop does not
cover it, nothing stood between the body and the row, and a create naming another organisation
succeeded. The mutation test confirms it.

That is the argument against leaning on RLS. Thirteen handlers were wrong and survived because
a policy caught them; the fourteenth was wrong in exactly the same way and shipped the defect,
and **nothing in the handler said which was which**.

## Rule 39 — six hand-fixes and no guard is a class that will come back

This shape had already been removed by hand from the yard trailer list, the dock doors, the
dock schedule, the maintenance schedule, the geofence zones and the dashboard overview. Each
carries a careful comment explaining *"From the TOKEN, never the payload"*. Fourteen more
instances were sitting in the same three files.

A comment records a fix; only a guard prevents the next one. The moment a defect is fixed for
the *second* time, the fix to write is the check — and the AST is worth the extra work over a
grep, because `organization_id=organization_id` and `organization_id=data.organization_id`
differ only in the value expression, and a substring search matches both plus every comment
explaining the defect (rule 37).

## Rule 40 — never act on truncated diagnostic output

The guard's first run printed thirteen offenders; `head -10` showed nine. Nine were fixed, the
guard was re-run, and four "new" ones appeared — which briefly looked like the fix having
caused them. They had been there all along, below the cut.

Pipe a guard's output to `cat`, or count the lines before believing the list is complete. This
cost one confused re-run here; on a longer list it would have meant shipping a partial fix and
believing it whole.

## Migration 055: the table that fell between two migrations

`vehicles` was the only fleet table without row-level security, and that is not a coincidence
about `vehicles` — it is what made it the one handler out of fourteen whose tenant-from-body
defect actually wrote a cross-tenant row instead of failing with a 500.

How the gap happened, and it is worth recording because it will happen again: 011 covered the
core tables. 033 extended that. 051 was written for *"the four fleet/maintenance tables that
had none"* and named them explicitly. `vehicles` arrived in 025 — too late for the first two,
not on the third's list. **A migration that enumerates its targets protects exactly those
targets, and the next table to arrive is unprotected by default.**

Migration 055 closes it, in the order 051 insists on: application layer first, policy second.
Verified before writing it — all seven functions that query `Vehicle` across `app/api` and
`app/services` already run on `get_tenant_db`, so no read was about to start returning zero
rows. `organization_id` is `varchar` here, as on 051's four, so the policy compares text with
no `::uuid` cast; copying 011's cast would raise on every row and leave the table looking
protected while every query against it errored.

**The change was caught by a guard the previous author wrote for exactly this.**
`test_vehicle_tenant_isolation_realdb.py` asserted `relrowsecurity is False` — recording that
the explicit filter was the *only* protection — with a failure message reading: *"vehicles now
has RLS enabled — good, but this test's premise no longer holds; check whether the sibling
logistics tables were covered too."*

That is a test written to fail when its own premise expires, firing across authors and months
apart, and handing the next person the exact question to answer. It is the same mechanism as
the CI-quarantine expiry and the pinned `get_db` debt counts, and this is the first time in
this session one of them has caught *me*.

## Rule 41 — a migration that enumerates its targets leaves the next arrival unprotected

011, 033 and 051 each named the tables they covered. Every table added afterwards starts
outside every policy, and nothing says so — `relrowsecurity` is simply false, which is
indistinguishable from a deliberate exemption.

The durable fix is not another enumerating migration. It is a test that asserts **every table
carrying an `organization_id` column has a policy**, so a new table fails the suite the day it
lands rather than the day someone reads a handler carefully. That is
`test_every_tenant_table_has_a_policy.py`, and running it for the first time was informative:

**61 tenant tables. Six with no policy, five with a policy that is not FORCEd.**

| state | tables |
|---|---|
| no RLS, exempt by necessity | `users`, `api_keys` — read *before* a tenant is known, so a policy keyed on `app.current_org_id` would lock out login |
| no RLS, real gap | `error_events`, `edge_agent_status`, `notification_subscriptions`, `notification_deliveries` |
| RLS without FORCE | five `erp_*` tables |

The unFORCEd ones are the more dangerous state, and `app/api/erp_integrations.py` already says
why in a comment: its background sync *"appeared to work only because no ERP table has FORCE
ROW LEVEL SECURITY and the dev connection owns them"*. `relrowsecurity = true` on those tables
reads as protected while the only connection that matters is exempt.

**None of the nine is closed here, deliberately.** Each needs a migration plus an audit of
every query against that table — application layer first, policy second, the order 051
insists on. `error_events` is written by an ingestion path with no user context;
`notification_deliveries` by a dispatcher running as a background task; the ERP tables by a
sync that may or may not bind a GUC on every path. Enabling FORCE on `users` without tracing
every auth query is how you take down login. So the baseline records each with **what closing
it requires**, and the guard's job is that the list cannot grow.

The two permanent exemptions are marked `EXEMPT BY NECESSITY` and a test asserts the count of
*real* gaps separately, so the two kinds cannot blur into each other over time — which is what
turns a gap list into an approval list.

## The notification router: a conditional tenant filter, four times

Auditing `notification_subscriptions` — one of the four tables the policy guard recorded as
having no RLS — to see whether a policy could be added found the reason it mattered. Four
defects in one router and its service, all the same shape:

```python
org = getattr(current_user, "organization_id", None)
stmt = select(...)
if org is not None:
    stmt = stmt.where(... == org)
```

**A user whose `organization_id` is NULL had the filter skipped and read everything.** Absence
read as unrestricted access — and precisely the case this codebase's own `get_tenant_org_id`
exists to refuse: it raises 403 there and its docstring explains *"we fail closed rather than
fail open"*. A local `_org` helper reimplemented the same idea with the opposite default, in a
router whose tables have no policy to fall back on.

| where | consequence |
|---|---|
| `list_subscriptions` | every tenant's subscriptions |
| `delivery_log` | every tenant's **alarm titles and detail text** — the most specific operational information in the system |
| `delete_subscription` | **no tenant clause at all**: any authenticated user could delete any tenant's subscription by id |
| `_load_rules` (dispatcher) | every tenant's subscriptions **dispatched to** — an outbound delivery of one tenant's alarm to another's webhook, Slack or mailbox |

The delete is the live destructive one: the endpoint's `rowcount == 0 -> 404` check already
existed and was measuring the wrong thing — it proved a row had been deleted, not that it was
yours.

**The dispatcher one is latent and worth separating.** Both callers pass a real organisation
today (the test endpoint and the RUL notifier), so the None path was unreachable. But
`organization_id` is `Optional` with a `None` default, so the next caller to omit it inherits
the fan-out and nothing in the signature says so. Fixed by refusing rather than by hoping.

Every handler now depends on `get_tenant_org_id` and scopes unconditionally. The RLS gap on
these two tables stays open: the handlers use `AsyncSessionLocal` and bind no GUC, so a FORCEd
policy would empty every read — the audit the baseline asked for turned out to be the
application layer itself, and that is now done. The migration is the next step, not this one.

## Rule 42 — a test asserting emptiness must be given something to find

`test_the_helper_is_strict_even_when_called_directly` called `_load_rules(None)` and asserted
`[]`. It omitted the fixture that seeds subscriptions, so the table was empty and the assertion
held whatever the filter did. Restoring the fan-out did not fail it.

The mutation check is the only reason that surfaced — the test passed, read sensibly, and
inspected nothing. This is rule 21 in its most ordinary clothing: not a clever regex or a
proximity window, just a fixture left off a parameter list. **Every negative assertion needs a
positive premise, and for a database test that means rows.**

## The second variant: a client-supplied tenant *parameter*

The body-tenant guard was clean, so the class looked closed. It was not — the guard checks for
a tenant **assigned** from a request, and eight handlers were **receiving** one as a query
parameter instead:

| handler | shape |
|---|---|
| `geotab.py` × 6 | `organization_id: Optional[UUID] = None`, on `Depends(get_db)` |
| `operations.get_active_operations` | optional param, and the tenant join only happened *if* one was sent |
| `yard.get_detention_alerts` | optional param, filter applied only when present |

Every one was **Optional**, which is the dangerous half: a request that simply omitted the
parameter filtered by nothing at all. Whether that leaked depended entirely on whether the
table carried a policy — the same coin-flip that decided the fourteen body-tenant handlers.

**The geotab six also escaped the existing `get_db` guard**, and the reason is instructive:
that guard inspects a handler's own body for references to RLS-protected models, and these
handlers pass `db` to `geotab_service` and query nothing directly. An indirection of one
function call was enough to hide six handlers from a check written specifically to find them —
rule 34's shape again, in a different guard.

Their failure mode was the empty one rather than the leaky one: `get_db` binds no tenant GUC,
so the policy filtered every row and those endpoints returned nothing to anybody, including for
their own organisation. `geotab.py` had already been *removed* from the `get_db` debt list when
`get_fleet_summary` was fixed — the file was marked done with six handlers still wrong.

`workcells.get_organization` is the one legitimate case and stays: `GET
/organizations/{organization_id}` must accept the id, and it compares against the token and
404s. It is allowlisted with that reason, and a further test asserts the comparison still
exists — an allowlist entry that claims a handler validates its input has to be checked, or it
is just a hole with a docstring.

## Rule 43 — a guard proves the absence of the shape it models, not of the class

Three guards have now been written for one class — tenant chosen by the caller — and each was
clean while the next variant sat in the same three files:

1. `organization_id=payload.get(...)` — assignment from a body. **14 handlers.**
2. `organization_id: Optional[UUID] = None` — a query parameter. **8 handlers.**
3. `if org is not None: stmt = stmt.where(...)` — a filter applied conditionally. **4 handlers.**

All three are "the caller decides which tenant", and no single check saw more than one of them.
After writing a guard, the useful question is not *did it pass* but **what shape does it model,
and what else could express the same defect?** Each variant here was found by reading code the
previous guard had just declared clean.

## Rule 44 — a hand-maintained number in prose is a claim that will be wrong

The README stated "206 backend test files". The measured figure was 201. Nobody lied: the
number had been incremented by hand at each milestone and drifted, the way every hand-maintained
count does. Two other claims in the same paragraph had drifted the same way — the rule range said
21–38 while the doc had reached 41, and the class count said thirty-seven while the table had
grown past it.

The method-rules index had drifted **three separate times**: rules 22–27 were written as
sections while the numbered list stopped at 21, then 28–31, then 33–43. Each repair was by hand,
which is precisely the situation rule 39 describes — a comment records a fix, only a guard
prevents the next one. `test_method_rules_are_indexed.py` now asserts the list is contiguous
from 1, that every `## Rule N` section has a list entry and vice versa, and that the README
cites the real range.

**Which numbers deserve a guard and which do not.** A rule range and a class count change rarely
and mean something, so they are worth asserting. A test count changes on every commit — pinning
it would make every new test fail the suite, which converts a documentation nicety into an
obstacle. Those stay hand-written and are re-measured at each milestone rather than trusted;
this document's own counts were re-measured to write this paragraph, and two of the three were
wrong.

Writing the guard also required scoping care worth recording: several prose sections in this file
enumerate with the identical `1. **…**` formatting — the five maintenance-mode defects, the four
things the CI-quarantine guard asserts — so a file-wide regex reports duplicate rules 1–5 and is
useless. The check reads only between the list's heading and the next `---`, and a separate
assertion proves that scoping is narrower than the whole file.

## Migration 056: closing two of the four recorded gaps

The policy-coverage baseline recorded `notification_subscriptions` and
`notification_deliveries` as REAL GAPS, and each entry said what closing them required: *"a
check of the dispatcher, which reads subscriptions from a background task with no request
behind it."* Doing that check found four defects rather than a clean bill (see the section
above), and fixing them was the actual precondition — every session in that router was an
unbound `AsyncSessionLocal`, so a FORCEd policy would have **emptied every read** instead of
protecting anything.

All six sessions now go through `core.tenant.tenant_session`, which binds the GUC and
re-asserts it per transaction, and migration 056 adds the policy. Two of the four real gaps are
closed; the guard's own staleness check named them for removal from the baseline, which is what
a baseline is for.

**The migration was wrong on its first run, loudly.** It omitted the `::uuid` cast and the whole
chain failed to build the test schema: `operator does not exist: uuid = text`. The ORM declares
`Column(UUIDString(), …)`, which reads like a varchar — and genuinely is one on the tables in
051 and 055 — but `022_notifications.sql` declares `organization_id UUID`. **The DDL is the
authority on a column's type, not the model**: a custom SQLAlchemy type can render as either.
Better to be loudly wrong than quietly wrong here — a policy comparing incompatible types raises
on every row rather than silently matching none.

## Rule 45 — a module-level copy of a patched name is a defect waiting for a new caller

`tenant_session` held `AsyncSessionLocal`, captured by `from app.db.database import …` at
import. The test harness rebinds that name **per module**, sweeping `sys.modules` for anything
carrying the attribute — and whether `app.core.tenant`'s copy is among the rebound ones varies
by test.

That was invisible for as long as the helper was only reached through the `get_tenant_db`
dependency, which the suite overrides wholesale. Pointing a **service** at it — the notification
dispatcher — surfaced it instantly as one failing RUL test whose error had been swallowed into a
warning log: `role "placeholder" does not exist`.

The helper now looks the name up on `app.db.database` at call time. There is one binding that
matters and it reads it, instead of holding a copy that may or may not have been patched.

**And the first test for this was too weak.** It compared engines, which passed under the
mutation as well as the fix — because in that test's context the module's copy *happened* to be
the patched one, and the entire defect is that this varies. The test now poisons
`app.core.tenant.AsyncSessionLocal` with a maker that raises and asserts `tenant_session` still
works. Simulate the broken state rather than hoping the test runs in it.

## Class 43: a scoped read against a column the write path never fills

`GET /api/v1/edge/fleet` backs the `/admin/collectors` page. It filtered on
`EdgeAgentStatus.organization_id` — and `POST /api/v1/edge/heartbeat`, the only writer of that
table, **never set that column**. Nothing else in the tree did either; the only three
occurrences of `organization_id` in `app/api/edge_fleet.py` were the two read filters and a
comment.

So the column was NULL on every row ever written, `NULL = '<uuid>'` is NULL, no row could
satisfy the predicate, and the fleet page was **empty for every tenant in every deployment since
the endpoint was written**. `/fleet/{agent_id}` 404'd for the same reason. An operator reads
that as "no agents are enrolled." The frontend even says so in as many words: *"No edge agents
have reported yet. Agents appear here once they enroll and send a heartbeat."*

**The filter was not the mistake.** It was added as a security fix, and the comment above it
still explains why: the read used to be unscoped, so every authenticated user saw every tenant's
agent ids, versions, certificate expiry and buffer depths. That fix was right. It scoped a read
against a column the write path never populated, and so converted a leak into a permanent
emptiness — and nothing failed, because there was no test on either endpoint. The only edge
fleet tests covered the pure liveness helper, which needs no database.

### The obvious fix would have been a hole

An agent's tenant belongs in its certificate: already verified, already the identity the
heartbeat trusts. But `sign_csr` did `.subject_name(csr.subject)` — it copied the CSR's entire
subject into the signed certificate and validated only the CN. Every other attribute was
client-supplied and came back CA-signed, indistinguishable from a server assertion.

Reading the organisation out of that subject would have been **the tenant-from-the-body defect
wearing a certificate**, and worse than the original: durable for the certificate's lifetime and
carrying the CA's signature. The CA now builds the subject itself, from the agent id it checked
and the organisation the *server* chose; anything else in the CSR is discarded. The guard
asserts the whole subject, not just the O — `{CN, O}` and nothing else — so the next attribute
somebody starts trusting is covered before it is trusted.

Enrolment decides the organisation server-side: `EDGE_ENROLLMENT_ORGANIZATION_ID` if set, else
the single organisation when there is exactly one, else **refuse**. There is deliberately no
`organization_id` on the enrolment request.

### Migration 057, and why unattributed rows are deleted rather than kept

Once the policy is on, a row with a NULL `organization_id` is readable by no tenant and
updatable by no tenant — and it makes its agent permanently broken, because the next heartbeat
cannot see the row through the policy, tries to INSERT, and hits the primary key. Deleting them
is what makes the upgrade self-healing: the next heartbeat recreates each row, attributed.
Nothing is lost that a thirty-second heartbeat does not restore.

A certificate issued before agents carried an organisation has no tenant to bind, so its
heartbeat is refused with a 409 naming the remedy rather than failing the policy check with a
500. Certificates are issued for `EDGE_CERT_TTL_DAYS` (30), so **the transition window closes
itself within one certificate lifetime** — which is the fact that made closing this gap safe.

## Rule 46 — a filter added to a read is a claim about the write path

Adding `WHERE organization_id = :org` asserts that something fills `organization_id`. Nobody
did, and nobody had to: the read got safer, the tests stayed green, and the page went blank.

A scoping fix is only half a change. Check the writer in the same commit — and when a column is
supposed to be populated, assert it **from the write side**, against the database, not by
reading the handler that is supposed to set it.

The tell is available statically and cheaply: a column that appears in `WHERE` clauses and never
on the left of an assignment is a column nobody writes.

## Rule 47 — fixing one half of a defect can arm the other half

`agent_id` is the primary key of `edge_agent_status` — one global namespace across every tenant
— and the CA signs a certificate for whatever id is asked for. While the organisation column was
never written, that was inert: a second tenant enrolling the same id overwrote counters on a row
nobody could read.

Attributing the row gives it teeth. The last heartbeat would win the *tenancy*, so B enrolling
`agent-of-a` moves A's agent onto B's fleet page and off A's. The fix for one defect created the
conditions for the next, in the same file, in the same commit.

Ask what a dormant defect was being kept dormant *by*, before removing it. The heartbeat now
refuses the rebind — and under the policy that check is unreachable (the other tenant's row is
filtered out of the lookup), so the collision surfaces as the primary-key violation, which is
handled too. Both paths, because the SQLite offline path has no policy at all.

## The last recorded gap is a grain problem, not an audit

`error_events` is the fourth entry, and working it produced no migration — deliberately. The
table is keyed on `fingerprint` ALONE: one row per distinct error for the whole platform, shared
by every tenant that hits the same bug, with `organization_id` naming only the last one to hit
it. A tenant policy over that column would hide errors that genuinely are the caller's, which is
worse than the disclosure it would fix.

`test_error_triage_sample_redaction_realdb.py` already recorded that finding and the decision it
led to — redact the two payload-bearing fields cross-tenant rather than pretend the table is
partitioned — with evidence: org A retrieved a row owned by org B whose message carried a
customer identifier and whose traceback carried a payment-card value. Re-deciding that quietly
would have been the wrong move; the baseline entry was corrected instead, because it said to
"check the ingestion path" and the ingestion path is fine. Closing this needs the primary key to
become `(fingerprint, organization_id)`, a composite foreign key from `error_event_buckets`, and
the upsert's `ON CONFLICT`/`COALESCE` rewritten — or a platform-admin role to gate the view on.

**An entry that names the wrong precondition is worse than one that names none**, because it
looks actionable. That is what a baseline is for.

## Two services had their own copy of the tenant session

`tenant_session` was extracted because the test harness held four hand-copied overrides of
`get_tenant_db`, each under a comment reading *"Mirrors the production get_tenant_db"* — and
each mirroring the RLS-after-commit defect as faithfully as the behaviour, which is why the suite
could not see it. A guard closed that for the test doubles.

**Production had two more, and that guard could not see them.**
`ExportProcessor._tenant_session` and `BulkProcessor._tenant_session`, both
`@asynccontextmanager`s yielding a bound session, both under the same *"Mirrors
app.core.tenant.get_tenant_db"* docstring. Found by asking a different question than the guard
asked: not "which test files override the dependency" but "which code in the whole tree binds
`app.current_org_id`" — thirty call sites, two of which were helpers rather than call sites.

They were not merely redundant. Both used a SESSION-scoped GUC (`set_config(..., false)`) so the
binding would survive intermediate commits, and reset it to `''` in a `finally` so it could not
ride a pooled connection into someone else's request. The reasoning is sound and the reset was
there — but it holds only while the reset runs. `tenant_session` gets the same
survive-the-commit property from an `after_begin` listener with a TRANSACTION-scoped GUC:
nothing outlives the transaction, so there is nothing to reset and no path where a leak depends
on cleanup running. Both now delegate.

The new guard also sweeps for the other way the thirty inline sites go wrong: a transaction-scoped
GUC, a commit, and more statements after it — every one of which runs unbound. There are none
today, and `run_erp_sync` is one `await db.commit()` away from being the first.

**The detector was wrong first, as usual.** With a bare `.get(` in its list of "still talking to
the database" it flagged `report_download_audit._insert_audit`, whose only line after the commit
is `logger.error(..., reason=details.get("reason"))` — a dict lookup in an exception handler.
The token list now names the receiver, and a negative control pins that exact shape.

## Rule 48 — a guard answers the question it was asked, so ask the broader one too

The duplicate-tenant-session guard asked *"which test files override `get_tenant_db`?"* and
answered it correctly, for years, while two production services held copies of the same helper.
Nothing was wrong with it. It was scoped to where the copies had been found, which is the natural
scope and the one that misses the next instance.

The broader question — *"what in the whole tree binds `app.current_org_id`?"* — is barely harder
to ask and returns thirty call sites instead of four files. Two of them were the helpers.

Related to rule 43 (a guard proves the absence of the shape it models) but distinct: there the
model was too narrow for the class, here the *search space* was. When a guard has been green for
a long time, re-derive its population from first principles rather than trusting the enumeration
it was born with.

## Migration 058: the five ERP tables that read as protected and were not

RLS enabled without FORCE is the more dangerous state, not a lesser one. The owner bypasses the
policy, and the application connects as the owner in several deployments — so
`relrowsecurity = true` answers the question, and answers it wrongly.
`app/api/erp_integrations.py` records what that cost in a comment: its background sync *"appeared
to work only because no ERP table has FORCE ROW LEVEL SECURITY and the dev connection owns
them."* The tenant GUC that sync now sets had never actually been under test.

Every live writer turned out to bind the tenant already: `run_erp_sync` sets it explicitly and
holds one transaction with a single commit, so the transaction-scoped GUC covers every statement;
the mapping routes run on `get_tenant_db`; the webhook path sets it after resolving the tenant
from the integration record. The dynamics, oracle and SAP `*_data_extraction` services and
`erp_database_replication` also write these tables and take their session as a parameter — but
**nothing imports them**: ~1,800 lines reachable from no router, no worker and no test but one
honesty check.

## Rule 49 — a suite that skipped is not a suite that passed

The baseline entry asked for "one real-DB run to confirm before the migration", and the run was
available: four real-Postgres ERP suites. They report **25 passed, 29 skipped** — and the 29 are
`test_erp_sync_e2e_realdb.py` and `test_erp_platform_integration_realdb.py` in full, skipped for
want of live Dataverse credentials. Every test that touches `run_erp_sync` is in that 29.

The migration header had already been written claiming those suites confirmed it. Green, from a
suite that never executed the code the change can break — the same shape as every "verdict from
absence" defect in this document, this time in the verification rather than the product.

The fix is not to acquire credentials. It is to notice which part actually needs them: the vendor
HTTP call, and nothing else. `test_erp_background_sync_under_force_realdb.py` stubs the connector
and drives the real `run_erp_sync` against real Postgres with the real policy — then asserts
FORCE is actually on first, because a successful write proves nothing while the owner is exempt.
Controlled by deleting the `_set_tenant_guc` call: three of its tests go red.

**Read the skip count, not just the pass count.** A skipped test is an unanswered question
wearing a green tick.

## An empty list that meant two different things

Found while writing the above. `GET /erp/integrations/{id}/sync-status` returned `200 []` for
another tenant's integration id — no leak; the explicit filter and the policy both held. But `[]`
also means *"this integration has never synced"*, which is the operator's answer to "did the sync
run?", and the ambiguity was there for the OWNER too: a wrong id and a never-synced integration
were the same response. The integration is now resolved first and an unknown one is a 404, so an
empty list has exactly one meaning.

404 rather than 403 for another tenant's id, matching the rest of that file: distinguishing them
would confirm the id exists.

## The eleventh finding: seven fields on one interface, and the value standing next to them

`RepairOrder` was the largest cluster the wire-vocabulary sweep had left. `repair_orders` has
thirteen columns and `_order_out` emits eleven of them; the TypeScript described a richer object
that no endpoint produces and no migration plans.

The sharpest of the seven is `assignedTechnician`, because everything around it worked.
`repair_orders.vendor` — the shop that actually did the repair — was sent on every response and
rendered **nowhere**, while the card offered a `Tech:` line that could never populate. The same
shape as the `geoTabDeviceId` finding: a row that cannot fill itself standing next to the value
it should have shown. `category` was in the same state, sent and unread.

The other six split across the sweep's three fixes:

  * **Deleted.** `workOrderNumber` — nothing in this product issues one. It had already been
    stripped from the panel; leaving the field optional kept the invitation open, and the mock
    `createRepairOrder` was still accepting it by minting `WO-YYYY-NNNN`. `actualCost` — a
    second cost on a table with one `cost` column, which IS the actual cost; two names for one
    number invites populating both. `laborHours` and `partsUsed` (with its `PartUsed` shape) —
    no columns, no tables, nothing pending.
  * **Renamed.** `issueDescription` and `reportedDate` were real data under invented names, and
    the adapter filled them from `title` and `openedAt`. Rule 35.

Renaming the type emptied the adapter: it had grown five fallbacks, four of which existed only
to bridge names the type had made up. What is left derives `vehicleNumber`, which the serializer
genuinely does not send.

## The twelfth finding: the first one fixed by making the server send it

`MaintenanceCosts` declared six figures and `/maintenance/costs` sent two. The client made up
four:

  * `monthlyAverage` was `ytd / 12` — computed in January as readily as in December, so a fleet
    three weeks into its year saw a twelfth of its spend labelled as a monthly average;
  * `costPerVehicle` and `upcomingEstimated` were hardcoded zeros, the second in a highlighted
    box reading **"Upcoming (Est.) $0"**, which reads as *nothing is coming up* rather than
    *nobody calculated this*;
  * `monthlyBreakdown` was a required array nothing sent, so the trend chart drew nothing.

An earlier pass removed the fabrications and left four blank rows. That was right, and it was
not the end of the job — **delete and rename are the cheap two of the three options, and the
third is the one that finishes the feature.** Every figure is a fact about data the endpoint
already had: spend per elapsed month, YTD over months elapsed, the sum of
`maintenance_schedules.estimated_cost` on work not yet done, and YTD over the fleet size. The
endpoint had been passing `[]` for schedules, which is where the cost of not-yet-done work lives.

`costPerVehicle` needed the one thing repair orders cannot supply: the fleet size. A vehicle
with no repairs this year has no row among them, and it is exactly the vehicle that makes the
average meaningful.

### None and zero, three times in one endpoint

* An empty fleet has **no** cost per vehicle. Not zero — and not a division by zero, which is
  how it became a hardcoded 0 in the first place.
* Outstanding work that nobody has costed has **no** estimate. Not an estimate of zero, which is
  what the highlighted box claimed. But a schedule explicitly costed at nothing is a real zero,
  and collapsing that to `None` would be the same error inverted — so both are pinned.
* A month in which nothing was repaired **did** cost zero. That one is a number, and dropping it
  from the breakdown shortens the year and moves every other bar.

## Rule 50 — a fixture in a shape no endpoint produces tests the fixture

The trend chart labelled its axis with `month.month.split(' ')[0]`. That is correct for
`"Jan 2024"`, which is what the mock contained, and it renders the server's `"2026-01"` as the
literal string `2026-01`.

The mock had never been wrong about anything else, so nothing pointed at it — and the panel test
used the same fixture, so the test agreed with the code about a format the server does not send.
Two artefacts agreeing with each other is not a check; they were copies of one assumption.

The same thing appeared twice more in this cluster: `MaintenancePanel.test.tsx` carried
`issueDescription` AND `title`, `reportedDate` AND `openedAt`, so it could not distinguish the
panel reading the wire from the panel reading names the adapter had invented. Fixtures now carry
exactly what the serializer emits, and the mock uses the wire's date format.

## The thirteenth finding: one cluster, all three fixes, and a hole in the sweep itself

Eight entries across `Vehicle`, `Driver`, `Shipment` and `HOSViolationAlert`, all about where
something is or what it is assigned to. Between them they needed every option the sweep offers.

**Renamed.** `Vehicle.currentLocation` is `vehicles.last_location`, which the serializer emits
as `lastLocation` with exactly the shape the panel reads. Every location block on the vehicle
panel was dead against a value arriving on every response.

**Served.** `Driver.currentVehicleId` and `.currentShipmentId` are not columns on `drivers` and
should not be: a vehicle names its driver, and a shipment names its driver. The driver's side of
both is a **reverse lookup**, which is why comparing the table to the type says "no such column"
about a field that is perfectly derivable. Two batched queries, and the shipment one excludes
terminal statuses — a delivered load is not what the driver is on now.

**Deleted.** `Shipment.currentLocation`, with the "Current Location (GeoTab)" card it fed. A
shipment has no position; the nearest real one belongs to the driver's vehicle, two hops away
through `shipments.driver_id` → `vehicles.current_driver_id`, and goes stale the moment a driver
changes vehicle. The heading was the most specific claim in it — GeoTab is not the source of a
shipment's position, because nothing is. `Shipment.estimatedDelivery` went too: it drove a
running-late warning (yellow when the ETA exceeded the schedule) that could never fire, because
nothing in this product predicts a delivery time.

`HOSViolationAlert` was deleted **whole**. One occurrence in the entire frontend: its own
declaration. Nothing constructed it, nothing rendered it, and none of its fields had a source. A
type nothing constructs is a plan, not a contract.

`Driver.lastLocation` went with them although the sweep never reported it — `drivers` has no
position column, and the global vocabulary credited the name from `vehicles`. Rule 34's blind
spot, found by auditing the interface against its own table rather than against the tree.

## Rule 51 — an upper-bound assertion is satisfied by zero

The N+1 guard for the driver lookups counted SELECTs and asserted `len(vehicle_reads) <= 1`. It
passed against a deliberate one-query-per-driver mutation, and the reason was two mistakes
stacked so that neither was visible:

  * the matcher was `" FROM vehicles" in statement` — **with a leading space**. SQLAlchemy
    renders the clause at the start of a line, so `FROM` is preceded by a newline and the count
    was always zero;
  * `0 <= 1` is true, so the bound could not tell "batched" from "matched nothing".

The file even had a non-vacuity check — `assert statements` — and it passed, because *something*
was recorded. It proved the listener was attached, not that the thing being counted was ever
found.

**Assert the exact count.** `== 1` fails at zero, which makes the matcher's silence a test
failure instead of a pass. An upper bound on a number you also have to discover is two claims in
one assertion, and the weaker one hides the stronger.

## Rule 52 — when a fix does not move the baseline, suspect the detector

`Driver.currentVehicleId` stayed on the declared-but-unsent list after the server started
sending it and the panel started rendering it. The obvious reading is that the fix did not work.
The actual reason: `_wire_vocabulary` collected string keys from dict LITERALS, and
`transportation.py` builds several responses by validating a model and then adding derived keys
by subscript — `row["carrierName"] = …`, the HOS remaining hours, the driver's vehicle and
shipment. Every one was invisible, and would have been reported as unsourced the moment a client
declared it.

A baseline that does not move when the code does is evidence about **one of the two**, and it is
worth a minute to find out which. The widening carries a positive control (`carrierName` is
credited) and a negative one (a variable subscript credits nothing) — a vocabulary that absorbs
names too freely stops reporting anything, which is the same failure as one that reads nothing.

## The fourteenth finding: the yard, and an interface that had drifted whole

Four entries, two joins and two deletions — and one of them turned out to be a twelve-field
interface with two fields right.

**Served.** `YardTrailer.driverPhone` and `DockAppointment.driverPhone`. Both tables carry
`driver_id` and `drivers.phone` is where the number lives, so this is the same join as
`trailerLicensePlate` one finding earlier in the same file. It is the number an operator calls
about a trailer sitting on the yard, rendered in three places and sent by nothing.

**Deleted.** `YardTrailer.contents`, with `poNumber` beside it. `yard_trailers` records what the
trailer IS — type, seal, weight, temperature setpoint — and nothing about what is inside it. The
inventory table printed a dash on every row under a column headed "Contents"; it shows the seal
number now, which exists. `YardTrailer.lastLocation` went too, unreported by the sweep for the
same reason as `Driver.lastLocation` — credited from `vehicles.last_location`, a different
table. It gated a "Current GPS Location (GeoTab)" card behind a condition that was never true.

**`DetentionAlert` had drifted entirely.** The banner appears only when a trailer is at risk or
already accruing charges — only when it matters — and it read `<trailer id>` above a bare
`" • "`, then `"$"` with no number and `"N/A excess"`. Every field it rendered was `undefined`,
including the React `key`, so every row shared one.

The numbers were all being sent under the endpoint's names (`detention_minutes`,
`current_charge`, `elapsed_minutes`, `free_minutes`) — renames. The identifying details were
genuinely absent and are real columns on the row the loop already held: `license_plate`,
`yard_location`, and the carrier's name one join away. The alert also has no `id`, because it is
computed rather than stored, and a four-value `severity` union nothing ever produced was
replaced by the `status` the builder really emits.

**Only `excessMinutes` was reported.** `carrierName`, `location` and `estimatedCost` all exist on
other interfaces, so the global vocabulary credits them and the sweep sees nothing — rule 34,
for the third time in this batch. The per-interface read against its own endpoint is what found
the rest.

## Rule 53 — a NULL a column can hold is a value the schema has to accept

`metadata: Dict[str, Any] = Field(default_factory=dict)` **rejects** `None`. The factory fires
only when the key is ABSENT — and `model_validate(orm_row)` does not omit the key, it supplies
the attribute's value. Seventeen of the twenty-one `meta_data` columns in the migrations are
declared with no DEFAULT, so any row not written through the ORM has `None` there, and
`model_validate` raises inside the list loop: the whole PAGE 500s for that tenant, not the row.

Twelve schemas were in that state. Three had already been changed to `Optional[...] = None`, one
table at a time, after the same defect was found on appointments — nobody had asked the question
across the file.

**Found by accident**, which is the part worth recording. A real-DB test for an unrelated fix
seeded its trailers with raw SQL, as every real-DB test here does, and seven of its eight
assertions failed on a validation error that had nothing to do with what was being tested. A
test that touches the database the way other systems touch it finds things no unit test can.

Coercion rather than `Optional`, deliberately: `Optional` changes the wire contract (clients that
received `{}` start receiving `null`), and NULL metadata and empty metadata genuinely mean the
same thing — a row with no extra attributes. That is **not** true of the other absences in this
session, which is why a missing cost, a missing estimate and a missing fleet size all stay
`None` while this one becomes `{}`.

## The fifteenth finding: three interfaces that had each drifted from their endpoint

The last four baseline entries, reported by **one field apiece** because the rest of their names
exist elsewhere in the tree. Rule 34, for the fourth time in this batch — a global vocabulary
credits `costSavings` from a maintenance schedule and `lastConnectedAt` from an agent, so the
sweep sees one field of eleven and the per-interface read finds the other ten.

**`CloudGatewayStatus`** declared eleven fields — an uptime, a certificate expiry, a last-sync
time and a nested `egressStats` of five more — against a `cloud_gateway.get_stats()` that
returns four keys. The instructive part: **the page had already worked this out.** It declared
its own local interface with the four real fields, under a comment reading *"Anything else is
not sent, so we render strictly from what actually arrives."* That was right, and it left the
exported type wrong — so the api client still promised eleven fields, the mock still returned
them, and the next component to use `CloudGatewayStatus` would have inherited the whole fiction.
A local workaround fixes one call site and preserves the defect for everyone else.

**`MaintenanceSchedule.assignedTechnician`** — deleted. `maintenance_schedules` has no
technician column and, unlike `repair_orders`, no vendor either: a schedule records what is due
and when, not who will do it.

**`StrategicRecommendation.expectedImpact`** is free-form by design — the engine documents it as
`{'oee_improvement': …, 'cost_reduction': …}` and sends a different set per recommendation type.
The card named three keys in a fixed grid: `oeeImprovement` (right), `costSavings` (the wire says
`costReduction`) and `timeSavings` (produced by nothing). So the cost figure never appeared on a
card whose entire purpose is justifying an approval, and two of the engine's three demo
recommendations — a throughput gain, forty-five days of extra RUL — rendered an empty box.

The fix is not a fourth and fifth named slot. **A fixed grid over an open-ended dict can only
ever show the keys somebody thought of**, so the card renders what arrives and labels it,
special-casing only the two it formats as a percentage and a currency.

## Rule 54 — a widening that removes one finding can cost the detector

`AgentRolloutCreate.all` is a genuine false positive: `_resolve_targets` branches on
`selector.get("all") is True`, and a `*Create` interface describes a REQUEST, so `all` is a name
the backend really reads. It just lives inside a free-form dict rather than in a signature,
which is where the parameter walk looks.

The obvious fix — credit the argument of every `.get("literal")` call — works. It was measured
before being accepted: **425 names are reachable only that way.** A third of the vocabulary's
discriminating power, spent to remove one baseline entry, and every one of those 425 becomes a
name the sweep will never report again.

Declined. The entry stays with its reason written out, and a test asserts the widening has not
since crept in. **Measure what a widening costs before taking it** — each one looks like a bug
fix on its own, and a detector can be improved until it reports nothing. The two widenings this
sweep did accept (parameters, subscript assignment) were narrow and each carries a positive and
a negative control.

The baseline is now two entries: this one, and `LogisticsOverview.todayAppointments`, which the
page genuinely computes client-side. **Both are non-defects** — which is the state a baseline of
gaps is supposed to reach, and the point at which it becomes purely a guard against new ones.

## Rule 55 — a static sweep cannot see what an adapter makes up at runtime

Deleting `contents` and `poNumber` from `YardTrailer` left `adaptTrailer` still synthesising
both — fishing them out of the free-form `meta_data` blob, which nothing writes either key into
— and `tsc --noEmit` stayed clean the whole time.

TypeScript relaxes excess-property checking for an object literal that spreads an `any`. So
`{ ...t, contents: … }` keeps compiling once the type stops declaring `contents`, and the
orphaned line survives every static check the repository has: the type says the field is gone,
the compiler agrees, and the object still carries it.

That is a structural limit, not an oversight. `test_frontend_fields_exist_on_the_wire.py`
compares DECLARATIONS against the backend tree; an adapter's inventions are not declarations.
The whole reason `currentMileage` was a defect rather than a typo is that the adapter
manufactured it at runtime.

**Assert the adapter's output.** `maintenance.realmode.test.ts` and `yard.realmode.test.ts` feed
each adapter exactly what the serializer emits and assert that nothing else comes back — the
harder half, because most tests check a value is present and this class is about a value that is
present and made up.

The control makes the point in one run: restoring the metadata synthesis leaves `tsc` clean and
turns the real-mode test red.

### Why this file and not the mock branch

`src/test/setup.ts` stubs `VITE_USE_MOCK='true'` before any module evaluates, so every frontend
unit test has always taken the mock fork — the real branch of ~213 forks across `src/api/` is
run by nothing. `loadInRealMode` resets the module registry and re-imports against the real
value. Two more modules are covered now; the maintenance client is where the sweep started, and
it had none.

## Rule 56 — a fixture on a boundary is a coin flip

`test_the_appointment_row_gets_the_phone` seeded an appointment at `now()`. The endpoint's window
is `scheduled_start >= start_date`, with `start_date` defaulting to the *request's* `now()` —
which is microseconds later. The row sat just outside the window and the test passed or failed on
scheduling jitter: green in isolation when I first wrote it, red in isolation an hour later, green
in the full suite because another module ran first and shifted the timing.

An order-dependent failure reads as pollution from a neighbouring test, and the instinct is to
look for shared state. Here there was none — both runs were correct, and the fixture was the
thing that was wrong. Seeding two hours out removes the race entirely.

**Put fixtures well inside the range under test, not on its edge**, unless the edge IS the
assertion — in which case seed both sides of it deliberately.

## Class 52: a coercion between two layers that both handled the absence correctly

`adaptZone` and `adaptAlert` in `src/api/geofencing.ts` turned absent values into plausible
ones. In three places that defeated null-handling written **deliberately on both sides of them**
— the serializer chose to send `null`, the panel was written to detect it, and the adapter in
between replaced it with something that looked like data.

**`geofenceName: … ?? a?.zoneId ?? ''`.** `_alert_out` resolves the zone name by join and sends
`null` when it cannot, under a comment reading *"the panel must be able to tell a zone it could
not resolve from one with an empty name. A blank would read as an unnamed zone."* The panel does
`geofenceName ?? 'Zone name unavailable'`. And **`'' ?? x` is `''`** — nullish coalescing does
not treat the empty string as absent — so the panel's fallback was unreachable and the row
rendered a blank line. Before reaching `''` it would print the zone's UUID under a heading that
reads like a name.

Two authors did the careful thing, in two files, and one line between them undid both.

**`alertType: … ?? 'violation'`** — the original defect surviving as a fallback. *Every geofence
alert reading "Violation"* is what started this whole thread; the producer was fixed and the
panel was taught to refuse to guess an unrecognised value, which requires it to SEE the absence.
The adapter kept supplying the word.

**`center: { latitude: … ?? 0, longitude: … ?? 0 }` and `radius: … ?? 0`.** `center_lat`,
`center_lng` and `radius_meters` are nullable, and are genuinely NULL for a POLYGON zone.
`circleRenderableZones` filters on `typeof z.center.latitude === 'number'` precisely to exclude
those — and a coerced `0` passes the filter. A zero-radius circle at 0°N 0°E, in the Gulf of
Guinea, drawn on the fleet map.

`GeofencingPanel.zones.test.ts` covers that filter thoroughly, **including a `center: undefined`
case**, and passed throughout. The adapter never produced an undefined centre, so the filter was
tested against an input the real pipeline could not send it.

Two smaller ones in the same pass: `vehiclesInside: … ?? []` made the panel print "0 vehicles
inside" on every zone — a count, which reads as a measurement, for a figure nothing computes —
and `createdAt: … ?? ''` produced `new Date('')`, which renders as the literal string
"Invalid Date".

**The whole frontend suite was green before this and after: 417 tests, none of which could see
any of it.** A coercion is invisible to every test that supplies complete data, and fixtures
supply complete data by default.

## Rule 57 — test each layer with what the layer above it can actually send

`circleRenderableZones` was tested with `center: undefined`. `adaptZone` produced
`center: {latitude: 0, longitude: 0}`. Both were correct about their own contract and neither
was ever handed the other's output, so a defect lived in the join between them with full
coverage on both sides.

The cheap fix is one test that runs the real adapter's output into the real filter — twenty
lines, and it fails on its own against the coercion. Where two units meet, assert on the pair;
the seam is where the untested inputs live.

Related to rule 55 but distinct: there the static checker could not see the runtime value, here
both dynamic tests were fine and neither covered the composition.

## The literal-default guard: turning the third hand-audit into a check

Three coercion defects were found by reading adapters — `geofenceName ?? ''`,
`alertType ?? 'violation'`, `latitude ?? 0`. Rule 39 says six hand-fixes and no guard is a class
that will come back, and this was the third pass over the same shape, so the audit is now a
test.

**The rule it encodes: an API client may choose what to SEND; it may not decide what the server
MEANT.** The dangerous form is a LITERAL default on a value that came from the server —
`field: response.x ?? 0`. Deliberately not flagged:

* `a ?? b` where both sides are field reads. That is a **rename** (`geofenceId ?? zoneId`), one
  of the three legitimate fixes this codebase applies, and a guard that forbade it would forbid
  the cure.
* Request-side defaults. `limit: params.limit ?? 1000` is the client deciding what to ask for.

Twenty-eight sites, each classified with its kind — REQUEST, ERROR, BENIGN, MOCK-ONLY — and a
test asserting every reason states which. Sorting them was most of the value:

* **Live, and fixed:** the three geofencing coercions.
* **Real branch, no consumer, fixed anyway:** `timestamp: d?.lastSeen ?? new Date()` in
  `getDiagnostics`. Every fault code on a device that has never reported would have been stamped
  with the current time — the most confident thing the row could say and the one thing nobody
  knows. Dead code gets called eventually; that is how the synthesised work-order number shipped.
* **Mock-only, left with the caveat written down:** `driveHoursRemaining: … || 0` in
  `getDriverHOS`, which has no consumer. It is the exact shape the backend warns about —
  `hos_drive_hours_remaining` is NULL for a driver who has not reported, and 0 means *out of
  hours*. The baseline entry says so, so wiring the method up without fixing it fails a review
  that reads the entry.
* **Benign-ish, recorded as such:** `totalSchedules: d.scheduledCount ?? 0` and its two
  siblings, reachable only on a 200 that omits the counters. "0 overdue" is a claim, and the
  entry says to revisit if that path ever becomes reachable.

The control reintroduces two of the fixed coercions and the guard names both, by file and field.

## Rule 58 — a mock-only defect is a defect with a delay

`getDriverHOS` and `getDiagnostics` have no callers, so their fabrications hurt nobody today,
and the temptation is to leave them or delete the methods. Neither is right on its own.

A mock branch is the specification the next author reads. `createRepairOrder` minted
`WO-YYYY-NNNN` in its mock, which is how a synthesised work-order number came to look like a
product feature and ended up displayed as the heading a technician quotes to a vendor — the real
path could never produce one. The fixture taught everybody the wrong contract, and the code that
shipped followed it.

So: fix the real branch even when nothing calls it, and where the fabrication genuinely belongs
to a fixture, **write down what makes it wrong to promote**. The baseline entry for
`driveHoursRemaining` names the exact reason (`NULL` means unreported, `0` means out of hours),
which is the thing a future author needs and would otherwise have to rediscover from a backend
comment three files away.

## The same HOS defect, third endpoint

`/api/v1/logistics/compliance/summary` counted violations as

    (d.hos_drive_hours_today or 0) >= 11 or (d.hos_cycle_hours or 0) >= 70

Both columns are nullable and NULL means the driver has **not reported** — not that they have
driven zero hours. Every unreported driver coerced to 0, cleared both thresholds, and the tab
rendered `activeViolations: 0`, which `TransportationManagement` paints **green**. An all-clear
on DOT-regulated hours, produced by the absence of the data that would decide it.

This is the third place the same class has been found on the same column family:

  * `hosDriveHoursRemaining === 0` on the driver list — `null === 0` is false, so every fleet
    came back with no violations under a green "No HOS violations detected";
  * `HOSComplianceMonitor.check_compliance`, fixed by collecting a `missing_data` list before
    judging anything;
  * this rollup, which neither fix reached.

`/logistics_correlation`'s `driver_compliance` block already reported `unassessable_drivers`
alongside its violation count, for exactly this reason. **The shape existed, on the other
endpoint.** A fix applied where the defect was found does not travel to where the same defect
also is, and the thing that makes it travel is a name — searching for `unassessable` finds the
pattern; searching for the defect finds nothing, because the defect looks like ordinary code.

The rollup now counts over the drivers it could assess and reports `driversAssessed` /
`driversUnassessable`. The tile paints zero green only when something was assessed, grey
otherwise, with the count that explains it. It also imported 11.0 and 70.0 as literals while
`HOSComplianceMonitor` held the canonical FMCSA values — a third copy, and the one furthest
from anybody looking for them.

**Rule 37 caught this file's own test on its first run.** The comment above the fix quotes
`(d.hos_drive_hours_today or 0) >= 11` while explaining what was wrong with it, and the source
assertion `">= 11" not in summary` matched the prose describing the defect — reporting the fixed
code as unfixed. Fourth occurrence of that trap. Comments are stripped before the assertion now,
as every other source assertion here already does.

## Rule 59 — search for the fix, not the defect

Three HOS endpoints had the same coercion. Two were fixed, months apart, each time by someone
looking at the endpoint in front of them.

A defect of this class is invisible to search: `(x or 0) >= 11` is ordinary code and looks like
every other guard clause. The FIX is not — `unassessable_drivers`, `missing_data`,
`hos_drive_hours_remaining is None` are all distinctive strings, and each names the concept the
other sites are missing.

So when you fix one, grep for what you just wrote and see who else should have it. That is a
thirty-second check that would have found this rollup twice.

The generalisation: a codebase's fixes are more searchable than its bugs, and the second
instance of a class is usually adjacent to the first — same table, same columns, same domain
vocabulary. `_scope`, `tenant_session`, `availability_only`, `unassessable` — each of those was
introduced once and had to be carried by hand to the other places that needed it.

## Rule 59 applied to its own commit, immediately

The rule says: when you fix one instance, grep for what you just wrote. Doing that on
`unassessable` found the carrier rollup in `transportation_management.py`, which was already
correct and thorough — it counts violations, unassessable drivers and compliant drivers
separately, with a comment explaining that subtracting only violations would count the
unassessable ones as compliant.

**One line below it was not.**

    'csa_score': float(carrier.csa_score) if carrier.csa_score else None

A falsy test, and **0 is the best possible CSA score.** A carrier with a spotless safety record
reported "no score on file" — which is exactly what an operator sees for a carrier nobody has
assessed. `erp_integrations.py` had the twin: a sync that finished in under a second stores 0 and
reported its duration as unrecorded.

This is the same class pointing the other way. Everything above was absence dressed as data — a
NULL coerced to a plausible number. These two are **data dressed as absence**: a real,
meaningful zero discarded by a truthiness test. Both come from the same habit of writing `if x`
where the question is `if x is not None`, and the second direction is harder to notice, because
the value it hides is the good news.

The sweep for the shape found five sites; three were datetimes, which are never falsy, so they
were already equivalent to an `is not None` check. Two were real.

## Class 53: a comment that argues for the code beneath it, and is no longer true

`fleet_logistics._scope` opened with *"NEEDED EXPLICITLY because these four tables …
carry `organization_id` but have NO row-level security."* Migration **051** policied all four
with FORCE, and the sentence was never updated. It is repeated at four write sites in the same
file as the justification for taking the organisation from the token rather than the payload —
which remains the right thing to do, for a reason that stopped being the stated one.

**Three of the five stale claims were made stale by migrations written in this session.** 056
policied the two notification tables; 057 policied `edge_agent_status`. Each left behind a
comment saying the table it had just protected was unprotected. The claim decays every time
somebody does the right thing somewhere else — which is the definition of a fact that should not
be maintained by hand.

And it decays in the dangerous direction. *"This table has no policy, so the filter is all that
stands between you and a cross-tenant read"* is load-bearing: it is the argument for the code
beneath it. Stale, it does not become harmlessly out of date — it becomes a false account of why
the code is shaped the way it is, and the next reader either trusts it and over-builds, or checks
it, finds it wrong, and trusts the rest of the file less. A comment that explains itself survives
review; that is exactly what makes a wrong one durable.

The claims are checked against `pg_class` now. Past tense is exempt on purpose — `alarms.py` says
*"`alarms` HAD no RLS policy; migration 046 turned a latent bug into a real one"*, a statement
about history, which stays true.

### The detector was wrong twice, both found by running it

* It matched **line by line**, and the claim in `_scope`'s docstring wraps across a line break
  (`carry \`organization_id\` but have NO` / `row-level security`). The four tables it is
  actually about were never checked. The text is joined before matching.
* It attributed **every table token within two lines**, which made `user_management.py` a false
  positive: *"``users`` has no RLS policy: ``audit_logs`` DOES"* names the contrast as well as
  the subject. Only tables in the sentence BEFORE the phrase are its subject — which is where
  English puts them, and it is also what excludes the contrast that follows.

## Rule 60 — a non-vacuity check keyed on defect count inverts when you fix them

The first version asserted `len(_claims()) >= 5` as its "the scan still works" floor. Five stale
claims existed, so it passed — and it **failed the moment they were corrected**, because
correcting them meant putting them in the past tense, which is precisely what the scan is built
to skip.

The check was measuring the defects, not the detector. A guard that goes red on success teaches
people to weaken it, and the weakening is indistinguishable from the scan quietly breaking.

Key non-vacuity on something that does not move when the codebase improves: a synthetic positive
control in the shape of the real defect, and a negative control from the real false positive.
Both are now written against the exact sentences that produced them, so a regex that stops
matching wrapped text, or loses its subject attribution, fails on the sample rather than on a
count.

## The twenty-third call site

Correcting the stale `_scope` comment meant reading what `_scope` is for, and that raised the
obvious next question: does every query against those four tables actually use it?

Twenty-two of twenty-three did. `vehicle_service_history` took **no `org_id` dependency at all**
— the only handler in the file that did not — and filtered `repair_orders` on `vehicle_id` and
status alone, returning `_history_out`: description, cost, vendor, and the technician's notes.
Its sibling one function above, same table, same shape, was scoped.

On Postgres migration 051's FORCEd policy filtered the rows anyway, so there was no leak there.
On the **SQLite offline path there is no policy**, which is the case `_scope` exists for: any
caller with a vehicle id got that vehicle's repair history regardless of whose vehicle it was.
And `repair_orders.vehicle_id` is a bare VARCHAR with no foreign key, so two tenants using the
same id is not exotic.

**Twenty-two right and one wrong is the state in which the one is invisible.** Nothing about it
looks unusual, and a reviewer's eye is calibrated by the twenty-two. So the question — *is this
`select()` wrapped in `_scope`?* — is asked by a parser now, along with the smell that made it
findable in the first place: a handler that queries a tenant table and takes no `org_id`.

Both assertions fire on the real pre-fix handler, which is the control that matters; a synthetic
sample would only have proved the regex works.

### What the real-DB test can and cannot show

`test_service_history_is_scoped_realdb.py` passes against the **pre-fix** code too, because the
policy was doing the filtering. That is not a weakness to hide — it is the finding. The source
check is what caught this, and the behavioural test pins the other half: that adding the filter
did not break the endpoint for its owner, that the status predicate and the ordering survived
being moved inside `_scope`, and that the two layers agree rather than one masking the other.

Two layers that disagree are worse than one, because whichever answers first decides.

## Class 54: the write surface was never walked

`test_realdb_endpoint_smoke.py` walks every GET against a migrated Postgres and asserts none of
them 5xx. Nothing walked POST or PATCH, and the failure mode there is different: a body the
handler did not expect should come back 422, and instead crashes inside the handler as a 500 the
caller cannot act on. This codebase already names that distinction — `_uuid_or_404` and
`_iso_or_400` both exist because somebody hit a 500 that should have been a 4xx — and neither
was enforced anywhere.

An **empty body** is the right probe: valid input to the test, invalid input to every handler,
no ids to collide with, nothing written if a handler wrongly accepts it. `payload["name"]` on
`{}` is a KeyError; `payload.get("name")` flowing into a NOT NULL column is an IntegrityError.
Both are 500s that should be 422s.

### The first version passed while testing nothing

`/api/v1/auth/logout` is the **fourth route in registration order**. An empty POST to it
succeeds, revokes the caller's session, and all 137 probes after it came back 401 — which the
first version counted as acceptable, on the reasoning that a 401 means the walk never reached
the handler. **133 of 141 probes were 401.** The walk was asserting, over and over, that an
unauthenticated request is rejected.

It was caught by mutation testing and not by reading: deliberately breaking a handler to
`payload["name"]` produced no failure, and the endpoint answered 400 correctly when probed on
its own. The gap between those two facts is the whole bug.

Two changes, and the second is the one that matters:

* logout and refresh are skipped, along with the three agent-certificate endpoints, whose 401
  for a user's bearer token is the correct answer rather than a lost session;
* **401 is no longer acceptable**, and the walk asserts at the end that it is still
  authenticated. If a future endpoint revokes the session, every probe after it fails and names
  itself, instead of 137 silent passes.

### What it found once it worked

* `/admin/database/vacuum` answering `role "placeholder" does not exist` — **rule 45 in a
  handler nobody had reached.** `_vacuum_telemetry` used the `engine` captured by
  `from app.db.database import ...` at import.
* Three HARSH-lane 500s, recorded in a known-failure list asserted both ways.
* Legitimate 503s from Redis and `pg_stat_statements` being absent, now allowed for the same
  reason the GET walk allows them: degrading is the correct behaviour.

## Rule 61 — sweep every name a module exports, not the one that broke

`conftest` rebinds `AsyncSessionLocal` across `sys.modules` for every `app.*` module that binds
it, under a comment explaining that patching a hardcoded list of eight while forty-one bind the
name is how `role "placeholder" does not exist` reached the smoke suite. That fix was right, and
it swept **one of the two names `app.db.database` exports.**

Six modules bind `engine`, including `app.api.health`, whose `_vacuum_telemetry` opens a
connection on it directly. The same error, from the same cause, one attribute over — and
invisible because nothing reached that handler until a write-surface walk did.

When the fix for a stale-binding problem is "sweep the modules", sweep the module's whole public
surface. The attribute that was not causing trouble at the time is the one that will.

## Completing the walk: PUT and DELETE

PUT is the same probe as POST. DELETE needed a different one — **a fresh random UUID rather than
the seeded organisation id the other walks fill with.** Filling every `{...}` with a real id is
harmless when the request only reads; on DELETE it is the difference between probing and
destroying. Nothing in the database has the random id, so every route exercises its not-found
path, which is the path most likely to be wrong because the happy path is the one everybody
tests.

**One route is never probed at all, and not because it might fail.** `/api/v1/gdpr/data-delete`
takes no path parameter and erases the caller's data on request; a probe that "passes" there has
deleted the organisation the rest of the walk is about. It is the one place where the cost of
finding out exceeds the finding.

### What it found

`PUT /api/v1/feature-flags/{key}` and `POST /api/v1/feature-flags/` raised a raw
`ConnectionError` when Redis was absent. The **same file's** GET, list and DELETE handlers all
degrade to 503, two of them under comments reading *"store (redis) unreachable — match the list
endpoint"* and *"match GET/list (503)"*. Four handlers had the caveat and two did not, in a file
whose author clearly knew about it.

That is the twenty-two-and-one shape again at a smaller scale, and it is why the walk is worth
more than reading the file: nothing about the two exceptions looks wrong beside the four.

`DELETE /api/v1/rag/documents/{doc_id}` surfaces a SeaweedFS connection error for the same
reason the GET walk already records `/api/v1/rag/documents` — one root cause, two methods,
htreinen's lane.

### The known-failure list had to be keyed by method

One list across four walks, keyed by path alone, meant a DELETE-only failure read as *"listed
but passing"* to the POST walk — whose staleness check then reported it as fixed and demanded
its removal. Caught immediately, because that check exists and is asserted both ways. A shared
baseline needs every dimension the thing it describes varies along.

## The failure-is-not-emptiness sweep had a population, not a class

`failureIsNotEmptiness.test.ts` is the most-revised guard in this repository — five documented
broadenings, each found by the next false positive, with a comment explaining every one. Its
scope was `useQuery` **and** a literal empty state, on the reasoning that "the query is what can
fail, and the empty string is where the failure lands."

That is the population the defect was found in, not the class. **Fourteen components fetch by
hand** — `await maintenanceApi.getX()` inside a `useEffect`, then `setState` — and render empty
states from data that can fail to arrive exactly as react-query's can. The only difference is
who owns the `catch`. `ErrorTriage` has four empty states, handles failure in its own state, and
was entirely outside the guard's reach: nothing had ever checked which branch a failure lands in.

Rule 48, applied to a guard that had already been broadened five times.

### The broadening produced three false positives, and each was a missing idiom

* **Bare `error`.** react-query hands you `isError`; a hand-fetching component holds
  `const [error, setError] = useState<string | null>(null)` and writes `if (error) return`. All
  three fleet panels do exactly that, correctly, and were all reported. The word alone is too
  loose to match on (`setError(`, `onError=`, `errorMessage`), so it is anchored to the three
  shapes that actually branch.
* **The three-state ternary.** `HealthSecurityPanel` renders
  `isLoading ? <skeletons/> : error ? <message/> : (<>…entire page…</>)`. Every empty state sits
  in that last branch and is unreachable on failure — and all five were reported, because the
  error arm and the empty states are thousands of characters apart and the chain check is a
  proximity window. The file already had this insight for `if (isError) return`; the ternary
  form is the same guard wearing different syntax. Deliberately narrow: it requires the loading
  arm too, so a bare `error ? a : b` elsewhere in a file cannot excuse an unguarded empty state.
* **A router fallback.** `App.tsx`'s "Page not found" entered the population only because
  `.then(` appears in its lazy route imports. There is no request behind it that could have
  failed instead.

### And one real finding

`GeofencingPanel` renders an error banner **and then the content anyway**, so a failed load
showed *"Failed to load geofence zones and alerts"* above *"No geofence zones. Use + to create
one."* Two statements about the same fetch, one of which invites the operator to create a zone
that may already exist. The banner explains what happened; the list now stops contradicting it.

The other eight offenders are HARSH's — kanban, NLP and intake — recorded with owners and
asserted both ways rather than edited blind.

## Rule 62 — a guard's scope is a hypothesis, and it is usually the place you first looked

Every broadening of this file so far had been about the *shape* of the check: which idioms count
as an error branch, how far to look, whether comments count. The scope itself — "components that
call `useQuery`" — had never been questioned, because it was true of both original findings.

Ask what the class actually is, then ask what the population is. Here the class is "a failure
rendered as a fact about the world" and the population is "anything that fetches", which is
strictly larger than "anything that uses the library we happened to be using when we found it".

The same shape as rule 48, one level up: there the guard asked the right question of too few
files; here it asked it of the right files for the wrong reason.

## The eight, fixed

The lane baseline recorded eight offenders in kanban, NLP and intake, on the reasoning that
editing another lane's subsystem blind is how you break what you cannot test. Checked against
`docs/planning/next-week-task-pool.md` first: Harsh's assigned items are the scenario builders,
the deselected mappers, the quarantine expiry, the `simulated` flag, the Gemma adapter, the
kanban RLS work in `kanban.py`, the intake 500 and splitting `CorrelationAIPane.tsx`. Alex's are
header parsing and docs. **None of the eight files appears in any assigned item**, so the fix
collides with nothing in flight.

**Not one of the eight had an error state at all.** Every one caught the failure, logged it, and
rendered the empty branch. Two are worth quoting:

* `SessionList` clears its list in the catch, under a comment reading *"On error, clear sessions
  to avoid showing stale data."* The author thought about it and got the first half right —
  clearing IS correct — then left "No sessions found" as the only thing on screen. Clearing the
  data and saying nothing happened are different acts.
* `IntakeInbox` rendered *"No items in the inbox"* above *"Upload data to get started with AI
  analysis"* — an invitation to re-upload work that may already be there.

`RealTimeDataPanel` needed one gate for five empty states: every tab's data starts `null` and
the per-tab strings ("No telemetry data", "No alarms", …) are reached only once data has
arrived, so the top-level `!data` branch is where a failure lands.

`TaskDetailModal` was the mixed case. Of its three flagged strings, two — "No description
provided" and "No due date" — are fields of a task the modal receives as a **prop**; a task with
no description genuinely has none and no request could have failed instead. Only the assignee
dropdown's "No users available" is a fetch. The two are exempted by name, the one is gated.

### The baseline is deleted, not kept

A list of other people's defects earns its place by being shorter than the work. Once it reaches
zero it is a monument, and the assertion beneath it should be unconditional again. Its two
companion tests — "names nothing already fixed" and "every entry names an owner" — went with it;
they existed to keep the list honest, and there is no list.

---

