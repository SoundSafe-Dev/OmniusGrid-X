"""`datetime.now()` must be called with a timezone.

THE HAZARD IS AT THE BOUNDARY, not inside Python. A naive datetime is perfectly usable as
long as everything it meets is also naive — which is why the nine bare `datetime.now()`
calls in `model_monitoring` never raised: its drift and performance histories are
in-memory and both sides of every comparison were naive.

What they produced was ISO strings with no offset, while the other 483 datetime
constructions in this codebase emit `+00:00`. `new Date("2026-07-28T02:15:00")` is parsed
by JavaScript as LOCAL time; `new Date("2026-07-28T02:15:00+00:00")` is UTC. The same
instant would render hours apart depending on which endpoint returned it, silently, with
no error anywhere. No frontend consumes those routes today, which is the only reason it
never showed.

The other failure mode is louder and already has a scar: comparing a naive value with an
aware one raises `TypeError`. `fleet_logistics._aware()` exists specifically to coerce
that away, because Postgres returns aware timestamps and SQLite returns naive ones, so the
same code path differs by backend.

WHY AST AND NOT GREP. A text search for `datetime.now()` matches this file's own prose and
the explanatory comment in `model_monitoring`, and would have to be weakened with
exclusions until it stopped meaning anything. The AST sees calls, so a mention in a
docstring is simply not a call. That distinction — measure the object the code operates
on, not the text that contains it — is the same one that made an earlier flake
investigation reach the wrong conclusion for a day.
"""

from __future__ import annotations

import ast
import pathlib
from typing import List, Tuple

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _receiver(node: ast.Call) -> str:
    """The name the method was called on: `datetime` in `datetime.now()`.

    NEEDED BECAUSE `now` IS NOT A UNIQUE NAME. The first version of this check matched
    any call to something named `now` and immediately flagged four uses of SQLAlchemy's
    `func.now()` in `app/db/models.py` — which renders SQL `NOW()`, returns a
    `timestamptz` on Postgres, and is exactly right. Flagging it would have meant
    "fixing" correct code.
    """
    func = node.func
    if not isinstance(func, ast.Attribute):
        return ""
    value = func.value
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    return ""


def _naive_now_calls() -> List[Tuple[str, int]]:
    """Every `datetime.now()` / `datetime.utcnow()` invoked with no timezone."""
    found: List[Tuple[str, int]] = []
    for path in sorted(APP.glob("**/*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # another test's problem
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if _receiver(node) != "datetime":
                continue
            if name == "utcnow":
                found.append((str(path.relative_to(APP)), node.lineno))
            elif name == "now" and not node.args and not node.keywords:
                found.append((str(path.relative_to(APP)), node.lineno))
    return found


def _aware_now_calls() -> int:
    count = 0
    for path in sorted(APP.glob("**/*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name == "now" and (node.args or node.keywords):
                    count += 1
    return count


class TestTheDetectorSeesCallsNotText:
    def test_a_mention_in_a_docstring_is_not_a_call(self):
        tree = ast.parse('"""We used to call datetime.now() here."""\nx = 1\n')
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        assert not calls, "prose is being read as code"

    def test_a_bare_call_is_detected(self):
        tree = ast.parse("import datetime\nd = datetime.datetime.now()\n")
        bare = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "attr", None) == "now"
            and not n.args and not n.keywords
        ]
        assert len(bare) == 1

    def test_sqlalchemy_func_now_is_not_flagged(self):
        """`func.now()` renders SQL NOW() and returns an aware timestamptz on Postgres.
        The first version of this detector flagged four correct uses of it."""
        tree = ast.parse("from sqlalchemy import func\nc = Column(default=func.now())\n")
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "now"
        ]
        assert calls, "fixture does not contain the call it means to"
        assert _receiver(calls[0]) == "func", "the receiver is not being read"

    def test_a_call_with_a_timezone_is_not_flagged(self):
        tree = ast.parse("from datetime import datetime, timezone\nd = datetime.now(timezone.utc)\n")
        bare = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "attr", None) == "now"
            and not n.args and not n.keywords
        ]
        assert not bare


class TestTheSweepIsNotVacuous:
    def test_it_reaches_the_codebase(self):
        assert _aware_now_calls() >= 100, (
            f"only {_aware_now_calls()} timezone-aware now() calls found; the walk is "
            f"not reaching app/ and the assertion below would pass trivially"
        )


class TestEveryNowIsAware:
    def test_no_naive_datetime_construction(self):
        offenders = _naive_now_calls()
        assert not offenders, (
            "These construct a naive datetime. Inside Python that is harmless until it "
            "meets an aware one (TypeError, and Postgres returns aware while SQLite "
            "returns naive); at the API boundary it serialises without an offset, and a "
            "browser reads that as LOCAL time while every other endpoint's timestamps "
            "are UTC:\n  "
            + "\n  ".join(f"app/{path}:{line}" for path, line in offenders)
        )
