# Open decisions

Findings that are **understood, reproduced, and deliberately not fixed** — because closing
each one is a product or contract decision rather than a bug fix.

**Seven when this page was written; five now.** Two closed on 2026-08-05:

* *A PDF page's text truncated at 20,000 characters, silently.* Left open on the belief that
  fixing it meant changing a return shape two consumers read. **The belief was wrong and
  checking it took one grep** — both read named keys off each page, so an added key breaks
  nothing. The blocker was the assumption, not the coupling.
* *The backend image cannot be rebuilt — the Docker VM is full.* 13 GB was reclaimed from
  abandoned build containers, the image rebuilt, and the stack now answers `health: 200`.

They are currently recorded in test docstrings, which is the right place for the *reasoning*
and the wrong place for the *decision*: a docstring is read by whoever next edits that file,
and none of these will be closed by that person. This page is where someone deciding can see
them together.

**Every entry is pinned by a test.** None can drift silently, and each names what would have
to change. When one is closed, delete its entry here and the test class that pins it — a
register that outlives its items is the thing this repository keeps finding.

**And the numbers below are asserted, not maintained.**
`backend/tests/test_open_decisions_numbers_are_true.py` compares every figure on this page
against the thing it describes, so a ratchet that moves without this page moving fails a
test. That guard exists because four figures in this repository's documentation were wrong in
a single week — one of them an unfillable-registry count on this very page, written as 41
when it is 38.

The reason to care is not tidiness. A reader consults a register like this to decide
something, and **one wrong figure makes them discount the whole page — including the entries
that were right.**

---

## 1. 38 registries are created that nothing can fill

**Pinned by** `backend/tests/test_correlation_registry_integration.py::TestTheRegistriesNothingCanFill`
· FS-444

`initialize_registries_for_organization` creates a registry for every mapped domain. Of 46:

| | count |
|---|---|
| reachable by `_extract_domains_from_analysis` | **8** |
| also receive default items (a *subset* of the 8) | 5 |
| **neither — created empty, stay empty** | **38** |

On a compliance screen that reads as 38 programmes **not started** rather than 38 that
**cannot be started**, which is a different fact and the more alarming one.

**To close:** give those domains extractor keywords and default items, or stop creating a
registry nothing can populate.

---

## 2. Five declared fields on shapes the server never defines

**Pinned by** `backend/tests/test_frontend_fields_exist_on_the_wire.py`
(`MAX_UNREAD_PHANTOM_FIELDS = 5`) · FS-442

All five are on `Location` and `Address`. `shipments.origin`/`destination` are
`Dict[str, Any]` on the wire — free-form JSON with no contracted keys — so those interfaces
document **an expectation a caller may fill in, not a payload the server promises.**

Asking "does the backend send this name" of a shape the backend never defines gets an answer
that means nothing. Two of the five also carry a deliberate keep-decision from an earlier
pass, recorded in the type itself.

**To close:** contract the JSON shape server-side (then they become real fields), or teach
the sweep to recognise client-constructed types and exempt them with a verifiable rule.

---

## 3. `logistics_correlation` serves twelve paths at a doubled prefix

**Pinned by** `backend/tests/test_logistics_correlation_scoping_realdb.py`

The router declares `prefix="/logistics"` and `main.py` mounts it at `/api/v1/logistics`, so
its routes serve at `/api/v1/logistics/logistics/…`.

**It is not a routing edit.** Removing the inner prefix lands two of those paths on
`/delivery-efficiency` and `/compliance/summary`, which `fleet_logistics` already serves and
which the frontend actually calls. Whichever router registers first would silently win.

**To close:** decide which implementation is canonical per path, then fix the prefix.

---

## 4. Two PUT handlers replace rather than patch

**Pinned by** `backend/tests/test_partial_updates_do_not_wipe_fields.py` (2 allowances)

Both are recorded with reasons; one is a genuine full-replacement PUT where every field has
a default, which is what PUT means. The other dumps nested checklist items and is a
different shape from the update payload.

**To close:** confirm the intended semantics per route and either narrow the allowance or
switch the verb.

---

## 5. Three heartbeat fields arrive at the cloud and are discarded

