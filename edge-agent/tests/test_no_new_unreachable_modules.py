"""460 lines of edge agent that no production code imports. This stops it growing (FS-506).

The backend has had this guard since its 7,726-line inventory
(`backend/tests/test_no_new_unreachable_modules.py`). The agent never did, and it has the same
problem in miniature — with one twist that makes it *harder* to see rather than easier.

**RESOLVED AND REMOVED (FS-759): `compression.py`.** Its entry said the missing half was the
receiver — "needs a backend decision first — this is half a protocol, not unfinished wiring".
The decision was made: `backend/app/services/wire_codec.py` decodes the framing, the heartbeat
ack advertises which codecs it can read, and `main.py`'s uplink serialiser compresses only
what the backend said it can decode. The entry is deleted rather than reworded, which is the
outcome this register exists to produce — an entry leaving the list because the decision got
made, not because somebody got tired of it.

**Three of the four were tested.** `aggregation.py` and `compression.py` are exercised by
`test_dataplane_robustness.py`; `config_reload.py` has a file of its own. Coverage reports them
green, the suite counts them, and a reader browsing the tree finds a documented feature with
passing tests. Nothing distinguishes that from a feature that runs. **A test is evidence the
code is correct, never evidence that anything calls it** — which is the shape FS-490 named
("counted what does not run") arriving at a different layer.

Each entry below states what is specifically missing, because "unused" is the observation, not
the reason. Two of them are missing a counterpart that does not exist anywhere in the product,
which is a materially different situation from "nobody got round to the wiring":

  * `compression.py` frames its output as `codec_marker + body`, and **no backend code
    decodes it** — `grep gzip.decompress backend/app` is empty. Turning it on would make every
    uplink undecodable. It is half a protocol, and the half that ships is the wrong one.
  * `config_reload.py` needs a trigger. `main.py` installs no signal handler and the command
    consumer registers no `reload_config` action, so there is no path by which a reload could
    be asked for.

WHY NOT JUST DELETE THEM. Deleting `compression.py` throws away a correct implementation of
half a feature whose other half is a backend decision nobody has made; deleting
`aggregation.py` preempts a per-collector config decision (and its key would have to join
`CROSS_CUTTING_KEYS`, FS-500). The point of this file is that those decisions get **made**
rather than accumulate, and that a fifth module cannot join the list quietly.

DETECTOR NOTE. The first version reported `main.py` as unreachable, which is true and useless:
it is the entrypoint (`pyproject.toml:21`, `Dockerfile:49`). An inventory that flags the
program itself is one nobody reads twice — the backend's header records being wrong the same
way, by a much larger factor. Entrypoints are excluded by name and the exclusion is asserted
against the packaging metadata, so it cannot quietly grow.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "opsgrid_agent"

#: Modules launched by something other than an import. Held to the packaging metadata below so
#: this cannot become a place to hide a module by calling it an entrypoint.
ENTRYPOINTS = {"opsgrid_agent/main.py"}

#: Every module no production code imports, with what is specifically missing.
UNREACHABLE: dict[str, str] = {
    "opsgrid_agent/aggregation.py":
        "83 lines, tested by test_dataplane_robustness.py. MISSING: an opt-in config key and "
        "a flush loop calling `WindowAggregator.collect_due`. The key would be the fifth "
        "cross-cutting one and must join CROSS_CUTTING_KEYS in the same change, or a strict "
        "collector dies on it (FS-500). Whether per-sensor fidelity is negotiable is a "
        "product decision, not a wiring one.",
    "opsgrid_agent/config_reload.py":
        "114 lines with a dedicated test file. MISSING: a trigger. main.py installs no signal "
        "handler and commands/consumer.py registers no `reload_config` action, so there is no "
        "path by which a reload could be requested. The diff logic is pure and correct; it "
        "has never had a caller.",
    "opsgrid_agent/ota/model_executor.py":
        "220 lines and the only one here with NO tests (FS-507). It is also the only one that "
        "is actively dispatched to: rollout_orchestrator.py:297 sends `model_update` for "
        "every model release and the agent answers `unknown_action`, because nothing "
        "constructs this class so `register()` never runs. Paired by "
        "backend/tests/test_dispatched_commands_have_a_handler.py (FS-505). Owner: Hridyansh.",
}


def _imported_names(paths) -> set[str]:
    """Every module name any of `paths` imports, by last segment.

    Last-segment matching is deliberately loose. The backend's header records that counting
    `ImportFrom(module=...)` alone reported 57 dead modules because `from app.api import
    alarms` records `app.api`; recording each imported *name* too is what took it to the real
    18. Same correction, applied here from the start.
    """
    names: set[str] = set()
    for path in paths:
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name.split(".")[-1])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.add(node.module.split(".")[-1])
                for alias in node.names:
                    names.add(alias.name)
    return names


def _unreachable_modules() -> set[str]:
    """Modules under `opsgrid_agent/` that no production module imports."""
    production = list(PKG.rglob("*.py")) + list(ROOT.glob("*.py"))
    imported = _imported_names(production)
    return {
        str(path.relative_to(ROOT))
        for path in sorted(PKG.rglob("*.py"))
        if path.name != "__init__.py"
        and path.stem not in imported
        and str(path.relative_to(ROOT)) not in ENTRYPOINTS
    }


class TestTheEntrypointExclusionIsHonest:
    def test_every_excluded_entrypoint_is_declared_as_one(self):
        """Otherwise ENTRYPOINTS is just an allowlist with a flattering name."""
        packaging = (ROOT / "pyproject.toml").read_text() + (ROOT / "Dockerfile").read_text()
        for entry in ENTRYPOINTS:
            module = entry.removesuffix(".py").replace("/", ".")
            assert module in packaging, (
                f"{entry} is excluded from the dead-module sweep as an entrypoint, but "
                f"`{module}` appears in neither pyproject.toml nor the Dockerfile. Either it "
                f"is launched some way this test cannot see — say how — or it belongs in "
                f"UNREACHABLE like everything else."
            )


class TestNothingNewGoesUnreachable:
    def test_no_module_has_joined_the_list(self):
        new = sorted(_unreachable_modules() - set(UNREACHABLE))
        assert not new, (
            f"{new} is imported by no production module. Tests importing it do not count — "
            f"three of the four modules already on this list are fully tested and none of "
            f"them runs. Wire it, delete it, or add it to UNREACHABLE with what is "
            f"specifically missing."
        )

    @pytest.mark.parametrize("module", sorted(UNREACHABLE))
    def test_every_listed_module_is_still_unreachable(self, module: str):
        """A stale entry is worse than none: it reports a wired feature as dead, so the next
        reader distrusts the whole list. FS-504 was exactly this, on a different allowlist."""
        if not (ROOT / module).exists():
            return  # deleted, which is one of the two acceptable outcomes
        assert module in _unreachable_modules(), (
            f"{module} is imported by production code now — the wiring it was waiting for "
            f"exists. Delete its entry from UNREACHABLE; the decision it was holding open "
            f"has been made."
        )

    @pytest.mark.parametrize("module,reason", sorted(UNREACHABLE.items()))
    def test_every_reason_says_what_is_missing(self, module: str, reason: str):
        """`"unused"` is the observation, not the reason."""
        assert len(reason) > 80 and ("MISSING" in reason or "Owner" in reason), (
            f"the entry for {module} does not say what is specifically missing or who owns "
            f"it. An entry here is a claim that somebody looked."
        )


class TestTheDetectorIsNotVacuous:
    def test_it_finds_the_modules_that_are_reachable_too(self):
        """If the import walk broke, `_unreachable_modules()` returns most of the package and
        the assertion above would fail loudly — but if it broke the *other* way and matched
        everything, the sweep silently proves nothing."""
        unreachable = _unreachable_modules()
        total = sum(1 for p in PKG.rglob("*.py") if p.name != "__init__.py")
        assert len(unreachable) < total / 2, (
            f"{len(unreachable)} of {total} modules read as unreachable; the import walk is "
            f"broken, not the agent"
        )
        assert "opsgrid_agent/collectors/coordinator.py" not in unreachable, (
            "the coordinator, which main.py imports directly, reads as unreachable"
        )
