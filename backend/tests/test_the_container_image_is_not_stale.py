"""A bind-mounted source tree outlives the image's site-packages (FS-446).

`docker-compose.yml` mounts `./backend:/app` over the backend image. That is the right call
for development — edit a file, the server reloads — but it splits the container in two:

    the CODE comes from the working tree, and is always current
    the PACKAGES come from the image, and are as old as the last build

So the moment a dependency changes, every container built before it runs **new code against
old packages**. Today that presents as:

    File "/app/app/api/auth.py", line 10, in <module>
        import jwt
    ModuleNotFoundError: No module named 'jwt'

eight frames deep in a crashloop, on an image two months old, three weeks after `PyJWT`
replaced `python-jose` (FS-76). Nothing in that stack trace says "your image predates a
dependency change; rebuild it", which is the only useful thing to know.

THIS FILE DOES NOT TEST THE CONTAINER. It cannot — the suite runs on the host, and a guard
that only fires where Docker is available is a guard that does not fire. What it tests is the
thing that made the failure unreadable: **that the app refuses to start with a message naming
the cause**, rather than dying on whichever import happens to come first.

The check itself lives in `app/core/startup_checks.py` and runs from the lifespan, so it
fires in the container, in CI, and on a laptop whose venv is behind `requirements.txt` —
which is the same failure wearing different clothes.
"""

from __future__ import annotations

import pytest

from app.core.startup_checks import (
    MissingDependencies,
    _requirement_names,
    verify_installed_dependencies,
)


class TestTheRequirementsAreReadable:
    def test_it_parses_the_real_file(self):
        names = _requirement_names()
        assert len(names) > 30, (
            f"only {len(names)} requirements parsed; the parser is broken and this check "
            f"would pass over an empty set — the shape every sweep here has a rule about"
        )

    @pytest.mark.parametrize(
        "line,expected",
        [
            ("PyJWT[crypto]==2.10.1", "pyjwt"),
            ("fastapi>=0.100", "fastapi"),
            ("uvicorn[standard]==0.30.0  # comment", "uvicorn"),
            ("SQLAlchemy == 2.0.0", "sqlalchemy"),
            ("python-dotenv~=1.0", "python-dotenv"),
        ],
    )
    def test_it_reads_a_pinned_extra_or_commented_line(self, line, expected):
        assert _requirement_names([line]) == {expected}

    @pytest.mark.parametrize(
        "line", ["", "   ", "# just a comment", "-r other.txt", "--index-url https://x"]
    )
    def test_it_ignores_what_is_not_a_requirement(self, line):
        assert _requirement_names([line]) == set()

    def test_it_knows_pyjwt_is_required(self):
        """The dependency whose absence started this. If the name stops being read, the
        check would pass on the exact container that is broken today."""
        assert "pyjwt" in _requirement_names()


class TestTheCheckSaysWhatIsWrong:
    def test_a_satisfied_environment_passes_quietly(self):
        verify_installed_dependencies()  # this venv is current; must not raise

    def test_a_missing_package_names_itself_and_the_remedy(self):
        with pytest.raises(MissingDependencies) as excinfo:
            verify_installed_dependencies(required={"pyjwt", "definitely-not-installed"})

        message = str(excinfo.value)
        assert "definitely-not-installed" in message, "the missing package is not named"
        assert "pyjwt" not in message, "an INSTALLED package was reported as missing"
        assert "rebuild" in message.lower(), (
            "the message does not say what to do. `ModuleNotFoundError: No module named "
            "'jwt'` was already available and told nobody anything; the value here is "
            "entirely in naming the remedy"
        )

    def test_it_mentions_the_bind_mount_because_that_is_the_cause(self):
        with pytest.raises(MissingDependencies) as excinfo:
            verify_installed_dependencies(required={"definitely-not-installed"})
        assert "requirements.txt" in str(excinfo.value)

    def test_it_lists_every_missing_package_not_just_the_first(self):
        """A developer who rebuilds for one package and hits the next has learned nothing
        about the actual gap."""
        with pytest.raises(MissingDependencies) as excinfo:
            verify_installed_dependencies(required={"not-a-package-one", "not-a-package-two"})
        message = str(excinfo.value)
        assert "not-a-package-one" in message and "not-a-package-two" in message


class TestItIsWiredIntoStartup:
    def test_the_lifespan_calls_it(self):
        """A check nothing calls is a check that does not run — and this one exists
        precisely because a crashloop said nothing useful."""
        import inspect

        import app.main as main

        source = inspect.getsource(main)
        assert "verify_installed_dependencies" in source, (
            "app.main no longer calls the dependency check, so a stale image goes back to "
            "failing eight frames deep in whichever import comes first"
        )