**Pinned by** `backend/tests/test_heartbeat_contract_is_fully_read.py` · FS-460

`build_heartbeat_payload` sends eleven fields. `_process_agent_heartbeat` persists
`agent_id`, `agent_version`, `config_hash` and `build_id`, and uses `organization_id`,
`asset_ids` and `timestamp` to route and stamp the update. It never touches:

| field | what it would tell an operator |
|---|---|
| `buffer_depth` | pending messages on the device — the number that says it is falling behind |
| `collector_status` | per-collector health, from the agent's own coordinator |
| `git_sha` | which build is actually running, beyond `build_id` |

`buffer_depth` is the one that matters. The `EdgeBufferGrowing` alert answers the same
question from the agent's `/metrics`, which requires **reaching the device** — and the case
worth catching is the device you cannot reach. The heartbeat is the path that survives NAT,
it already arrives, and the cloud already parses it.

**To close:** decide whether the fleet surface should show device backlog and collector
health. If yes it is a migration (three columns on `assets`), a worker change and a panel; if
no, stop computing and transmitting them on every device. Both are defensible; doing neither
is what is currently happening.

---

## Not on this page

Three registers already govern their own items and expire on their own terms:

* `backend/tests/_lane_failures.py` — endpoints permitted to 5xx. **Currently empty**
  (FS-431); all nine were fixed rather than re-dated.
* `backend/tests/test_ci_quarantine_expires.py` — CI `--ignore` flags. **Currently empty.**
* `docs/engineering/test-quarantine.md` — skipped tests.

Ratchets that are at **zero** and stay there by assertion, rather than being open decisions:
per-type unfed fields (`MAX_UNFED_FIELDS = 0`) and adapter-unset fields
(`MAX_UNSET_FIELDS = 0`).

## Closed, and what closing one cost

**The capped lists** (FS-455/459) were entry #2 and are at zero. Eleven endpoints could not
say they had capped; the fix was `limit + 1` and one `mark_truncated` call each. Six went on
2026-08-05 in `registries.py`, `health_index.py`, `commands.py` and `notifications.py`; the
last five went the same day in `analysis_sessions.py` and `kanban.py`.

**Those last two files belong to another lane, and crossing it was the right call here** —
this entry recorded itself as the one needing nobody's intent. The change contains no
decision about semantics. The entries that DO need someone's intent are still on this page,
untouched, which is the distinction that makes the lane rule worth keeping rather than a rule
to route around.

Half a fix would have been to stop at the server. The three chat endpoints have real callers,
so `getChatHistory`, `searchChatHistory` and `getSessionMessages` now return `ListResult`, and
both components render a notice. Search is the sharpest: a capped result means matches exist
that were not shown, and a search box that quietly omits hits is worse than one that finds
nothing, because the user concludes the thing is not there. The two `kanban.py` endpoints have
no frontend caller at all — the board uses `/kanban/board` — so the signal is there for
whoever writes one.

`MAX_UNSIGNALLED = 0`, and the class that used to attribute the debt across lanes now asserts
there is none.


**The PDF truncation flag** (FS-454/456) was entry #1 on this page: the parser capped each
page at 20,000 characters and said nothing. Closing it took three layers, and only the first
was the one written down:

1. the parser now reports `text_truncated` and `text_chars_dropped` per page;
2. `POST /nlp/correlation/intake/analyze` carries `pages_text_truncated` beside the
   `truncated` flag it already sent — **two different amputations, one of them reported**;
3. the intake panel renders a notice. It had been receiving `truncated` all along and
   rendering a risk score next to it without comment.

Worth recording because the entry was written as a parser problem and was a **three-layer**
problem, and because layers 2 and 3 were found by fixing layer 1 rather than by reading. An
open decision's scope is a guess until someone starts closing it.

It also cost a self-inflicted outage: the same session's edit added
`mark_truncated(response, ...)` to nine handlers and the `response` parameter to six, so
three endpoints answered **500 on every call**. Nothing caught it until a real request did —
now pinned by `TestTheSignalCanActuallyBeSent` in
`backend/tests/test_capped_lists_cannot_grow.py`, which is an AST check costing milliseconds.
