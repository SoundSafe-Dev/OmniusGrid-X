"""A metric that is DEFINED but never OBSERVED exports no series, and every guard we had said it was fine (FS-774).

WHAT THIS FOUND, and it had been true for the whole life of the rules.

`APIHighErrorRate` — **severity: critical** — is built on `opsgrid_http_requests_total`.
So are `APIErrorRateElevated` and `APILatencyP95High`. That counter is defined in
`app/middleware/profiling.py` and incremented in exactly one place, line 239, inside
`ProfilingMiddleware.dispatch`. Five lines from the top of that method:

    async def dispatch(self, request, call_next):
        if not PROFILING_ENABLED:
            return await call_next(request)

`PROFILING_ENABLED` defaults to False (`profiling.py:60`) and is set in NO environment —
not docker-compose, not any kustomize overlay, not CI. So the counter has never been
incremented anywhere, the series has never existed, and the three alerts built on it —
one of them the critical API error-rate page — have never been capable of firing.

WHY THE EXISTING SWEEP MISSED IT. `test_every_alert_watches_a_series_something_exports`
collects metric names by AST from `Counter(...)`/`Gauge(...)` constructor calls. That
answers "is this metric declared", which is the FS-695 question. It cannot answer "is
this metric ever incremented on a path that runs", and a declaration is what a
disabled feature flag leaves behind. The metric is declared, importable, and present in
the default registry — it simply has no children, so `/metrics` omits it entirely.

This file asks the narrower question the class actually turns on: **for every metric an
alert depends on, is there at least one write site not sitting behind a boolean that
defaults to False?**
"""

from __future__ import annotations

import ast
import functools
import pathlib
import re

from tests.test_every_alert_watches_a_series_something_exports import CODE_ROOTS

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
ALERTS = REPO / "infra" / "prometheus" / "alerts.yml"
SLO_RULES = REPO / "infra" / "prometheus" / "slo_rules.yml"
#: CODE_ROOTS is IMPORTED, not restated. Both sweeps ask about the same population —
#: every module that could export a metric series — so a second copy is one fact
#: written twice, and the two would drift the first time a codebase moved.

#: Deployment surfaces that can turn a flag on. A flag defaulting to False is only a
#: defect if nothing anywhere enables it.
DEPLOYMENT_FILES = [
    REPO / "docker-compose.yml",
    REPO / "infrastructure",
    REPO / ".github",
]

#: Metrics written only behind a flag, where that is DELIBERATE and no alert may depend
#: on them. Adding an entry is a statement that the metric is diagnostic, not alertable.
DIAGNOSTIC_ONLY: dict[str, str] = {
    "opsgrid_http_slow_requests_total": (
        "profiling-only; the alertable latency signal is http_request_duration_seconds "
        "from RequestContextMiddleware, which is unconditional"
    ),
    "opsgrid_http_request_db_queries": "profiling-only; per-request DB query attribution",
}


def _flag_defaults_false(module: ast.Module) -> set[str]:
    """Module-level names bound to a falsy-by-default boolean env lookup.

    Matches the two idioms in this tree:
        PROFILING_ENABLED: bool = _env_bool("PROFILING_ENABLED", False)
        ERROR_TRACKING_ENABLED = os.getenv("...", "false").lower() == "true"
    """
    flags: set[str] = set()
    for node in module.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        else:
            continue
        if not targets or value is None:
            continue
        source = ast.dump(value)
        # _env_bool("X", False) / _env_bool("X", default=False)
        if "_env_bool" in source and "Constant(value=False)" in source:
            flags.update(targets)
        # os.getenv("X", "false") == "true"
        elif "getenv" in source and re.search(r"value='(?:false|0|no)'", source):
            flags.update(targets)
    return flags


