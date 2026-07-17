# Handoff → Harsh: two real-DB 500s in your lane

**From:** Hamad (convergence integration)
**Date:** 2026-07-16
**Branch:** `hamad/converged-pre-main`
**How found:** smoke-testing all 244 GET endpoints against a *migrations-built*
Postgres (not SQLite create_all) after the 039/040 schema-drift fix. 8 of the 10
5xx were in my lane and are fixed (`FS-86..88`, commit `63e46036`). These two are
correctness bugs in your lane (correlation / kanban), so I did **not** touch them.

Both reproduce with a dev-token GET against any migrations-built Postgres:

```bash
curl -H "Authorization: Bearer dev-token" localhost:8002/api/v1/kanban/rules/premade
curl -H "Authorization: Bearer dev-token" localhost:8002/api/v1/nlp/correlation/intake/<any-uuid>
```

---

## Bug 1 — `GET /api/v1/kanban/rules/premade` → 500

**Location:** `backend/app/api/kanban.py:1454-1529`
(`get_premade_rules`, `response_model=List[TaskRuleResponse]`).

**Root cause:** the endpoint returns a hard-coded `premade_templates` list whose
items do **not** satisfy `TaskRuleResponse`. FastAPI raises ~50 response-validation
errors. Per template:
- `"id": "template-001"` — not a UUID (`TaskRuleResponse.id` is a `UUID`).
- missing required fields `organization_id`, `is_active`, `target_board_id`.

So it 500s 100% of the time — it has never returned a valid body on any DB.

**Suggested fix (your call):**
- *Cleanest:* give the premade catalog its own response schema, e.g.
  `PremadeRuleTemplate` (string `template_id`, no org scoping, no `is_active`),
  and set `response_model=List[PremadeRuleTemplate]`. These are static catalog
  entries, not persisted rules, so they shouldn't share `TaskRuleResponse`.
- *Quick:* synthesize conforming values (a stable `uuid5` from the template key,
  `organization_id=current_user.organization_id`, `is_active=True`,
  `target_board_id=None`) — but that fabricates identity for non-persisted rows.

---

## Bug 2 — `GET /api/v1/nlp/correlation/intake/{intake_id}` → 500

**Location:** `backend/app/api/nlp_correlation.py:1888-1901` (`get_intake_item`).

**Root cause:** line 1901 builds the query against the **Pydantic** model, not the
ORM model:

```python
query = select(IntakeItem).where(...)   # IntakeItem is the BaseModel at line 1082
```

`IntakeItem` (line 1082) is a `pydantic.BaseModel`; the ORM model is imported and
aliased at line 21 as `IntakeItemModel`. SQLAlchemy then raises:
`Column expression, FROM clause, or other columns clause element expected, got
<class 'app.api.nlp_correlation.IntakeItem'>`. Note `analyze_intake` (line 1334)
already uses `IntakeItemModel` correctly — this handler just missed the alias.

**Suggested fix (one word):** `select(IntakeItem)` → `select(IntakeItemModel)` at
line 1901 (and check the rest of `get_intake_item` maps rows via the ORM object).

---

Ping me if you'd like me to land either fix on the convergence branch instead —
they're small, but they're your lane so I'm leaving them to you.
