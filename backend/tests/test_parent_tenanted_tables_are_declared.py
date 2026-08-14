"""A table with no `organization_id` is invisible to RLS, and that must be a decision (FS-721).

Most tenant tables carry `organization_id` and a policy of the usual shape, so
`get_tenant_db` filters them and a handler that forgets its `WHERE` is still safe. **Fifteen
tables do not.** Their tenant is whoever owns the row's PARENT — an operation belongs to the
organisation that owns its asset, a task comment to whoever owns the board behind the task —
so RLS does nothing for them and every handler is on its own.

WHAT THAT COST (FS-720). `operations` is one of the fifteen. Four of its five handlers
selected by id, or not at all:

    GET  /operations/                     bare select(Operation)   every tenant's rows
    GET  /operations/{id}                 by id                    any tenant's
    GET  /operations/{id}/packml-summary  by id                    any tenant's
    POST /operations/{id}/complete        by id                    any tenant's, and WROTE

An authenticated operator could finish another organisation's production run. The fifth
handler joined `assets` under a comment reading "THE TENANT JOIN IS NO LONGER OPTIONAL",
written when the same defect was found there — fixed on one handler of five.

THE SWEEP THAT FOLLOWED, and why this file is a register rather than a detector. Every
`select()` of these fifteen models in `app/api` was read: 40 sites across six routers. All
but `operations` follow the convention — verify the PARENT with an explicit organisation
predicate (or a user predicate), then query children by the parent's id.
`telemetry.get_telemetry_history` calls `_verify_asset_in_org` first; `registries` selects
its `ActionableRegistry` with `organization_id == current_user.organization_id` before
touching items; `gdpr` scopes consents by `current_user.id`, which is narrower still.

Deciding statically whether a parent was verified means following an id through a handler,
and a detector that guesses would either miss the real thing or cry wolf until somebody
adds an exemption (rule 211). So this file asserts the part that IS decidable and that
actually failed: **which tables are in this category at all.** A new one arriving unnoticed
is how the next `operations` happens — the author reasonably assumes the session is doing
the work, because for every other table in sight it is.
"""

from __future__ import annotations

import pathlib
import re

import pytest

MODELS = pathlib.Path(__file__).resolve().parents[1] / "app" / "db" / "models.py"

#: model -> how its tenant is determined. Every entry is a claim that somebody checked the
#: handlers that read it. A table joins this list only by deliberate decision: the usual
#: answer is to give it an `organization_id` and a policy like everything else.
PARENT_TENANTED: dict[str, str] = {
    # --- the asset tree -------------------------------------------------------------
    "Operation": "assets.organization_id — FS-720; all five handlers now go through "
                 "`_own_operation`, which joins and filters",
    "Telemetry": "assets.organization_id — `_verify_asset_in_org` runs before any read",
    "PackMLState": "assets.organization_id, via the operation it belongs to",
    # --- the kanban tree, Harsh's lane ----------------------------------------------
    "TaskColumn": "task_boards.organization_id",
    "Task": "task_boards.organization_id, through the board fetched for the caller",
    "TaskComment": "the task, which is fetched board-scoped first",
    "TaskTimer": "the task, same route as its comments",
    "TaskEscalation": "the task and its rule",
    # --- analysis sessions, Harsh's lane --------------------------------------------
    "SessionDataSource": "analysis_sessions.organization_id — that table IS under RLS, so "
                         "a data source is reachable only through a session the caller can see",
    "SessionMessage": "analysis_sessions.organization_id, same as its data sources",
    # --- per-USER rather than per-organisation, which is narrower -------------------
    "UserSession": "users.id — scoped to the authenticated user, not merely their org",
    "RevokedToken": "the user session it revokes",
    "ConsentRecord": "users.id — GDPR consents are the user's own",
    # --- other -----------------------------------------------------------------------
    "ActionableRegistryItem": "actionable_registries.organization_id — the registry is "
                              "selected with an explicit org predicate before its items are",
    "ErrorEventBucket": "error_events, which carries the organisation",
}


def _models() -> dict[str, tuple[str, bool, list[str]]]:
    """class -> (table, carries organization_id, foreign-key parents)."""
    source = MODELS.read_text()
    out: dict[str, tuple[str, bool, list[str]]] = {}
    for match in re.finditer(r"class (\w+)\(Base\):(.*?)(?=\nclass |\Z)", source, re.S):
        name, body = match.groups()
        table = re.search(r"__tablename__\s*=\s*['\"](\w+)['\"]", body)
        if not table:
            continue
        parents = sorted(
            set(re.findall(r"UUIDForeignKey\(\s*['\"](\w+)\.", body))
            | set(re.findall(r"ForeignKey\(\s*['\"](\w+)\.", body))
        )
        out[name] = (table.group(1), "organization_id" in body, parents)
    return out


def _parent_tenanted() -> set[str]:
    return {
        name
        for name, (_table, has_org, parents) in _models().items()
        if not has_org and parents
    }


class TestTheMeasurementIsReal:
    def test_the_models_parse(self):
        """Vacuity. If the model regex breaks, every table looks org-carrying and this file
        passes over an empty set — the shape a register cannot survive."""
        models = _models()
        assert len(models) > 60, f"only {len(models)} models parsed"
        assert sum(1 for _t, has_org, _p in models.values() if has_org) > 30, (
            "almost nothing carries organization_id; the column check is broken"
        )

    def test_a_known_org_carrying_table_is_not_listed(self):
        """`Asset` has its own `organization_id` and a policy, so it must never appear
        here. If it did, the detector would be reporting the wrong half of the tree."""
        assert "Asset" not in _parent_tenanted()


class TestTheListIsExact:
    def test_no_new_table_is_parent_tenanted_without_a_decision(self):
        new = sorted(_parent_tenanted() - set(PARENT_TENANTED))
        assert not new, (
            f"{new} have no `organization_id`, so no RLS policy protects them and "
            f"`get_tenant_db` does nothing for their rows — every handler must scope them "
            f"by hand, through the parent. That is how `operations` leaked four handlers "
            f"(FS-720). Give the table an `organization_id` and a policy, or add it here "
            f"naming the parent its tenancy comes from."
        )

    def test_no_entry_has_gained_an_organization_id(self):
        stale = sorted(set(PARENT_TENANTED) - _parent_tenanted())
        assert not stale, (
            f"{stale} are registered as parent-tenanted and now carry their own "
            f"organization_id — delete the entries rather than leaving them to describe a "
            f"schema that has moved on"
        )

    @pytest.mark.parametrize("model", sorted(PARENT_TENANTED))
    def test_every_entry_names_the_parent_it_inherits_from(self, model: str):
        reason = PARENT_TENANTED[model]
        assert len(reason.strip()) > 20, f"{model} is registered without naming its parent"
        assert any(word in reason for word in ("organization_id", "users.id", "the task", "the user", "error_events")), (
            f"{model}'s entry does not say where its tenant comes from: {reason!r}"
        )
