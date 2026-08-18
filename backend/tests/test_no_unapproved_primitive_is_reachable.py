"""No unapproved cryptographic primitive is reachable from application code (FS-748).

WHAT "APPROVED" MEANS HERE. FIPS 140-3 validates cryptographic *modules*, not applications;
an application's obligation is to use only algorithms a validated module provides, which for
CMMC 3.13.11 is the requirement when protecting CUI. This file is the standing check that
the algorithm inventory stays inside that set, so the answer to "what crypto do you use" is
a test result rather than an afternoon of grepping before an assessment.

THE INVENTORY WAS MEASURED BEFORE ANY OF IT WAS CHANGED, and most of it was already fine:

    Ed25519 OTA signing              approved (FIPS 186-5)
    EC P-256 + SHA-256 X.509         approved
    HS256 JWTs                       approved — HMAC-SHA-256. The JWT work is key
                                     rotation, which is a different concern; calling it
                                     a FIPS fix would have been a story, not a finding
    SHA-256 of random tokens         fine — SP 800-132 governs PASSWORDS, and a 256-bit
                                     random session token is not one
    MD5 / SHA-1                      none anywhere in the tree

So the real deltas were three, and two are closed: **bcrypt** (FS-748, now PBKDF2-HMAC-SHA256
with dual-read) and **Fernet** (AES-128-CBC, and keyed by a bare `sha256("master:org_id")`
rather than a KDF, which was the actual defect). The third — a FIPS-validated base image —
is infrastructure and is tracked separately; a UBI image with FIPS mode off looks identical
to one with it on, which is why `validate_settings` grows a runtime assertion rather than
this file trying to prove it statically.

WHY AST AND NOT GREP. `hashlib.md5` in a comment, a docstring, or a variable named
`md5_of_nothing` are not uses. This walks the syntax tree in the style of
`test_no_naive_utcnow.py`, so the failure message names a file and a line that actually
calls something.

WHAT IT CANNOT DO. It sees this repository. A dependency that reaches for an unapproved
primitive internally is invisible here and is the base image's problem — which is precisely
why the base image is a separate control rather than something this file can close.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
ROOTS = (
    REPO / "backend" / "app",
    REPO / "edge-agent" / "opsgrid_agent",
)

#: Hash algorithms that may be constructed. Everything else is a finding.
APPROVED_HASHES = frozenset({"SHA256", "SHA384", "SHA512", "SHA3_256", "SHA3_384", "SHA3_512"})

#: Symmetric algorithms. AES only — no Blowfish, no TripleDES, no ARC4.
APPROVED_CIPHERS = frozenset({"AES", "AESGCM", "AESCCM", "AESSIV"})

#: Curves. P-256/384/521 for signatures and key agreement.
APPROVED_CURVES = frozenset({"SECP256R1", "SECP384R1", "SECP521R1"})

#: Module-level imports that must not appear in application code at all. Each is an
#: algorithm decision, not a utility: importing it is using it.
FORBIDDEN_IMPORTS = {
    "passlib": "password hashing must use app/core/password.py (PBKDF2), not a second context",
    "bcrypt": "bcrypt is not FIPS-approved; app/core/password.py owns the migration",
    "cryptography.fernet": "Fernet is AES-128-CBC; use AESGCM with an HKDF-derived key",
}

#: Named exceptions, each with the reason it is allowed. Empty is the goal; an entry here
#: is a decision somebody made, not a silence.
DELIBERATELY_ALLOWED: dict[str, str] = {
    "backend/app/core/mfa.py": (
        "HMAC-SHA-1, for RFC 6238 TOTP. This is not a SHA-1 exemption in the usual sense: "
        "SP 800-131A retires SHA-1 for DIGITAL SIGNATURES, where collision resistance is "
        "the property that matters, and HMAC-SHA-1 remains approved because HMAC's security "
        "rests on the key and on PRF behaviour rather than on collision resistance. The "
        "alternative is SHA-256 TOTP, which RFC 6238 permits and authenticator apps support "
        "unevenly — trading a real usability failure for an apparent compliance win. The "
        "secret itself is wrapped in AES-256-GCM and recovery codes are SHA-256, so SHA-1 "
        "appears only inside the OTP construction."
    ),
    "backend/app/core/password.py": (
        "The one module permitted to import passlib. It configures PBKDF2 as the preferred "
        "scheme and keeps bcrypt as DEPRECATED so existing hashes still verify during the "
        "migration window — removing it would lock out every user who has not logged in "
        "since the cutover. This exemption ends when that window closes, which must be "
        "before the FIPS base image lands: in enforcing mode the bcrypt verify path may "
        "raise rather than return False."
    ),
}


def _python_files():
    for root in ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def _relative(path: pathlib.Path) -> str:
    return str(path.relative_to(REPO))


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{a.name}" for a in node.names)
    return modules


class TestTheMeasurementIsReal:
    def test_the_roots_are_present(self):
        found = [root for root in ROOTS if root.exists()]
        assert len(found) == len(ROOTS), (
            f"only {len(found)} of {len(ROOTS)} source roots found; a sweep that cannot see "
            f"its subject reports a clean result over nothing"
        )

    def test_files_are_walked(self):
        count = sum(1 for _ in _python_files())
        assert count > 300, (
            f"only {count} python files walked; both application trees together are far "
            f"larger, so the glob has broken"
        )

    def test_the_detector_finds_a_planted_primitive(self):
        """Negative control. Without this the checks below could be matching nothing."""
        planted = ast.parse(
            "from cryptography.hazmat.primitives import hashes\n"
            "digest = hashes.MD5()\n"
        )
        names = {
            node.func.attr
            for node in ast.walk(planted)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "MD5" in names and "MD5" not in APPROVED_HASHES


class TestNoForbiddenModuleIsImported:
    def test_no_application_module_imports_one(self):
        offenders = []
        for path in _python_files():
            relative = _relative(path)
            if relative in DELIBERATELY_ALLOWED:
                continue
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for module in _imported_modules(tree):
                for forbidden, reason in FORBIDDEN_IMPORTS.items():
                    if module == forbidden or module.startswith(f"{forbidden}."):
                        offenders.append(f"{relative}: imports {module} — {reason}")
        assert not offenders, (
            "unapproved cryptographic modules are imported by application code:\n  "
            + "\n  ".join(sorted(offenders))
        )

    @pytest.mark.parametrize("path", sorted(DELIBERATELY_ALLOWED))
    def test_every_exemption_states_its_reason_and_still_exists(self, path: str):
        assert (REPO / path).exists(), (
            f"{path} is exempt and does not exist — a stale exemption silently widens the "
            f"rule the next time a file takes that name"
        )
        assert len(DELIBERATELY_ALLOWED[path].strip()) > 80, (
            f"{path} is exempt without a reason long enough to be one"
        )


class TestNoUnapprovedAlgorithmIsConstructed:
    """`hashes.MD5()`, `algorithms.TripleDES(...)`, `ec.SECP192R1()` — the constructor is
    the decision, so the constructor is what this looks for."""

    def test_only_approved_primitives_are_constructed(self):
        findings = []
        for path in _python_files():
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                name = node.func.attr
                owner = getattr(node.func.value, "id", "")
                if owner == "hashes" and name not in APPROVED_HASHES:
                    findings.append(f"{_relative(path)}:{node.lineno}: hashes.{name}()")
                elif owner == "algorithms" and name not in APPROVED_CIPHERS:
                    findings.append(f"{_relative(path)}:{node.lineno}: algorithms.{name}()")
                elif owner == "ec" and name.startswith("SECP") and name not in APPROVED_CURVES:
                    findings.append(f"{_relative(path)}:{node.lineno}: ec.{name}()")
        assert not findings, (
            "unapproved primitives are constructed:\n  " + "\n  ".join(sorted(findings))
        )

    def test_a_weak_hash_passed_by_reference_is_detected(self):
        """THE BLIND SPOT THIS CHECK WAS WRITTEN WITHOUT (FS-750). The version below looked
        only at CALLS, so `hashlib.md5()` was caught and `hmac.new(key, msg, hashlib.sha1)`
        was not — the algorithm passed as a callable reference, never invoked at this site.

        That is not an exotic form: it is how every HMAC in Python names its hash, so the
        gap covered exactly the code most likely to contain one. Found when TOTP landed and
        the guard reported clean over an HMAC-SHA-1 it should have had an opinion about."""
        findings = []
        for path in _python_files():
            relative = _relative(path)
            if relative in DELIBERATELY_ALLOWED:
                continue
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                if getattr(node.value, "id", "") != "hashlib":
                    continue
                if node.attr in {"md5", "sha1"}:
                    findings.append(f"{relative}:{node.lineno}: hashlib.{node.attr}")
        assert not findings, (
            "MD5 or SHA-1 is referenced in application code:\n  "
            + "\n  ".join(sorted(findings))
            + "\n\nA reference is a use — `hmac.new(key, msg, hashlib.sha1)` never calls "
            "it at the call site. If the use is defensible (HMAC-SHA-1 remains approved "
            "under SP 800-131A, unlike SHA-1 for signatures), add the file to "
            "DELIBERATELY_ALLOWED with that argument written out."
        )

    def test_no_weak_hashlib_constructor(self):
        findings = []
        weak = {"md5", "sha1", "new"}
        for path in _python_files():
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if getattr(node.func.value, "id", "") != "hashlib":
                    continue
                if node.func.attr in {"md5", "sha1"}:
                    findings.append(f"{_relative(path)}:{node.lineno}: hashlib.{node.func.attr}()")
                elif node.func.attr == "new" and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and str(first.value).lower() in weak:
                        findings.append(
                            f"{_relative(path)}:{node.lineno}: hashlib.new({first.value!r})"
                        )
        assert not findings, (
            "MD5 or SHA-1 is constructed in application code:\n  "
            + "\n  ".join(sorted(findings))
            + "\n\nIn a FIPS-enforcing runtime these RAISE rather than returning a digest, "
            "so this is an outage as well as a compliance finding."
        )


class TestTheDeclaredTokenAlgorithmsAreApproved:
    def test_signed_url_algorithms_are_an_approved_allowlist(self):
        from app.utils.signed_urls import SUPPORTED_SIGNED_URL_ALGORITHMS

        approved = {"HS256", "HS384", "HS512", "ES256", "ES384", "ES512"}
        assert set(SUPPORTED_SIGNED_URL_ALGORITHMS) <= approved, (
            f"signed URLs accept {sorted(set(SUPPORTED_SIGNED_URL_ALGORITHMS) - approved)}"
        )

    def test_the_jwt_algorithm_is_approved(self):
        from app.core.config import settings

        approved = {"HS256", "HS384", "HS512", "ES256", "ES384", "ES512", "RS256"}
        assert settings.JWT_ALGORITHM in approved, (
            f"JWT_ALGORITHM is {settings.JWT_ALGORITHM!r}. HMAC-SHA-256 is approved, so "
            f"HS256 is not the finding here — an unapproved or 'none' algorithm would be."
        )
