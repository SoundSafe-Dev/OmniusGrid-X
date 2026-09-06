"""A bare `except:` catches BaseException, and that includes cancellation (FS-982).

`except:` and `except Exception:` are not two spellings of the same thing.
`asyncio.CancelledError` inherits from BaseException, not Exception, precisely so that a
handler written for "something went wrong" does not eat "you are being shut down". A bare
`except:` eats it anyway, and the failure it produces is one of the worst shapes there is:

  * `collectors/opcua_collector.py` browsed a server's address space child by child inside
    a bare `except:`. On a wide address space, a shutdown cancelling that task had the
    cancellation absorbed and the loop kept going -- the agent appeared to HANG rather than
    stop, and nothing in any log said why.
  * `services/erp_middleware/mulesoft_integration.py` wrapped `await response.json()` in
    one. A cancellation there was reported to the caller as `{"status": "success"}` with no
    data -- a task being torn down, telling its caller the ERP call worked.

Both are fixed. This file keeps the class closed, because the difference is invisible on
sight: a bare `except:` looks like a slightly lazier `except Exception:` and behaves like a
trap that only springs during shutdown, which is exactly when nobody is reading logs.

SCOPE. This is a zero-tolerance check, not a ratchet, and it can be: the population is
already zero in both trees. `except BaseException:` is caught by the same rule -- writing
it explicitly is at least honest, but it needs a reason, and there is currently no case
here that has one.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

# Derived, not restated. `test_no_two_guards_keep_the_same_list.py` flagged the private
# copy this file first carried against three other guards' identical ones -- see
# `tests/_source_trees.py` for why that is one fact rather than four.
from tests._source_trees import REPO_ROOT as ROOT, PACKAGE_ROOTS


def _sources() -> list[pathlib.Path]:
    return [p for tree in PACKAGE_ROOTS if tree.exists() for p in sorted(tree.rglob("*.py"))]


def _bare_handlers() -> list[str]:
    """(path:line) for every handler that catches BaseException, bare or explicit."""
    found = []
    for path in _sources():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - a file that cannot parse is a louder bug
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is None:
                found.append(f"{path.relative_to(ROOT)}:{node.lineno} (bare `except:`)")
            elif isinstance(node.type, ast.Name) and node.type.id == "BaseException":
                found.append(f"{path.relative_to(ROOT)}:{node.lineno} (`except BaseException`)")
    return found


class TestTheWalkCanSeeItsSubject:
    """A sweep that parses nothing passes for the wrong reason."""

    def test_it_reads_a_plausible_number_of_files(self):
        assert len(_sources()) > 200, (
            f"only {len(_sources())} python files found across "
            f"{[str(t) for t in PACKAGE_ROOTS]}; "
            "the walk is broken rather than the codebase being tiny"
        )

    def test_it_finds_the_ordinary_handlers_it_is_not_flagging(self):
        """The inverse check: `except Exception:` is everywhere and must NOT be counted,
        or this file is silently asserting something other than what it claims."""
        total = 0
        for path in _sources():
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            total += sum(
                1
                for n in ast.walk(tree)
                if isinstance(n, ast.ExceptHandler)
                and isinstance(n.type, ast.Name)
                and n.type.id == "Exception"
            )
        assert total > 100, (
            f"found only {total} `except Exception:` handlers, which means the AST walk is "
            "not seeing handlers at all and the real check below cannot fail"
        )

    def test_a_bare_handler_would_be_detected(self):
        """Drive the detector against a known-bad snippet, so a passing suite means the
        population is zero rather than the detector being blind."""
        tree = ast.parse("try:\n    x()\nexcept:\n    pass\n")
        handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
        assert handlers and handlers[0].type is None


class TestNothingCatchesBaseException:
    def test_no_bare_or_baseexception_handler_exists(self):
        offenders = _bare_handlers()
        assert not offenders, (
            "handlers catching BaseException found:\n  "
            + "\n  ".join(offenders)
            + "\n\n`except:` and `except BaseException:` catch asyncio.CancelledError, so a "
            "task being shut down has its cancellation swallowed and keeps running -- the "
            "process appears to hang instead of stopping. Use `except Exception:` and "
            "narrow it further if you can name what actually raises."
        )