def _guarded_by(func: ast.AST, flags: set[str]) -> set[str]:
    """Flags this function early-returns on: `if not FLAG: return ...` at the top level
    of the body, which is the shape that leaves the rest of the function dead."""
    guarding: set[str] = set()
    for stmt in getattr(func, "body", []):
        if not isinstance(stmt, ast.If):
            continue
        test = stmt.test
        if (
            isinstance(test, ast.UnaryOp)
            and isinstance(test.op, ast.Not)
            and isinstance(test.operand, ast.Name)
            and test.operand.id in flags
            and any(isinstance(s, ast.Return) for s in stmt.body)
        ):
            guarding.add(test.operand.id)
    return guarding


@functools.lru_cache(maxsize=None)
def _metric_bindings() -> dict[str, set[str]]:
    """variable name -> exported series names, across BOTH codebases.

    Global rather than per-module on purpose. Metrics in this tree are routinely
    declared in one place and incremented in another — `AUDIT_WRITE_FAILURES` lives in
    `app/core/http_metrics.py` and is written by `app/middleware/audit.py` — so a
    per-module map cannot see the write at all, and a sweep that cannot see a write
    reports the metric as having none, which is indistinguishable from a clean result.
    """
    bound: dict[str, set[str]] = {}
    for root in CODE_ROOTS:
        for path in root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in tree.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                value = node.value
                if not isinstance(value, ast.Call) or not value.args:
                    continue
                kind = getattr(value.func, "id", getattr(value.func, "attr", ""))
                if kind not in {"Counter", "Gauge", "Histogram", "Summary"}:
                    continue
                first = value.args[0]
                if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                    continue
                names = {first.value}
                if kind == "Counter" and not first.value.endswith("_total"):
                    names.add(f"{first.value}_total")
                if kind == "Histogram":
                    names |= {f"{first.value}_{sfx}" for sfx in ("bucket", "sum", "count")}
                if kind == "Summary":
                    names |= {f"{first.value}_{sfx}" for sfx in ("sum", "count")}
                targets = (
                    [t.id for t in node.targets if isinstance(t, ast.Name)]
                    if isinstance(node, ast.Assign)
                    else ([node.target.id] if isinstance(node.target, ast.Name) else [])
                )
                for t in targets:
                    bound.setdefault(t, set()).update(names)
    return bound


@functools.lru_cache(maxsize=None)
def _metric_write_sites() -> dict[str, list[tuple[str, str | None]]]:
    """metric series name -> [(file:line, flag gating it or None)].

    A write is `.inc()`, `.observe()`, `.set()`, `.dec()` on a name bound anywhere to a
    metric constructor.
    """
    sites: dict[str, list[tuple[str, str | None]]] = {}
    bound = _metric_bindings()
    for root in CODE_ROOTS:
        for path in root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text())
            except (SyntaxError, UnicodeDecodeError):
                continue
            flags = _flag_defaults_false(tree)


            # Walk functions, recording which flag (if any) gates each write.
            for func in ast.walk(tree):
                if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                gating = _guarded_by(func, flags)
                gate = sorted(gating)[0] if gating else None
                for node in ast.walk(func):
                    if not isinstance(node, ast.Call):
                        continue
                    if getattr(node.func, "attr", "") not in {"inc", "observe", "set", "dec"}:
                        continue
                    # unwrap  METRIC.labels(...).inc()  and  METRIC.inc()
                    receiver = getattr(node.func, "value", None)
                    if isinstance(receiver, ast.Call):
                        receiver = getattr(receiver.func, "value", None)
                    if not isinstance(receiver, ast.Name) or receiver.id not in bound:
                        continue
                    where = f"{path.relative_to(REPO)}:{node.lineno}"
                    for series in bound[receiver.id]:
                        sites.setdefault(series, []).append((where, gate))
    return sites


@functools.lru_cache(maxsize=None)
def _alerted_metrics() -> dict[str, set[str]]:
    """series name -> alert names that reference it."""
    import yaml

    refs: dict[str, set[str]] = {}
    for rules_file in (ALERTS, SLO_RULES):
        doc = yaml.safe_load(rules_file.read_text())
        for group in doc.get("groups", []):
            for rule in group.get("rules", []):
                name = rule.get("alert") or rule.get("record") or "?"
                expr = rule.get("expr")
                if not isinstance(expr, str):
                    continue
                # PARSED, NOT LINE-SCANNED. `expr: |` block scalars are a quarter of
                # alerts.yml, and the three alerts this file was written to catch are
                # all block scalars — a line-scanning version of this function passed
                # over them and reported the file clean.
                stripped = re.sub(r'"[^"]*"', "", expr)
                for ident in set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{3,}", stripped)):
                    refs.setdefault(ident, set()).add(name)
    return refs


