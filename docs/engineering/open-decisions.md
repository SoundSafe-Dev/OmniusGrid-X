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

## 1. `pre-commit` is advisory, and bringing the tree into compliance is one 972-file commit

**The state.** `.pre-commit-config.yaml` declares four formatting hooks — `trailing-whitespace`,
`end-of-file-fixer`, `ruff-format` and `prettier` — and `quality-gates.yml` runs them with
`continue-on-error: true`, above a comment reading *"Advisory while the existing tree is
brought into compliance."* The tree has not been brought into compliance, and the comment has
been true for long enough that it now describes a decision rather than a transition.

**What making it blocking costs.** Measured 2026-08-08 by running `pre-commit run --all-files`
on a clean tree: **972 files changed, 55,068 insertions, 40,118 deletions.** Of the Python
half, `ruff format` alone would rewrite 570 files and leave 125 as they are. It touches every
lane in this repository at once — OTA, MLOps, correlation-AI and RAG included.

**Why it is a decision and not a task.** Both answers are defensible and they are not
reversible against each other:

* *Make it blocking.* One announced tree-wide reformat, landed when no branch is open,
  because a 972-file diff conflicts with every branch that exists. Every future diff is then
  clean, and `git blame` on 972 files points at that commit instead of at the person who wrote
  the line.
* *Keep it advisory and say so.* The comment stops claiming a transition that is not
  happening. New code stays unformatted at the same rate it does today, and the hooks catch
  the two things that do not need a tree-wide change — merge conflicts and secrets — which is
  most of their value.

Nobody outside the lanes can make this call: the reformat lands in four other people's files.

**Pinned by** `backend/tests/test_the_precommit_decision_is_still_open.py`, which asserts the
CI job is still advisory and the four formatting hooks are still declared — so the entry
cannot go stale by somebody quietly making it blocking, or by the hooks being removed.

**The diff figures above are dated, not continuously checked, and that is deliberate.**
Reproducing them requires the hook versions pinned in `.pre-commit-config.yaml`; a count
computed with a locally-installed formatter would be a different number presented as the same
one. Re-measure with the command above, in a clean tree, before deciding on it.

---

## Everything else here was closed on 2026-08-05

**Every entry that was on this page then has been closed** (FS-466 … FS-470, 2026-08-05). What each one
needed turned out to be a decision rather than an investigation, which is what this page was
for — and in three of the five, making the decision took less time than the entry had spent
being re-read.

They are recorded under "Closed, and what closing one cost" below, with what the closing
actually involved. The pattern worth keeping: **two of the five were closed by deleting
something rather than building something** — the registries nothing could fill are no longer
created, and the heartbeat fields nobody read are no longer sent.

### Adding an entry

An entry belongs here when the work is blocked on **intent**, not on investigation: someone
has to choose between two defensible answers and the code cannot choose for them. It needs:

* a **pin** — the test that fails if the situation drifts, so the entry cannot go stale
  silently;
* the **figures**, which `test_open_decisions_numbers_are_true.py` checks against reality;
* what closing it would take, concretely enough that the next reader can judge the cost.

An entry that is really "nobody has got to it yet" is not a decision. The capped-list
ratchet sat here for weeks under that description, and closing it was `limit + 1` and one
function call per endpoint.

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

### The five that were open on 2026-08-05

**38 registries nothing could fill** (FS-467). `initialize_registries_for_organization`
created one for every mapped domain; only 8 can receive an item. Writing extractor keywords
for `INNOVATION_RD` and `KNOWLEDGE_MANAGEMENT` would have been product scope invented to
satisfy a count, so the initializer now creates only what something can fill, from a set
DERIVED from the extractor rather than listed beside it. Closing it exposed a second defect:
the analysis-to-item path carried the comment "Get or create registry for domain" above code
that only got, returning None and dropping the item. Harmless while all 46 existed; a silent
loss the moment they did not. **Narrowing creation without fixing that would have traded a
cosmetic problem for a data-loss one.**

**Five phantom `Location`/`Address` fields** (FS-469). Not debt: they describe
`shipments.origin`, which the server declares `Dict[str, Any]`. Asking "does the backend send
`contactEmail`" of an uncontracted field gets an answer that means nothing. The sweep now
derives which types are client-constructed — seeded from response types and closed
transitively over field references — and the exemption for `Location` is checked against the
backend schema, so it expires by itself if that field is ever contracted. The first version
had no closure and exempted 34 types including `GeofenceAlert`: **too broad silences real
debt, which is worse than the five meaningless entries it set out to remove.**

**The doubled logistics prefix** (FS-468). Twelve paths served at
`/api/v1/logistics/logistics/…`. The blocker was never the edit — dropping the prefix
collided with `fleet_logistics` on two paths, and the router registering first would have
silently won. `fleet_logistics` is canonical: response models, the HOS fix that stopped an
unreported driver counting as compliant, and the paths the frontend calls. The
correlation-flavoured variants moved under `/correlation/`. A guard now fails any route that
repeats an adjacent segment, which is the shape a prefix collision produces.

**Two PUT handlers replacing rather than patching** (FS-470). One was a detector false
positive — `kanban.update_task` dumps nested checklist items, not the patch body — and the
detector now checks that `model_dump()`'s receiver is the handler's own parameter, so the
distinction is read from the code instead of carried as an allowance. The other was correct
PUT semantics with a silent trap: every field defaulted, so a partial body reset six
retention settings. It takes a model requiring all seven now, so a partial body is a 422
naming the missing field. **The verb did not need to change; the trap did.**

**The agent reporting health twice** (FS-466). Two heartbeat paths carried overlapping facts
under two names. The HTTP one has a consumer, so the Kafka payload was narrowed to identity —
and the agent stopped reading its SQLite buffer on every beat to fill fields the cloud
discarded. This entry is also the one that had been **written with a wrong conclusion** and
corrected; see Rule 92.


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
