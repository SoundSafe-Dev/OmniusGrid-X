"""A KPI range label says the window the endpoint actually computes (FS-486).

THE DEFECT. `PerformancePanel`'s selector offered "Today / This Week / This Month / This
Quarter / This Year" — calendar periods. `app/api/kpi.py` computes:

    _RANGE_DAYS = {"today": 1, "week": 7, "month": 30, "quarter": 90, "year": 365, ...}
    since = datetime.now(timezone.utc) - timedelta(days=_RANGE_DAYS.get(time_range, 30))

which is a ROLLING WINDOW. On the 6th of August, "This Month" is the 7th of July to the 6th
of August, and most of what it reports happened in a month the label does not name. Fuel
efficiency, idle time, on-time performance and cost per mile all hang off it.

The number was right and the label was wrong, which is the harder direction to notice: there
is nothing on the screen that looks incorrect, and a figure attributed to the wrong period is
still a figure somebody compares against last period's.

Every other range selector in the application — Historian, ErrorTriage, AnalyticsPages —
already reads "Last N days". This one was the exception, so the fix was to make it agree with
both the computation and the rest of the product rather than to change what is computed.

WHAT THIS GUARDS. That each option's label states the same number of days `_RANGE_DAYS`
assigns to its value. It deliberately does not check wording beyond the number: "Last 30
days" and "Last 30 days (rolling)" are both honest, and a guard that pinned the prose would
be a guard people route around.

`custom` is not offered by the selector and is not required to be: it maps to 30 days, so
offering it would present a month under a name that promises a choice.
"""

from __future__ import annotations

import pathlib
import re

from app.api.kpi import _RANGE_DAYS

REPO = pathlib.Path(__file__).resolve().parents[2]
PANEL = REPO / "frontend" / "src" / "components" / "fleet" / "PerformancePanel.tsx"

#: `today` is one day, and "Last 24 hours" is the honest way to say one rolling day — a
#: label reading "Last 1 days" would be worse English for the same window.
EQUIVALENT_DAYS = {24: 1}


def _selector_options() -> list[tuple[str, str]]:
    """(value, label) for every option in the panel's range selector."""
    source = PANEL.read_text()
    block = re.search(r"const TimeRangeSelector[\s\S]*?</select>", source)
    assert block, "the TimeRangeSelector could not be found in PerformancePanel.tsx"
    return re.findall(r'<option value="(\w+)">([^<]+)</option>', block.group(0))


class TestTheReaderIsNotVacuous:
    def test_it_finds_the_options(self):
        options = _selector_options()
        assert len(options) >= 4, f"only {options} parsed; the reader is broken and the "
        assert dict(options).keys() <= _RANGE_DAYS.keys()

    def test_the_backend_table_is_populated(self):
        assert len(_RANGE_DAYS) >= 5


class TestEveryLabelNamesItsOwnWindow:
    def test_each_label_states_the_days_the_endpoint_uses(self):
        wrong = []
        for value, label in _selector_options():
            expected = _RANGE_DAYS[value]
            numbers = [int(n) for n in re.findall(r"\d+", label)]
            stated = [EQUIVALENT_DAYS.get(n, n) for n in numbers]
            if expected not in stated:
                wrong.append(f"{value!r} is a {expected}-day window and is labelled {label!r}")
        assert not wrong, (
            "these KPI range labels do not name the window the endpoint computes, so a "
            "figure is attributed to a period it was not measured over: " + "; ".join(wrong)
        )

    def test_no_label_claims_a_calendar_period(self):
        # The specific wording that was wrong. `_range_start` subtracts days from `now`, so
        # nothing here is ever a calendar month, quarter or year.
        calendar = [
            f"{value!r} reads {label!r}"
            for value, label in _selector_options()
            if re.search(r"\bthis\b", label, re.I)
        ]
        assert not calendar, (
            "a rolling window labelled as a calendar period — the endpoint subtracts days "
            "from now, so 'This Month' on the 6th is mostly the previous month: "
            + "; ".join(calendar)
        )
