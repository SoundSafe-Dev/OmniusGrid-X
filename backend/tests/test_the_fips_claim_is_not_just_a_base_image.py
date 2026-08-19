"""A FIPS-capable image is not a FIPS-enforcing runtime (FS-761).

Two things are being held here and they are different claims.

**The base images must be FIPS-CAPABLE.** Debian's OpenSSL has no FIPS 140-3 validated
module and no path to one; Alpine links musl and has no validated OpenSSL at all. No amount
of configuration gets either to a validated boundary, so the base image is the one FIPS
delta that could not be closed in application code.

**And that is not sufficient**, which is the more important half. A freshly pulled
`ubi9/python-311` reports providers `default`, no kernel flag, and MD5 available — measured,
not assumed. The container inherits the host kernel's FIPS state, so the identical image is
enforcing on a node booted with `fips=1` and permissive on the node beside it, with nothing
in any manifest to distinguish them. An assessor asking "how do you know this process is
using validated cryptography?" is not answered by a `FROM` line.

So `REQUIRE_FIPS_MODE` probes BEHAVIOUR at startup — does this process refuse MD5 for a
security purpose — and fails closed when it cannot prove it.
"""

from __future__ import annotations

import pathlib
import re
from unittest.mock import patch

import pytest

from app.core.config import Settings, validate_settings
from app.core.fips import (
    FIPSModeNotActive,
    assert_fips_mode,
    crypto_is_enforcing,
    fips_status,
    kernel_fips_enabled,
)

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Every image that runs application code, and what it must be based on.
#:
#: `frontend/Dockerfile` (the DEV image) is absent deliberately: it is the hot-reload
#: workflow, never deployed, and holds no CUI. `rag-inference` is absent for a different
#: reason and it is a gap rather than an exemption — see the test below, which states it
#: rather than letting the silence pass for coverage.
FIPS_CAPABLE_IMAGES = {
    "backend/Dockerfile",
    "edge-agent/Dockerfile",
    "frontend/Dockerfile.prod",
}

#: Bases with no FIPS-validated cryptographic module available, at all.
FORBIDDEN_BASE = re.compile(
    r"^FROM\s+(python:[\d.]+-slim|node:[\d.]+-alpine|nginx:[\d.]+-alpine|.*-alpine\b)",
    re.M | re.I,
)

UBI_BASE = re.compile(r"^FROM\s+registry\.access\.redhat\.com/ubi9/", re.M)


def _dockerfile(name: str) -> str:
    path = ROOT / name
    assert path.exists(), f"{name} moved; this guard is now measuring nothing"
    return path.read_text()


class TestTheBasesAreCapable:
    @pytest.mark.parametrize("name", sorted(FIPS_CAPABLE_IMAGES))
    def test_every_stage_is_ubi(self, name):
        content = _dockerfile(name)
        froms = re.findall(r"^FROM\s+(\S+)", content, re.M)
        assert froms, f"{name} declares no FROM at all"
        non_ubi = [f for f in froms if not f.startswith("registry.access.redhat.com/ubi9/")]
        assert not non_ubi, (
            f"{name} has non-UBI stage(s) {non_ubi}. Debian ships no FIPS-validated OpenSSL "
            "and musl-based images have none available, so the cryptographic boundary this "
            "deployment claims cannot exist on them."
        )

    @pytest.mark.parametrize("name", sorted(FIPS_CAPABLE_IMAGES))
    def test_no_forbidden_base_creeps_back(self, name):
        found = FORBIDDEN_BASE.findall(_dockerfile(name))
        assert not found, f"{name} is back on a base with no validated module: {found}"

    def test_the_pattern_would_actually_catch_a_regression(self):
        """A positive control. A regex that matches nothing passes every file above."""
        assert FORBIDDEN_BASE.search("FROM python:3.11-slim\n")
        assert FORBIDDEN_BASE.search("FROM node:20-alpine AS build\n")
        assert FORBIDDEN_BASE.search("FROM nginx:1.27-alpine\n")
        assert not FORBIDDEN_BASE.search(
            "FROM registry.access.redhat.com/ubi9/python-311\n"
        )
        assert UBI_BASE.search("FROM registry.access.redhat.com/ubi9/nginx-124\n")

    def test_the_rag_image_is_a_stated_gap_not_a_silent_one(self):
        """`rag-inference/Dockerfile` is still `python:3.10-slim`.

        It is another lane's (MLOps) and it is not in the CUI path today — it serves RAG
        inference over documents the backend has already admitted. It is named here rather
        than omitted, because a guard whose scope quietly excludes an image is how "all our
        images are FIPS-capable" becomes a sentence nobody can support.
        """
        rag = ROOT / "rag-inference" / "Dockerfile"
        if not rag.exists():
            pytest.skip("rag-inference image removed")
        assert "rag-inference/Dockerfile" not in FIPS_CAPABLE_IMAGES, (
            "rag-inference joined the FIPS set; move it to UBI and delete this test"
        )


