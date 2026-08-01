"""The documented skip-login demo must actually skip the login (FS-388).

THE DEFECT. `make demo` printed, and `docs/DEMO.md` repeated:

    cd frontend && VITE_USE_MOCK=false npm run dev   (login: dev / any password)

Typing `dev` there does not log you in. It falls through to the real login form and
returns **401**, verified against a running stack on 2026-08-01. The bypass has TWO gates
and the instructions named one:

    ALLOW_DEV_TOKEN=true   (backend)   accepts the `dev-token` bearer
    VITE_DEV_MODE=true     (frontend)  offers the bypass at all — Login.tsx requires
                                       `import.meta.env.DEV && VITE_DEV_MODE === 'true'`

DEMO.md even explained the login as "the backend accepts the `dev-token` bypass when
ALLOW_DEV_TOKEN=true", which is true and is not the half that was missing.

WHY IT DRIFTED, and why a test rather than a careful edit. The frontend gate was TIGHTENED
at some point — the `VITE_DEV_MODE` requirement is deliberate and well-tested in
`Login.test.tsx`, which asserts a production bundle cannot enable it. That change was
correct. What nothing connected it to was the two places that tell a human how to start
the demo, so the security improvement quietly broke the demo and neither side could tell:
the frontend test passes, the backend test passes, and the path between them is prose.

WHAT THIS PINS. That the instructions contain what the code requires. It cannot run vite,
so it does not prove the demo works end to end — it proves the two documents and the code
agree on which variables are needed, which is the specific thing that broke.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MAKEFILE = REPO / "Makefile"
DEMO_DOC = REPO / "docs" / "DEMO.md"
LOGIN_TSX = REPO / "frontend" / "src" / "pages" / "auth" / "Login.tsx"

#: Both halves of the bypass. Named here so a rename on either side fails loudly rather
#: than leaving the instructions pointing at a variable nothing reads.
BACKEND_GATE = "ALLOW_DEV_TOKEN"
FRONTEND_GATE = "VITE_DEV_MODE"


def _read(path: Path) -> str:
    assert path.exists(), f"{path} is missing; this guard checks nothing"
    return path.read_text()


class TestTheCodeStillGatesItThisWay:
    """Read the requirement off the source, so this file cannot enforce a stale answer.

    If `Login.tsx` stops gating on VITE_DEV_MODE, the assertions below are enforcing a
    variable nobody reads — which is the same failure in the other direction.
    """

    def test_login_requires_the_frontend_gate(self):
        source = _read(LOGIN_TSX)
        assert FRONTEND_GATE in source, (
            f"Login.tsx no longer mentions {FRONTEND_GATE}. Either the gate was renamed "
            "(update this file and both sets of instructions) or the bypass is now "
            "ungated, which is worse."
        )

    def test_the_frontend_gate_is_also_dev_build_only(self):
        """The other half of why this is safe: a production bundle compiles it out."""
        source = _read(LOGIN_TSX)
        assert re.search(r"import\.meta\.env\.DEV\s*&&", source), (
            "the dev-login bypass is no longer restricted to a dev build; "
            "VITE_DEV_MODE alone would let a production bundle enable it"
        )


class TestTheMakefileStartsAWorkingDemo:
    def test_the_backend_target_sets_the_backend_gate(self):
        makefile = _read(MAKEFILE)
        demo = re.search(r"^demo:.*?(?=^\S|\Z)", makefile, re.M | re.S)
        assert demo, "no `demo:` target in the Makefile"
        assert f"{BACKEND_GATE}=true" in demo.group(0), (
            f"`make demo` does not set {BACKEND_GATE}=true, so every API call the demo "
            "makes returns 401"
        )

    def test_a_ui_target_exists_and_sets_the_frontend_gate(self):
        """THE ASSERTION THIS FILE EXISTS FOR."""
        makefile = _read(MAKEFILE)
        target = re.search(r"^demo-ui:.*?(?=^\S|\Z)", makefile, re.M | re.S)
        assert target, (
            "no `demo-ui:` target. The frontend half of the demo was a line of prose to "
            "copy, and it drifted from what Login.tsx requires — putting it in a target "
            "is what stops that recurring."
        )
        assert f"{FRONTEND_GATE}=true" in target.group(0), (
            f"`make demo-ui` does not set {FRONTEND_GATE}=true. Typing `dev` at the login "
            "form will fall through to real authentication and return 401."
        )
        assert "VITE_USE_MOCK=false" in target.group(0), (
            "`make demo-ui` does not disable the mock layer, so the demo would show "
            "fixtures rather than the seeded data the whole point is to exercise"
        )

    def test_the_demo_target_points_at_the_ui_target(self):
        """`make demo` prints the next step; it must name the target, not a command that
        can go stale independently."""
        makefile = _read(MAKEFILE)
        demo = re.search(r"^demo:.*?(?=^\S|\Z)", makefile, re.M | re.S).group(0)
        assert "demo-ui" in demo, (
            "`make demo` still prints a raw frontend command instead of pointing at "
            "`make demo-ui` — the two can drift apart again"
        )


class TestTheWalkthroughAgreesWithTheMakefile:
    def test_demo_doc_names_both_gates(self):
        doc = _read(DEMO_DOC)
        for gate in (BACKEND_GATE, FRONTEND_GATE):
            assert gate in doc, (
                f"docs/DEMO.md does not mention {gate}. It previously explained the "
                f"skip-login entirely in terms of {BACKEND_GATE}, which is true and is "
                "not the half that was missing."
            )

    def test_no_frontend_dev_command_omits_the_gate(self):
        """Every `npm run dev` line in the walkthrough must carry the frontend gate.

        Checked per-line rather than per-document: a doc that mentions VITE_DEV_MODE in a
        paragraph while still printing a copyable command without it is exactly as broken
        as before, and a document-wide substring check would pass it.
        """
        offenders = [
            line.strip()
            for line in _read(DEMO_DOC).splitlines()
            if "npm run dev" in line and FRONTEND_GATE not in line
        ]
        assert not offenders, (
            "these commands start the demo UI without the frontend gate, so `dev` / any "
            f"password returns 401:\n  " + "\n  ".join(offenders)
        )


class TestTheSeededOrgMatches:
    def test_the_dev_login_org_is_the_seeded_one(self):
        """The bypass mints a user client-side, so its organizationId is a literal. If it
        stops matching the seeder's org, login succeeds and every org-scoped page is
        empty — a demo that looks broken rather than one that fails."""
        login = _read(LOGIN_TSX)
        seeder = _read(REPO / "backend" / "scripts" / "seed_demo_data.py")
        org = re.search(r"organizationId:\s*'([0-9a-f-]{36})'", login)
        assert org, "Login.tsx no longer pins an organizationId for the dev user"
        assert org.group(1) in seeder, (
            f"the dev-login organizationId {org.group(1)} does not appear in "
            "seed_demo_data.py; every org-scoped page would render empty"
        )
