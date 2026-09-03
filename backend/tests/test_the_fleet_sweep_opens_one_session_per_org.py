"""edge_fleet_sweep opens one AsyncSessionLocal per org, not two (FS-883).

THE DEFECT. `sweep_once` opened a fresh `AsyncSessionLocal()` to read
`EdgeAgentStatus`, set the tenant GUC, ran the query, closed it — then opened a SECOND
fresh session for the exact same org to set the same GUC again and read `Asset`. Every
sweep interval cost two pooled connections per organisation instead of one, direct
pressure on the ceiling FS-839 sized against `maxReplicas × pool ≤ max_connections`: a
background sweep that never serves a request was competing with request traffic for the
same pool, twice per org, on a timer.

THE FIX. Both queries run inside the same session, after a single `set_config` call —
the GUC and the two reads share one org-scoped connection instead of two.
"""
from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _sweep_source() -> ast.AST:
    """`sweep_once`, isolated by AST rather than line number. Matched by exact name —
    rule 296: a substring or keyword match is a bet nothing else in the file can also
    satisfy it."""
    tree = ast.parse((APP / "services/edge_fleet_sweep.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "sweep_once":
            return node
    raise AssertionError("sweep_once moved or was renamed; this guard is blind")


def _per_org_loop(handler: ast.AST) -> ast.For:
    for node in ast.walk(handler):
        if isinstance(node, ast.For) and "org_id" in ast.unparse(node.target):
            return node
    raise AssertionError("no per-org loop found in sweep_once; this guard is blind")


class TestOneSessionPerOrgNotTwo:
    def test_at_most_one_asyncsessionlocal_inside_the_per_org_loop(self):
        """THE DEFECT ITSELF. Two `AsyncSessionLocal()` opens inside the same iteration
        of the per-org loop is two pooled connections doing the work one connection can
        do — for every organisation, every sweep interval."""
        loop = _per_org_loop(_sweep_source())
        opens = sum(
            1
            for node in ast.walk(loop)
            if isinstance(node, ast.Call) and "AsyncSessionLocal" in ast.unparse(node.func)
        )
        assert opens <= 1, (
            f"{opens} AsyncSessionLocal() opens inside the per-org loop body — expected "
            f"at most 1. Each extra open is a pooled connection acquired and released a "
            f"second time for the same org, competing with request traffic for the same "
            f"pool FS-839 sized against maxReplicas."
        )

    def test_set_config_runs_at_most_once_per_org(self):
        """A second `set_config` inside the same loop iteration is the tell that a second
        session was opened for the same org — the GUC has to be set again because the
        first session's setting died with it."""
        loop = _per_org_loop(_sweep_source())
        body = ast.unparse(loop)
        assert body.count("set_config") == 1, (
            f"set_config runs {body.count('set_config')} times per org iteration; "
            f"expected 1. More than one means more than one session was opened for the "
            f"same org in the same pass."
        )

    def test_both_the_agent_and_asset_reads_are_present(self):
        """The consolidation must not have dropped either read — this sweep answers two
        different liveness questions (FS-695 agents, FS-774 assets) in one pass."""
        loop = _per_org_loop(_sweep_source())
        body = ast.unparse(loop)
        assert "EdgeAgentStatus" in body, "the agent-liveness read is gone from the sweep"
        assert "Asset" in body, "the asset-liveness read (FS-774) is gone from the sweep"
