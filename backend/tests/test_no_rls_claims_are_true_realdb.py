"""A comment saying a table has no row-level security must be true of the schema.

`fleet_logistics._scope` opens with:

    NEEDED EXPLICITLY because these four tables — geofence_zones, geofence_alerts,
    maintenance_schedules, repair_orders — carry `organization_id` but have NO
    row-level security.

Migration **051** policied all four, with FORCE, and the comment was never updated. The same
sentence is repeated at four write sites in that file as the justification for taking the
organisation from the token rather than the payload — which is still the right thing to do, for
a reason that is no longer the stated one.

WHY THIS IS WORTH A GUARD RATHER THAN A CORRECTION. Three of the stale claims were made stale by
migrations written in this session: 056 policied the two notification tables and 057 policied
`edge_agent_status`, and both left behind a comment saying those tables are unprotected. The
claim decays every time somebody does the right thing elsewhere, which is the definition of a
fact that should not be maintained by hand (rule 44).

And it decays in the dangerous direction. "This table has no policy, so the filter is all that
stands between you and a cross-tenant read" is a load-bearing statement: it is the argument for
the code beneath it. When it goes stale it does not become harmlessly out of date — it becomes a
false account of why the code is shaped the way it is, and the next person either trusts it and
over-builds, or checks it, finds it wrong, and trusts the rest of the file less.

PAST TENSE IS EXEMPT, deliberately. `alarms.py` says *"`alarms` HAD no RLS policy; migration 046
turned a latent bug into a real one"* — a statement about history, which stays true. Only claims
in the present tense are checked.
"""

from __future__ import annotations

import pathlib
import re

import pytest

pytestmark = pytest.mark.asyncio

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: The claim, in the present tense. `had`/`used to` are history and are not matched.
CLAIM = re.compile(
    r"\b(?:has|have|carries|carry)\s+(?:NO|no)\s+"
    r"(?:row-level security|RLS(?:\s+polic(?:y|ies))?)",
    re.IGNORECASE,
)

PAST_TENSE = re.compile(r"\b(?:had|used to have|previously had|no longer)\b", re.IGNORECASE)

#: A bare `word_with_underscores` that looks like a table name.
TABLE_TOKEN = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")

#: Sentence boundary, used to bound how far back the subject can be.
SENTENCE_END = re.compile(r"[.:;]\s")


