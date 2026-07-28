"""No SQL literal may be built by interpolating a value into quotes.

THE SIGNATURE. `text(f"... WHERE id = '{asset_id}'")` is a quoted literal assembled by
string formatting. A single apostrophe in the value breaks the statement; a crafted one
rewrites it. This codebase has already paid for that once — see
`tactical_engine._is_maintenance_mode`, whose comment records that
`' OR '1'='1` used to match every row.

WHY THE CHECK IS THIS SHAPE AND NOT "no f-string in SQL". Sixteen `text(f"...")` calls in
`app/` are entirely correct, because identifiers and intervals CANNOT be bound and must be
interpolated:

    f"SELECT {_HISTORIAN_POLICY_COLUMNS} FROM ..."   a module constant
    f"... ORDER BY {sort_col} {order_sql}"           both from dict lookups
    f"INTERVAL '{seconds} seconds'"                  an int from AGGREGATION_SECONDS
    f"FROM {view_name} AS rollup"                    three hardcoded call sites

Banning f-strings outright would flag all of them, and a guard with sixteen false
positives is one nobody reads. Interpolating INSIDE QUOTES is different: quotes mean the
value is data, and data can be bound. That distinction is what makes this check precise
enough to enforce.

WHAT IT FOUND. Eight sites, all now using bound parameters:

  * `device_provisioning` (5) — an INSERT interpolating `certificate_pem` and
    `json.dumps(metadata)` as quoted literals, plus approve/revoke/lookup. That module is
    referenced by nothing AND cannot be imported (`settings.CA_KEY_PATH` does not exist;
    the setting is `EDGE_CA_KEY_PATH`), which is why it was never reachable.
  * `feature_extraction` (3) — `asset_id` and timestamps in the telemetry and PackML
    queries. `asset_id` arrives from edge telemetry, which is the same untrusted source
    the tactical-engine fix was about.
"""

from __future__ import annotations

import ast
import pathlib
import re
from typing import List, Tuple

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: A value interpolated between single quotes: the data-as-literal signature.
QUOTED_INTERPOLATION = re.compile(r"'\{[^}]+\}'")


def _sql_calls_with_quoted_interpolation() -> List[Tuple[str, int, str]]:
    found: List[Tuple[str, int, str]] = []
    for path in sorted(APP.glob("**/*.py")):
        source = path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:  # another test's problem
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name != "text" or not node.args:
                continue
            arg = node.args[0]
            if not isinstance(arg, ast.JoinedStr):
                continue
            segment = "\n".join(lines[arg.lineno - 1 : (arg.end_lineno or arg.lineno)])
            for match in QUOTED_INTERPOLATION.findall(segment):
                found.append((str(path.relative_to(APP)), node.lineno, match))
    return found


class TestTheDetectorIsPrecise:
    def test_it_flags_a_value_interpolated_into_quotes(self):
        assert QUOTED_INTERPOLATION.findall("WHERE id = '{asset_id}'") == ["'{asset_id}'"]

    def test_it_ignores_an_interpolated_identifier(self):
        """Column and table names cannot be bound; they are interpolated on purpose and
        drawn from constants or dict lookups."""
        assert not QUOTED_INTERPOLATION.findall("SELECT {columns} FROM {view_name}")
        assert not QUOTED_INTERPOLATION.findall("ORDER BY {sort_col} {order_sql}")

    def test_it_ignores_a_bound_parameter(self):
        assert not QUOTED_INTERPOLATION.findall("WHERE id = :asset_id")


class TestTheSweepIsNotVacuous:
    def test_it_reaches_the_sql_in_the_codebase(self):
        """There must be `text(f"...")` calls to examine, or a clean result means only
        that the walk found nothing."""
        interpolated = 0
        for path in APP.glob("**/*.py"):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and getattr(node.func, "id", getattr(node.func, "attr", None)) == "text"
                    and node.args
                    and isinstance(node.args[0], ast.JoinedStr)
                ):
                    interpolated += 1
        assert interpolated >= 5, (
            f"only {interpolated} f-string SQL calls found; the walk is not reaching app/"
        )


class TestNoValueIsInterpolatedIntoQuotes:
    def test_no_quoted_interpolation_remains(self):
        offenders = _sql_calls_with_quoted_interpolation()
        assert not offenders, (
            "SQL is being built by formatting a value into quotes. An apostrophe in the "
            "value breaks the statement and a crafted one rewrites it — bind it with "
            ":name instead:\n  "
            + "\n  ".join(f"app/{path}:{line}  {frag}" for path, line, frag in offenders)
        )
