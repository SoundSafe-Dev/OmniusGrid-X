"""A suite that skips for want of credentials is registered, or it is invisible (FS-490).

RULE 49 IS "A SUITE THAT SKIPPED IS NOT A SUITE THAT PASSED", and this codebase has the
near-miss on record: the RLS migration guard noted that *"'25 passed' would have confirmed the
migration against tests that never ran the code it can break."*

Six suites in `tests/` carry a module-level `pytest.mark.skipif` on credentials. Between them
they are the entire vendor-facing surface — SAP, Dynamics, Dataverse, Odoo, QuickBooks — and
in the ordinary case every one of them skips. That is the correct behaviour: a fork PR has no
secrets, and a red build for a missing key nobody can provision teaches people to ignore the
colour.

WHAT IS NOT CORRECT IS THAT THE SET CAN GROW WITHOUT ANYONE NOTICING. A seventh suite added
tomorrow with the same marker joins a green run as a silent skip, and the honest reading of
"3,564 passed" quietly stops being honest. The count is the thing nobody checks, which is
exactly the shape of every hand-carried figure that has drifted in this repository — and all
of those drifted in the flattering direction.

So the register below is the claim, and this file is the check on it. Adding a
credential-gated suite means adding a line here, which is a small tax and the only moment at
which somebody decides on purpose that a suite may run nowhere.

WHAT EACH ENTRY MUST SAY. The reason has to name the environment variable that enables the
suite. "Needs credentials" in a CI log is a dead end for whoever reads it; "set
SAP_SANDBOX_API_KEY" is an instruction. That is checked rather than trusted, because a reason
is written once and read by people who were not there.

NOT IN SCOPE. `tests/rag_eval/` is a separate suite with its own `pytest.ini`, excluded from
the main run, and it gates per-test rather than per-module. It belongs to the RAG lane and is
left to it.
"""

from __future__ import annotations

import pathlib
import re

import pytest

TESTS = pathlib.Path(__file__).resolve().parent

#: Suites that may skip when their credentials are absent, and the variable that enables each.
#:
#: The value is the env var a reader should set. It is asserted to appear in the suite's own
#: skip reason, so the register and the message a person actually sees cannot drift apart.
CREDENTIAL_GATED = {
    "test_erp_sap_sandbox.py": "SAP_SANDBOX_API_KEY",
    "test_erp_intuit_sandbox.py": "INTUIT_REALM_ID",
    "test_erp_dynamics_sandbox.py": "DATAVERSE_ORG",
    "test_erp_sync_e2e_realdb.py": "DATAVERSE_ORG",
    "test_erp_platform_integration_realdb.py": "DATAVERSE_ORG",
    "test_erp_odoo_integration.py": "RUN_ODOO_INTEGRATION",
}


def _module_level_skips() -> dict[str, str]:
    """filename -> the text of its module-level ``pytestmark`` assignment."""
    found: dict[str, str] = {}
    for path in sorted(TESTS.glob("test_*.py")):
        source = path.read_text()
        match = re.search(r"^pytestmark\s*=\s*(.+?)(?=\n\S|\nclass |\ndef )", source, re.M | re.S)
        if not match:
            continue
        block = match.group(1)
        if "skipif" not in block and "skip(" not in block:
            continue
        found[path.name] = block
    return found


SKIPPING = _module_level_skips()


class TestTheReaderIsNotVacuous:
    """Two empty sets are equal, and that is the failure mode this whole file is about."""

    def test_it_finds_the_suites_that_skip(self):
        assert len(SKIPPING) >= 5, (
            f"only {sorted(SKIPPING)} parsed as module-level skips. The regex is broken, and "
            f"every comparison below would then pass over an empty set — which is the exact "
            f"'green because nothing ran' failure this file exists to prevent."
        )

    def test_it_finds_one_it_knows_about(self):
        assert "test_erp_sap_sandbox.py" in SKIPPING


class TestTheRegisterMatchesTheTree:
    def test_no_suite_skips_without_being_registered(self):
        unregistered = sorted(set(SKIPPING) - set(CREDENTIAL_GATED))
        assert not unregistered, (
            f"these suites skip themselves entirely when their credentials are absent and are "
            f"not in CREDENTIAL_GATED: {unregistered}. They will report as passing runs that "
            f"executed none of their code. Add each with the env var that enables it, or give "
            f"the suite a way to run."
        )

    def test_no_registered_suite_has_been_deleted(self):
        # A register that keeps excusing a file nobody has looked at stops describing the
        # tree and starts covering for it (Rule 110).
        ghosts = sorted(name for name in CREDENTIAL_GATED if not (TESTS / name).exists())
        assert not ghosts, f"registered here and not in the tree: {ghosts}"

    def test_every_registered_suite_still_skips_that_way(self):
        # The other direction: a suite that stopped being credential-gated should leave the
        # register, or the register overstates how much of the suite is conditional.
        no_longer = sorted(set(CREDENTIAL_GATED) - set(SKIPPING))
        assert not no_longer, (
            f"these are registered as credential-gated and no longer carry a module-level "
            f"skip: {no_longer}. If they run unconditionally now, remove them from the register."
        )


class TestEverySkipTellsYouHowToRunIt:
    @pytest.mark.parametrize("name", sorted(CREDENTIAL_GATED))
    def test_the_reason_names_the_variable(self, name: str):
        block = SKIPPING[name]
        assert "reason=" in block, (
            f"{name} skips with no reason, so `pytest -rs` prints the file and nothing else — "
            f"a reader learns that something did not run and no way to change that"
        )
        variable = CREDENTIAL_GATED[name]
        assert variable in block, (
            f"{name}'s skip reason does not mention {variable}, which the register says "
            f"enables it. A CI log saying 'needs credentials' is a dead end; one saying "
            f"'set {variable}' is an instruction. Either the reason or the register is wrong."
        )