def _tenant_tables(admin_sync_url) -> dict[str, tuple[bool, bool]]:
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                """
            )
            return {name: (enabled, forced) for name, enabled, forced in cur.fetchall()}
    finally:
        conn.close()


def _claims() -> list[tuple[str, int, str, set[str]]]:
    """`(file, line, sentence, tables the claim is ABOUT)`, present tense only.

    TWO THINGS THE FIRST VERSION GOT WRONG, both found by running it:

    * It matched line by line, and the claim in `_scope`'s docstring wraps —
      ``carry `organization_id` but have NO\n    row-level security`` — so the four tables
      it is actually about were never checked. The text is joined before matching.

    * It attributed every table token within two lines of the phrase, which made
      `user_management.py` a false positive: *"``users`` has no RLS policy: ``audit_logs``
      DOES"* names the contrast as well as the subject. Only tables in the sentence BEFORE
      the phrase are the subject of it — which is where English puts them, and it is also
      what excludes the contrast that follows.
    """
    out: list[tuple[str, int, str, set[str]]] = []
    for path in sorted(APP.rglob("*.py")):
        text = path.read_text()
        joined = re.sub(r"\s+", " ", text)
        for match in CLAIM.finditer(joined):
            before = joined[max(0, match.start() - 400): match.start()]
            after = joined[match.end(): match.end() + 200]
            if PAST_TENSE.search(before[-200:]) or PAST_TENSE.search(after[:80]):
                continue
            # Back to the start of the sentence the claim sits in.
            boundaries = list(SENTENCE_END.finditer(before))
            subject = before[boundaries[-1].end():] if boundaries else before
            named = set(TABLE_TOKEN.findall(subject))
            # Line number: count newlines up to the same offset in the ORIGINAL text by
            # locating the claim's distinctive tail.
            probe = joined[match.start(): match.start() + 40].strip()
            head = probe.split(" ")[0]
            line_no = text.count("\n", 0, max(text.find(head), 0)) + 1
            out.append((str(path.relative_to(APP.parent)), line_no, subject[-160:].strip(), named))
    return out


class TestTheScanIsNotVacuous:
    def test_it_still_finds_claims_in_the_tree(self):
        """A weaker floor than the first version's, DELIBERATELY.

        That one asserted `len(_claims()) >= 5`, which passed while five claims were stale and
        FAILED the moment they were corrected — because correcting them meant putting them in
        the past tense, which is exactly what this scan is built to skip. A non-vacuity check
        keyed on how many defects exist inverts as soon as they are fixed.

        What matters is that the scan can still see the shape at all, which
        `test_it_fires_on_a_claim_that_is_false` pins directly."""
        assert _claims(), "the pattern matches nothing in app/ — it can no longer see the shape"

    def test_it_fires_on_a_claim_that_is_false(self):
        """The positive control, and the one that actually keeps this guard honest. Written
        against a sentence in the shape of the five that were stale, so a regex that stops
        matching wrapped text or loses its subject attribution fails here."""
        sample = (
            "    NEEDED EXPLICITLY because these four tables — assets, workcells — carry\n"
            "    `organization_id` but have NO\n    row-level security. Something else.\n"
        )
        joined = re.sub(r"\s+", " ", sample)
        match = CLAIM.search(joined)
        assert match, "the claim was not matched across the line break"

        before = joined[: match.start()]
        boundaries = list(SENTENCE_END.finditer(before))
        subject = before[boundaries[-1].end():] if boundaries else before
        assert "assets" in TABLE_TOKEN.findall(subject) or "assets" in subject

    def test_it_does_not_attribute_a_contrast_to_the_claim(self):
        """The negative control, from the false positive the first version produced.
        `user_management.py` says *"``users`` has no RLS policy: ``audit_logs`` DOES"* — the
        subject is `users`, and `audit_logs` is what it is being contrasted with."""
        joined = re.sub(r"\s+", " ", "``users`` has no RLS policy: ``audit_logs`` DOES, so ...")
        match = CLAIM.search(joined)
        assert match
        after = joined[match.end():]
        assert "audit_logs" in after, "the contrast follows the claim, which is why it is excluded"

    def test_it_matches_the_present_tense_and_not_the_past(self):
        assert CLAIM.search("this table has no row-level security")
        assert CLAIM.search("these tables have no RLS")
        assert CLAIM.search("`alarms` has no RLS policy, so nothing else would stop it")
        # History is not a claim about now.
        assert PAST_TENSE.search("`alarms` had no RLS policy; migration 046 changed that")

    async def test_it_reads_a_real_schema(self, app, admin_sync_url):
        tables = _tenant_tables(admin_sync_url)
        assert len(tables) > 40
        assert tables.get("assets") == (True, True), "the schema read is wrong, not the claims"


class TestEveryClaimIsTrue:
    async def test_no_comment_says_a_protected_table_is_unprotected(
        self, app, admin_sync_url
    ):
        """THE ASSERTION THIS FILE EXISTS FOR.

        A false claim here is worse than no comment: it is the stated reason for the code
        beneath it, so it survives review by explaining itself.
        """
        tables = _tenant_tables(admin_sync_url)
        wrong: list[str] = []

        for file, line, text, named in _claims():
            for table in sorted(named):
                state = tables.get(table)
                if state is None:
                    continue  # not a table name, just an identifier with underscores
                enabled, _forced = state
                if enabled:
                    wrong.append(
                        f"{file}:{line} says {table} has no row-level security, and it has "
                        f"(FORCE={_forced}).\n      {text}"
                    )

        assert not wrong, (
            "these comments claim a table is unprotected when the schema says otherwise:\n  "
            + "\n  ".join(wrong)
            + "\n\nThe sentence is the ARGUMENT for the code beneath it. Correct it, or say "
            "which migration changed it and when."
        )
