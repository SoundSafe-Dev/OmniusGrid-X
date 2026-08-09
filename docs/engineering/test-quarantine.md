# The test quarantine

A test CI refuses to run is a decision. This is where that decision is written down, given
an owner and an expiry date, and checked — in both directions — against what CI actually does.

The register lives in [`backend/tests/test_quarantine.py`](../../backend/tests/test_quarantine.py).
It is a test suite, not a document, so it fails the build rather than going stale.

---

## Why it exists

`ci-cd.yml` once carried three `--ignore` and two `--deselect` flags behind a comment saying
*"pre-existing, owned by the intake/parsing lane"*. Nothing recorded who owned them, what was
actually wrong, or when they should be revisited. That is how a temporary exclusion becomes
permanent: the flag outlives everyone's memory of why it is there, and CI quietly stops
covering six things while reporting green.

The register closes the three ways an informal quarantine fails:

| Failure mode | What the register does |
|---|---|
| **No deadline** | Every entry carries `expires`. The suite fails once that date passes. |
| **No diagnosis** | "Fails at collection" is not a diagnosis. Each entry records the actual cause, so the owner starts from a fact instead of a re-investigation. |
| **No staleness check** | Each quarantined target is *run*, in a subprocess. If it now passes, the suite fails — because CI is skipping working coverage. |

A fourth guard, `TestRegisterMatchesCI`, asserts the register and the workflow are the same
set in both directions. An exclusion added to CI with no entry here fails the build; an entry
CI no longer excludes fails it too.

**It is not a place to park your own failures.** Adding an entry costs an owner, a real
diagnosis and a date, and the entry starts failing on that date. That is deliberately more
work than fixing most things.

---

## Currently quarantined

**Nothing.** The register is empty as of 2026-08-04, and CI runs every test with no
deselects.

### The last entry, and why it took two months

`tests/test_document_domain_mapper.py::test_map_section_to_domain_table_content` was the
only survivor of the original five, and the only one that ever needed a judgement rather
than a rewrite. This register stated the choice correctly:

> either table-content mapping has a gap, or the expectation was never right. Deciding needs
> the lane that owns the keyword sets.

**It was the gap.** `COLUMN_KEYWORD_DOMAIN_MAP` contained no asset word and no failure word
anywhere in it — in a platform whose central noun is an asset. `git log` settled the rest:
the test was added in the same commit as the mapper, against a byte-identical keyword map,
so it had **never passed**. It was not a regression anyone introduced; it was a reasonable
expectation written against an incomplete vocabulary.

The red test was not the cost. `document_scenario_builder` does `if domain is None:
continue`, so a document table keyed on `asset_id` produced **no correlation scenario at
all** while the page still reported as processed. Silent omission behind a quarantined test
that read as a taxonomy argument.

Widening a keyword list can misroute, so the fix is pinned from both sides: a table carrying
`defect` and `inspection` still resolves to quality even with an `asset_id` column (scoring
takes the highest-scoring domain, not the first hit), and a table with no operational
vocabulary still resolves to nothing.

**This is the entry that justifies the register's own rule** — recorded here after the
2026-07-30 release and proved again now:

> before accepting that a quarantined test is another lane's problem, check whether the code
> under it is *running*.

It was running. On every intake.

---

## The release of 2026-07-30, and the assumption that nearly kept it closed

Four entries came off in one change. All four were the same defect, and **none needed a
production change**:

| Target | Outcome |
|---|---|
| `tests/test_image_scenario_builder.py` | rewritten, 6 tests |
| `tests/test_cross_file_scenario_builder.py` | rewritten, 7 tests |
| `tests/test_document_scenario_builder.py` | rewritten, 8 tests |
| `test_image_domain_mapper.py::test_map_image_domains` | repaired |

### What the register believed

Both registers recorded these as tests *"written against an API that never shipped"*, owned by
the intake lane, not to be touched. The note in `test_ci_quarantine_expires.py` reasoned that
fixing the import *"would surface a body of failing expectations I would then be tempted to
edit"* — a good instinct about scope creep, applied to the wrong facts.

### What was actually true

Half of it held: the API those tests wanted never shipped. The half that mattered did not.

The builders under test are **live on the intake path**. `nlp_correlation.py:1594/1655/1794`
and `analysis_sessions.py:972` call them on every intake. CI was not skipping an unbuilt
feature — it was skipping coverage of code running in production.

> **The rule this earned:** before accepting that a quarantined test belongs to another lane,
> check whether the code under it is *running*. "The test is broken" and "the feature is
> unbuilt" look identical from the quarantine list and have opposite consequences. One grep
> for the module's callers separates them.

### It was not a rename

The register described these as one-line import mismatches — `build_image_scenarios` vs
`build_scenarios` — which made them look like two-minute fixes. Renaming the import gets you
to the next error, not to a passing test. The whole contract had changed in merge `42ed66d8`:

| | Tests expected (2026-06-08) | Modules export (since 2026-07-17) |
|---|---|---|
| Domain input | bare `{section_id: domain}` dict | `ImageDomainMapping` / `DocumentDomainMapping` object |
| Return | `list` | generator |
| Scenario ids | `img1-image-0`, `doc1-section-0` | `img1-img-000000`, `doc1-docsec-000000` |
| Extraction text key | `"text"` | `"extracted_text"` |
| `source_ids` / `shared_keys` | on `CorrelationScenario` | in each metric's `payload_snapshot` |
| Entry point | `ImageScenarioBuilder().build(...)` | module-level function |

An unclassifiable image also stopped mapping to `None` and started being absent from
`.image_domains` and listed in `.unmapped_images` instead.

### What the rewrites assert

Not "whatever the code currently does" — that produces a change-detector that passes forever
and catches nothing. Each test asserts a contract the module's own docstring states:

- one scenario per image in `image` mode, a single spanning scenario in `batch` mode;
- cross-file sources grouped by shared key, with pairwise `CrossDomainLink`s on that key;
- a grouped document scenario taking the severest wording in the group (`critical` → 0.9);
- unmapped inputs skipped rather than emitted without a domain;
- manual keys absent from every source grouping nothing.

---

## Working with it

```bash
# The register and its staleness checks
cd backend && pytest tests/test_quarantine.py tests/test_ci_quarantine_expires.py

# What CI runs
pytest --cov=app --cov-fail-under=54 \
  --deselect tests/test_document_domain_mapper.py::test_map_section_to_domain_table_content
```

**To release an entry:** fix the test, then remove it from `REGISTER` in `test_quarantine.py`,
from `IGNORED_FILES`/`DESELECTED` in `test_ci_quarantine_expires.py`, **and** from the flags in
`ci-cd.yml`. Leave any one of the three and a guard fails — which is the point.

**To add one:** you need an owner, a diagnosis that names the actual cause, and an expiry.
Prefer fixing the test.

---

## Known wart: two registers

The quarantine is tracked in **two** files — `test_quarantine.py` and
`test_ci_quarantine_expires.py` — which hold overlapping lists, check them against the same
workflow, and must both be hand-edited for every change. Two sources of truth for "what is CI
skipping" is precisely the drift these registers exist to prevent, and they cannot catch it in
each other.

Tracked as pool item **2b**: collapse to one register, with the other importing it.

A related sharp edge, already fixed: `TestTheSweepIsNotVacuous` asserted `--ignore=` was
present in the workflow unconditionally, so emptying `IGNORED_FILES` made a guard fail for the
*good* outcome it exists to encourage. It now asserts each flag form only while its own
register has entries. A vacuity guard has to be conditional on the thing it is guarding, or it
becomes a reason not to clean up.
