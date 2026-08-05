# Open decisions

Findings that are **understood, reproduced, and deliberately not fixed** — because closing
each one is a product or contract decision rather than a bug fix.

They are currently recorded in test docstrings, which is the right place for the *reasoning*
and the wrong place for the *decision*: a docstring is read by whoever next edits that file,
and none of these will be closed by that person. This page is where someone deciding can see
them together.

**Every entry is pinned by a test.** None can drift silently, and each names what would have
to change. When one is closed, delete its entry here and the test class that pins it — a
register that outlives its items is the thing this repository keeps finding.

---

## 1. A PDF page's text is truncated at 20,000 characters, silently

**Pinned by** `backend/tests/test_document_intake_parsers.py::TestThePageTextCapIsSilent`
· FS-440

`parse_pdf_structure` stores `text[:20000]` per page and sets no flag. The `truncated` field
in that result covers **only** pages dropped past `max_pages`, so a single dense page over
20,000 characters is cut in half and the document reports `truncated: False`.

The lost half is never chunked, never embedded, and never retrievable. The only symptom is
an answer that does not know something the document said — and nothing in the system can
report it, because nothing else knows what was in the file.

**Why not fixed here:** changing the return shape touches `document_domain_mapper` and
`document_scenario_builder`. That is a decision about the intake contract.

**To close:** raise the cap, or add a per-page truncation flag and have the consumers read
it. Then delete the pinning test class.

---

## 2. 38 registries are created that nothing can fill

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

## 3. Eleven capped lists cannot say they were capped

**Pinned by** `backend/tests/test_capped_lists_cannot_grow.py` (`MAX_UNSIGNALLED = 11`)

An endpoint that caps its result and cannot signal the cap reports a partial answer as a
complete one. Three of the eleven have no consumer today, which is why they are cheap to
leave and easy to forget.

**To close:** give each a `mark_truncated` signal, lower the ratchet. It only ever goes down.

---

## 4. Five declared fields on shapes the server never defines

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

## 5. `logistics_correlation` serves twelve paths at a doubled prefix

**Pinned by** `backend/tests/test_logistics_correlation_scoping_realdb.py`

The router declares `prefix="/logistics"` and `main.py` mounts it at `/api/v1/logistics`, so
its routes serve at `/api/v1/logistics/logistics/…`.

**It is not a routing edit.** Removing the inner prefix lands two of those paths on
`/delivery-efficiency` and `/compliance/summary`, which `fleet_logistics` already serves and
which the frontend actually calls. Whichever router registers first would silently win.

**To close:** decide which implementation is canonical per path, then fix the prefix.

---

## 6. Two PUT handlers replace rather than patch

**Pinned by** `backend/tests/test_partial_updates_do_not_wipe_fields.py` (2 allowances)

Both are recorded with reasons; one is a genuine full-replacement PUT where every field has
a default, which is what PUT means. The other dumps nested checklist items and is a
different shape from the update payload.

**To close:** confirm the intended semantics per route and either narrow the allowance or
switch the verb.

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
