"""The receiving half of the clock-quality flag (FS-760, DDIL S8).

The edge agent now corrects telemetry timestamps by its measured clock offset and says what
that correction is worth — `synced`, `holdover` or `unsynced`. None of that is any use unless
this side stores it: a flag that is computed, transmitted and dropped on arrival is the same
defect as the one being fixed, one hop later.

**Written before the mutation pass, deliberately.** Rule 264 came out of the previous item,
where fifteen mutations against a two-deployable feature caught every defect on the side I
was standing on and missed six in a row on the far side. The agent is the far side this time,
and the backend the near one, so both halves get assertions before anything is claimed.

`unknown` is the fourth value and the important one. Every agent predating this release omits
the field — which is the entire fleet on the day it ships — and labelling their rows
`unsynced` would assert something about clocks nobody measured.
"""

from __future__ import annotations

import pathlib

import pytest

from app.db.models import Telemetry
from app.workers.ingestion import TIME_QUALITIES, _time_quality_of

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "database" / "migrations" / "071_telemetry_carries_its_time_quality.sql"
)


class TestWhatTheAgentClaims:
    @pytest.mark.parametrize("claimed", sorted(TIME_QUALITIES))
    def test_every_recognised_quality_is_kept(self, claimed):
        assert _time_quality_of({"time_quality": claimed}) == claimed

    def test_an_agent_that_says_nothing_is_recorded_as_unknown(self):
        assert _time_quality_of({"asset_id": "press-01"}) == "unknown", (
            "an agent predating this field had its rows labelled with a clock state nobody "
            "measured. `unknown` is the only true statement about them."
        )

    def test_unknown_is_not_the_same_as_unsynced(self):
        """They mean different things and the difference is the whole point. `unsynced` is
        an agent reporting it has never reached a clock — a measured fact about an
        air-gapped device. `unknown` is this backend saying nobody told it."""
        assert _time_quality_of({}) == "unknown"
        assert _time_quality_of({"time_quality": "unsynced"}) == "unsynced"

    @pytest.mark.parametrize("junk", ["SYNCED", "excellent", "", 42, None, ["synced"]])
    def test_an_unrecognised_claim_is_not_stored_verbatim(self, junk):
        """A future agent inventing a label, or a malformed message, must not put an
        unrecognised value into a column an assessor filters on."""
        assert _time_quality_of({"time_quality": junk}) == "unknown"

    def test_the_vocabulary_is_the_four_states_and_no_more(self):
        assert TIME_QUALITIES == {"synced", "holdover", "unsynced", "unknown"}


class TestTheColumnExists:
    def test_the_model_declares_it(self):
        column = Telemetry.__table__.columns.get("time_quality")
        assert column is not None, (
            "the flag is transmitted and dropped on arrival, which is the original defect "
            "one hop later"
        )
        assert column.nullable is False
        assert "unknown" in str(column.server_default.arg)

    def test_it_carries_a_python_side_default_as_well(self):
        """Not redundant with `server_default`, and the reason is worth pinning.

        With the server default alone, SQLAlchemy must learn the value the database chose,
        so it switches this table's bulk insert to a RETURNING form and matches rows back by
        sentinel. That fails here: the primary key is `(time, asset_id, metric_name)` and a
        DateTime does not round-trip through the DBAPI identically, so the offline demo
        seeder died with "Can't match sentinel values in result set to parameter sets". A
        Python-side default puts the value in the INSERT and nothing needs fetching back.
        """
        column = Telemetry.__table__.columns.get("time_quality")
        assert column.default is not None, (
            "no Python-side default, so every bulk insert into telemetry goes through "
            "RETURNING and sentinel matching — which this composite primary key cannot "
            "satisfy"
        )
        assert column.default.arg == "unknown"

    def test_the_migration_exists_and_defaults_to_unknown(self):
        assert MIGRATION.exists(), f"missing migration: {MIGRATION.name}"
        sql = MIGRATION.read_text()
        assert "ADD COLUMN IF NOT EXISTS time_quality" in sql
        assert "DEFAULT 'unknown'" in sql, (
            "existing rows are being backfilled to something other than `unknown`, which "
            "asserts a clock state for readings nobody measured"
        )

    def test_the_migration_indexes_the_question_worth_asking(self):
        """The useful query is "which readings cannot be trusted for ordering", not "which
        can" — on a healthy fleet almost every row is `synced`, so a full index would be
        large and answer the boring question."""
        sql = MIGRATION.read_text()
        assert "idx_telemetry_degraded_time" in sql
        assert "WHERE time_quality <> 'synced'" in sql


class TestTheIngestionPathActuallySetsIt:
    def test_every_telemetry_insert_passes_the_quality_through(self):
        """By AST, not by slicing the source.

        The first version cut the text at the first `)` after `Telemetry(`, which lands
        inside `self._infer_unit(metric_name)` — so it examined half the call and reported a
        missing keyword that was three lines further down. Parentheses nest; a string slice
        does not know that. It also finds EVERY construction site rather than the first,
        which is the assertion actually wanted: a column that exists and is never written is
        the same silence with extra schema.
        """
        import ast

        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "app" / "workers" / "ingestion.py").read_text()
        tree = ast.parse(source)

        sites = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Telemetry"
        ]
        assert sites, "no Telemetry(...) construction found; this test sees nothing"

        for site in sites:
            keywords = {kw.arg for kw in site.keywords}
            assert "time_quality" in keywords, (
                f"the Telemetry construction at line {site.lineno} does not set "
                f"time_quality, so those rows silently default to 'unknown' while the "
                f"agent is telling us what their clock was worth"
            )