class TestTheRuntimeProbe:
    def test_it_reports_this_process_honestly(self):
        """On a developer machine and in CI this is a non-FIPS process, and the probe must
        say so. A probe that returns True everywhere is the failure this replaces."""
        status = fips_status()
        assert set(status) >= {"enforcing", "kernel_fips", "openssl_version", "providers"}
        assert isinstance(status["enforcing"], bool)

    def test_the_probe_gives_the_NEGATIVE_answer_when_it_should(self):
        """The mutation `return False` -> `return True` at the end of the probe survived
        everything else in this file, because every other test patches
        `crypto_is_enforcing` rather than running it. A probe that answers "yes, enforcing"
        unconditionally is precisely the reassuring lie `REQUIRE_FIPS_MODE` exists to stop,
        and it would have shipped.

        The oracle is established independently of the function: ask MD5 directly, then
        require the probe to agree. That catches always-True and always-False both, and it
        stays correct if CI ever does run on a FIPS-enforcing node.
        """
        import hashlib

        try:
            hashlib.new("md5", usedforsecurity=True)
            unapproved_crypto_available = True
        except (ValueError, TypeError):
            unapproved_crypto_available = False

        if unapproved_crypto_available:
            assert crypto_is_enforcing() is False, (
                "MD5 is available for security use in this process, and the probe still "
                "reports FIPS enforcement. That answer would let a deployment claim a "
                "validated cryptographic boundary it does not have."
            )
        else:  # pragma: no cover - only on a FIPS-enforcing host
            assert crypto_is_enforcing() is True

    def test_an_absent_kernel_flag_is_unknown_rather_than_false(self):
        """macOS, Alpine and every non-RHEL kernel simply do not publish the flag. Reporting
        `False` for "I cannot tell" makes the verdict wrong in the SAFE-LOOKING direction on
        exactly the platforms a developer reads it on."""
        with patch("app.core.fips.KERNEL_FIPS_FLAG", pathlib.Path("/nonexistent/fips")):
            assert kernel_fips_enabled() is None

    def test_the_kernel_flag_is_read_when_it_exists(self, tmp_path):
        flag = tmp_path / "fips_enabled"
        flag.write_text("1\n")
        with patch("app.core.fips.KERNEL_FIPS_FLAG", flag):
            assert kernel_fips_enabled() is True
        flag.write_text("0\n")
        with patch("app.core.fips.KERNEL_FIPS_FLAG", flag):
            assert kernel_fips_enabled() is False

    def test_the_probe_asks_about_security_use_not_md5_generally(self):
        """MD5 with `usedforsecurity=False` stays available under FIPS for cache keys and
        the like. Probing with the default flag would report "not enforcing" on a correctly
        enforcing system — the wrong answer in the direction that blocks a legitimate
        deployment from starting.

        BY AST, BECAUSE THE GREP VERSION DID NOT WORK. It asserted `"usedforsecurity=True"
        in source`, and the mutation removing the keyword from the CALL survived — the
        phrase still appears in the docstring three lines above, explaining why the keyword
        matters. A test that greps for a word cannot tell code from prose, which is a rule
        this repository already has (262's entry) and which I proceeded to trip over again
        in the file that cites it.
        """
        import ast

        tree = ast.parse((ROOT / "backend" / "app" / "core" / "fips.py").read_text())
        probe = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "crypto_is_enforcing"
        )
        calls = [
            node for node in ast.walk(probe)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "new"
        ]
        assert calls, "crypto_is_enforcing no longer calls hashlib.new; it probes nothing"
        for call in calls:
            keywords = {kw.arg: kw.value for kw in call.keywords}
            assert "usedforsecurity" in keywords, (
                "the behavioural probe dropped `usedforsecurity`, so it asks whether MD5 "
                "exists rather than whether it may be used for security — and reports a "
                "correctly enforcing system as non-enforcing"
            )
            value = keywords["usedforsecurity"]
            assert isinstance(value, ast.Constant) and value.value is True, (
                "the probe asks with usedforsecurity=False, which stays permitted under "
                "FIPS; it would report every system as non-enforcing"
            )


class TestItFailsClosed:
    def test_a_build_that_requires_fips_and_is_not_enforcing_raises(self):
        with patch("app.core.fips.crypto_is_enforcing", return_value=False):
            with pytest.raises(FIPSModeNotActive, match="not enforcing FIPS"):
                assert_fips_mode(required=True)

    def test_a_build_that_requires_fips_and_is_enforcing_passes(self):
        with patch("app.core.fips.crypto_is_enforcing", return_value=True):
            status = assert_fips_mode(required=True)
        assert status["enforcing"] is True

    def test_a_build_that_does_not_require_it_still_reports_status(self):
        """Recording what a deployment was actually running under is how "we thought that
        cluster was FIPS" becomes a log line rather than an assessor's question."""
        status = assert_fips_mode(required=False)
        assert "enforcing" in status

    def test_validate_settings_refuses_a_fips_claim_it_cannot_support(self):
        with patch("app.core.fips.crypto_is_enforcing", return_value=False):
            problems = validate_settings(Settings(REQUIRE_FIPS_MODE=True))
        assert any("REQUIRE_FIPS_MODE" in p for p in problems), problems

    def test_it_is_not_gated_on_production(self):
        """A staging deployment carrying the CUI flag and not enforcing FIPS is exactly the
        configuration somebody promotes. Catching it only in production catches it after."""
        with patch("app.core.fips.crypto_is_enforcing", return_value=False):
            problems = validate_settings(
                Settings(REQUIRE_FIPS_MODE=True, ENVIRONMENT="staging")
            )
        assert any("REQUIRE_FIPS_MODE" in p for p in problems), problems

    def test_the_default_is_off_and_silent(self):
        """Most deployments have no FIPS obligation, and a default of True would make every
        developer machine refuse to start on a claim nobody made."""
        assert Settings().REQUIRE_FIPS_MODE is False
        with patch("app.core.fips.crypto_is_enforcing", return_value=False):
            problems = validate_settings(Settings())
        assert not any("FIPS" in p for p in problems), problems

    def test_an_enforcing_process_with_the_flag_set_produces_no_problem(self):
        """The control case: a check that always complains would pass every test above."""
        with patch("app.core.fips.crypto_is_enforcing", return_value=True):
            problems = validate_settings(Settings(REQUIRE_FIPS_MODE=True))
        assert not any("FIPS" in p for p in problems), problems
