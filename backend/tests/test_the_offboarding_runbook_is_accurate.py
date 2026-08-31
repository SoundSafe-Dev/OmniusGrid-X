"""The offboarding runbook's load-bearing claim stays true (03.09.02).

`docs/runbooks/engineer-offboarding.md` tells a responder that a departing engineer's API
keys grant nothing, because **no request path authenticates with one**. That was verified
on 2026-08-31: `/api/v1/api-keys` mints, lists and revokes keys, `APIKey` appears only in
its own CRUD module and in `models.py`, and nothing consumes it.

It is a true statement about today and a dangerous one to leave unattended. The moment
somebody wires API-key authentication — a perfectly reasonable thing to build — a
departing engineer's key becomes live credentials that survive deactivating their user
account, and the runbook will still be telling the responder not to worry about it.

A runbook is read once, under pressure, by somebody who has no way to check whether its
claims aged. So the claim is asserted here instead: this fails when the feature is wired,
and the fix is to rewrite that row and move key revocation onto the critical path.

The same shape as rule 279 — an unexercised document that reads as operational — applied
to a single sentence rather than a whole file.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
APP = REPO / "backend/app"
RUNBOOK = REPO / "docs/runbooks/engineer-offboarding.md"

#: Modules allowed to mention the APIKey model. Anything else referencing it is a
#: candidate consumer, which is the thing this file watches for.
KEY_CRUD = {"api/api_keys.py", "db/models.py"}


def _modules_referencing_the_key_model() -> set[str]:
    found = set()
    for path in sorted(APP.rglob("*.py")):
        if "APIKey" in path.read_text():
            found.add(str(path.relative_to(APP)))
    return found


class TestTheClaimHolds:
    def test_nothing_outside_the_crud_module_reads_the_key_model(self):
        """The runbook says no request path accepts an API key. If one does now, that
        sentence is actively misleading a responder during an offboarding."""
        unexpected = sorted(_modules_referencing_the_key_model() - KEY_CRUD)
        assert not unexpected, (
            f"{unexpected} now reference the APIKey model. If any of them AUTHENTICATES "
            f"with it, `docs/runbooks/engineer-offboarding.md` is wrong where it says a "
            f"departing engineer's keys grant nothing — and those keys outlive "
            f"deactivating the user account, so key revocation belongs on the critical "
            f"path rather than in a footnote. Update the runbook, then this register."
        )

    def test_the_walk_is_not_vacuous(self):
        """If the sweep finds nothing at all, the model was renamed or the walk broke, and
        the check above passes while proving nothing."""
        assert _modules_referencing_the_key_model(), (
            "no module mentions APIKey, not even its own CRUD router. The sweep is broken "
            "rather than the codebase transformed."
        )


class TestTheRunbookStillSaysIt:
    def test_the_api_key_row_is_present(self):
        """A guard on a claim the document no longer makes is a guard on nothing."""
        text = RUNBOOK.read_text()
        assert "nothing accepts them" in text, (
            "the offboarding runbook no longer carries the API-key constraint this file "
            "exists to keep true. Either the claim changed — in which case update this "
            "test — or it was dropped, in which case a responder has lost the reason they "
            "were told not to chase key revocation."
        )

    def test_it_names_both_remotes(self):
        """The single most forgettable step. Access removed from one remote is access
        retained on the other, and `backup` is where several developers' only work lives."""
        text = RUNBOOK.read_text()
        for remote in ("SoundSafe-ai", "SoundSafe-Dev"):
            assert remote in text, (
                f"the runbook does not name {remote}. It names two organisations on "
                f"purpose: revoking access on one and not the other is the failure mode."
            )

    def test_it_names_the_refresh_token_window(self):
        """Deactivating the account and walking away leaves a week-long window."""
        assert re.search(r"7[\s-]day", RUNBOOK.read_text()), (
            "the runbook no longer states the refresh-token lifetime. Without it a "
            "responder reasonably believes deactivation ends the session immediately; it "
            "ends the ACCESS token immediately and leaves the refresh token live."
        )