@functools.lru_cache(maxsize=None)
def _flag_enabled_somewhere(flag: str) -> bool:
    for target in DEPLOYMENT_FILES:
        paths = [target] if target.is_file() else list(target.rglob("*"))
        for path in paths:
            if not path.is_file():
                continue
            try:
                text = path.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            if re.search(rf"{re.escape(flag)}\s*[:=]\s*[\"']?(true|1|yes)", text, re.I):
                return True
    return False


class TestTheMeasurementIsReal:
    """Rule 165: a sweep that parses nothing passes over an empty set."""

    def test_it_found_write_sites(self):
        sites = _metric_write_sites()
        assert len(sites) >= 40, f"only {len(sites)} metrics with write sites found"
        # Declared in app/core/http_metrics.py, written from app/middleware/audit.py.
        # Pins the cross-module binding map: a per-module walk misses this entirely.
        assert "opsgrid_audit_write_failed_total" in sites

    def test_it_found_the_flag_gated_write(self):
        """POSITIVE CONTROL. This is the exact site the sweep exists to notice; if the
        AST walk stops seeing it, the guard has gone vacuous rather than clean."""
        sites = _metric_write_sites()
        gates = {gate for _where, gate in sites.get("opsgrid_http_requests_total", [])}
        assert gates == {"PROFILING_ENABLED"}, (
            f"expected the one write site to be gated by PROFILING_ENABLED, got {gates}"
        )

    def test_an_unconditional_write_is_not_reported_as_gated(self):
        """NEGATIVE CONTROL. `http_requests_total` is written by
        RequestContextMiddleware with no flag; a sweep that called everything gated
        would be useless and would also be believed."""
        sites = _metric_write_sites()
        gates = {gate for _where, gate in sites.get("http_requests_total", [])}
        assert None in gates, f"http_requests_total should have an ungated write, got {gates}"

    def test_the_flag_is_read_as_off(self):
        assert not _flag_enabled_somewhere("PROFILING_ENABLED"), (
            "PROFILING_ENABLED is now set somewhere — re-check whether the alerts in "
            "this file's docstring are still inert before relaxing anything."
        )


def test_no_alert_depends_on_a_metric_only_written_behind_a_disabled_flag():
    sites = _metric_write_sites()
    alerted = _alerted_metrics()

    broken: dict[str, dict[str, object]] = {}
    for series, alerts in sorted(alerted.items()):
        writes = sites.get(series)
        if not writes:
            continue  # not ours to judge — the exporter sweep owns that question
        if series in DIAGNOSTIC_ONLY:
            broken[series] = {
                "alerts": sorted(alerts),
                "why": f"registered as diagnostic-only: {DIAGNOSTIC_ONLY[series]}",
            }
            continue
        gates = {gate for _where, gate in writes}
        if None in gates:
            continue  # at least one unconditional write — the series can exist
        live = {g for g in gates if g and _flag_enabled_somewhere(g)}
        if not live:
            broken[series] = {
                "alerts": sorted(alerts),
                "gated_by": sorted(g for g in gates if g),
                "write_sites": [w for w, _g in writes],
            }

    assert not broken, (
        f"These alerts depend on metrics whose every write site sits behind a feature "
        f"flag that defaults to False and is enabled in no environment:\n\n{broken}\n\n"
        f"The metric is DECLARED, so the exporter sweep passes it — but a declared "
        f"metric with no observations has no children and is omitted from /metrics "
        f"entirely. The alert lints, deploys, and can never fire. Either point the "
        f"alert at a series something writes unconditionally, move the write out from "
        f"behind the flag, or enable the flag in the environments that are alerted on."
    )
