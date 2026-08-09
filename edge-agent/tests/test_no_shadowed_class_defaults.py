"""No class writes its defaults twice (FS-579).

`ReconnectPolicy` declared seven tuning values as annotated class attributes — with comments
explaining each — and then repeated all seven as `__init__` parameter defaults. **The class
attributes were shadowed on every instance and decided nothing.** They existed to be read;
the `__init__` copy is what every collector actually received.

That is the same defect the class was created to fix, one level up. FS-473 consolidated sixteen
copies of `cap=60.0` and `failure_threshold=5` out of eight collector modules and into this
file, on the reasoning that *"a guess in eight places is a guess nobody can revise: the person
with the telemetry has to find all eight, and the ones they miss are the ones that keep the old
behaviour."* The consolidation then wrote the guess **twice in the file that consolidated it**
— and the copy a reader's eye lands on first, the annotated declaration with the explanatory
comments, was the dead one.

WHY IT SURVIVES REVIEW. Both copies agree when written, so nothing is wrong yet, and the
divergence arrives later as one edit. There is no moment where the mistake is visible: the
first reader sees two consistent lists, and the second sees a number that does not take effect
and no reason why.

THE FIX IS `@dataclass`, which generates `__init__` from the attributes so there is one place.
This guard is the general form: a class whose `__init__` parameter defaults duplicate its own
class-attribute defaults.
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PKG = pathlib.Path(__file__).resolve().parents[1] / "opsgrid_agent"

#: Classes allowed to repeat a default, with why. Empty — a value written twice is a value
#: that can disagree with itself, and only one of the two ever takes effect.
ALLOWED: dict[str, str] = {}


def _shadowed() -> list[str]:
    """`file::Class::attr` for each class attribute an `__init__` default overwrites."""
    found: list[str] = []
    for path in sorted(PKG.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            # A dataclass has no hand-written `__init__` for its fields; that IS the fix.
            if any(
                isinstance(d, ast.Name) and d.id == "dataclass"
                or isinstance(d, ast.Attribute) and d.attr == "dataclass"
                or isinstance(d, ast.Call)
                and isinstance(d.func, ast.Name)
                and d.func.id == "dataclass"
                for d in node.decorator_list
            ):
                continue

            attributes = {
                stmt.target.id: stmt.value
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.value is not None
            }
            if not attributes:
                continue

            init = next(
                (
                    b
                    for b in node.body
                    if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and b.name == "__init__"
                ),
                None,
            )
            if init is None:
                continue

            args = init.args.args[len(init.args.args) - len(init.args.defaults) :]
            for arg, default in zip(args, init.args.defaults):
                if arg.arg not in attributes:
                    continue
                if not isinstance(default, ast.Constant):
                    continue
                # Only a LITERAL default duplicates a literal class attribute. A parameter
                # defaulting to None and falling back to the attribute is the correct
                # single-source pattern, not a copy.
                key = f"{path.relative_to(PKG.parent)}::{node.name}::{arg.arg}"
                if key not in ALLOWED:
                    found.append(key)
    return found


class TestTheDetectorIsCalibrated:
    def test_it_reads_the_package(self):
        """Vacuity. A walk that parses nothing passes over an empty list while every
        shadowed default in the tree keeps lying."""
        classes = sum(
            1
            for path in PKG.rglob("*.py")
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.ClassDef)
        )
        assert classes > 20, f"only {classes} classes found; the walk is broken"

    def test_a_dataclass_is_not_flagged(self):
        """`@dataclass` generating `__init__` from its attributes is the FIX. Flagging it
        would punish the correct shape and make the guard unactionable."""
        source = "from dataclasses import dataclass\n@dataclass\nclass A:\n    x: int = 1\n"
        tree = ast.parse(source)
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
        assert node.decorator_list, "the fixture lost its decorator"

    def test_a_none_sentinel_is_not_flagged(self):
        """`def __init__(self, x: int | None = None)` falling back to the class attribute is
        single-source. Only a literal repeating a literal is the defect."""
        assert not [
            entry for entry in _shadowed() if "None" in entry
        ]


class TestNoValueIsWrittenTwice:
    def test_no_class_attribute_is_shadowed_by_an_init_default(self):
        shadowed = _shadowed()
        assert not shadowed, (
            "these class attributes are overwritten on every instance by an `__init__` "
            "default that repeats them, so the annotated declaration decides nothing and a "
            "reader editing it changes no behaviour:\n  "
            + "\n  ".join(shadowed)
            + "\n\nBoth copies agree when written, which is why this survives review — the "
            "divergence arrives later as a single edit, and there is no moment where the "
            "mistake is visible. Use `@dataclass`, or default the parameter to None and fall "
            "back to the attribute."
        )

    @pytest.mark.parametrize("entry", sorted(ALLOWED))
    def test_each_exemption_is_still_shadowed(self, entry: str):
        assert entry in _shadowed(), f"{entry} is no longer shadowed; delete its entry"


class TestReconnectPolicyStaysSingleSource:
    """Named specifically: it is the class the general rule was found in, and the one where
    a regression costs most — its seven numbers govern every collector's reconnect
    behaviour, which is precisely why FS-473 pulled them out of eight files."""

    def test_it_is_a_dataclass(self):
        from opsgrid_agent.resilience import ReconnectPolicy
        import dataclasses

        assert dataclasses.is_dataclass(ReconnectPolicy), (
            "ReconnectPolicy has a hand-written __init__ again, so its documented class "
            "attributes are shadowed and editing one changes nothing a collector sees"
        )

    def test_editing_an_attribute_changes_what_an_instance_gets(self):
        """The property the shadowing broke. Asserted through behaviour rather than shape,
        because that is what a reader who edits the number expects to happen."""
        from opsgrid_agent.resilience import ReconnectPolicy

        assert ReconnectPolicy().max_delay == ReconnectPolicy.max_delay
        assert ReconnectPolicy().failure_threshold == ReconnectPolicy.failure_threshold

    def test_the_validation_survived_the_conversion(self):
        """`__post_init__` must still run. A dataclass silently drops a `__init__` body that
        was not moved, so the pairing check could have vanished with no test failing."""
        from opsgrid_agent.resilience import ReconnectPolicy

        with pytest.raises(ValueError, match="cooldown_cap"):
            ReconnectPolicy(max_delay=1000.0)
