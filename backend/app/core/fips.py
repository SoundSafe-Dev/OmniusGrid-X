"""Is FIPS mode actually on, or does the image merely look like it is? (FS-761)

THE PROBLEM THIS EXISTS FOR, stated as measured rather than assumed. A freshly pulled
`ubi9/python-311` container reports:

    openssl:     OpenSSL 3.5.5
    providers:   default          <- not `fips`
    kernel flag: absent
    md5:         allowed

That is a FIPS-CAPABLE image running with FIPS off, and from inside the application it is
indistinguishable from a FIPS-enforcing one unless something looks. Moving to a UBI base is
necessary and it is not sufficient: the container inherits the host kernel's FIPS state, so
the same image is compliant on one node and not on the node next to it, with no difference
anywhere in the manifest.

An unasserted claim of this kind is worse than no claim. "We run on a FIPS-validated module"
is the sentence an assessor tests first, and discovering the deployment answers it by base
image alone is the finding that costs the rest of the package its credibility — which is the
same reasoning that removed `SOC2_COMPLIANCE.md`.

THREE SIGNALS, AND THE BEHAVIOURAL ONE IS THE AUTHORITY:

  kernel      `/proc/sys/crypto/fips_enabled` — the host booted with `fips=1`. Necessary on
              RHEL and not sufficient: a process can still use a non-FIPS provider.
  providers   the `fips` provider appears in OpenSSL's active list. Closer, and still a
              statement about configuration rather than about what this process will do.
  enforcing   `hashlib.new("md5", usedforsecurity=True)` RAISES. This is what the application
              actually experiences, and it is the only one of the three that cannot be true
              while the crypto in use is unapproved.

The behavioural probe is deliberately `usedforsecurity=True`. MD5 with `usedforsecurity=False`
stays available under FIPS for non-security uses such as cache keys, so probing with the
default flag would report "not enforcing" on a correctly enforcing system.
"""

from __future__ import annotations

import hashlib
import os
import ssl
from pathlib import Path
from typing import Dict, Optional

import structlog

logger = structlog.get_logger()

#: The kernel's own answer, on the systems that have one.
KERNEL_FIPS_FLAG = Path("/proc/sys/crypto/fips_enabled")


def kernel_fips_enabled() -> Optional[bool]:
    """Whether the host booted with `fips=1`. `None` where the flag does not exist.

    `None` and not `False`, because macOS, Alpine and any non-RHEL kernel simply do not
    publish this — and reporting "FIPS is off" for "I cannot tell" would make the aggregate
    verdict wrong in the safe-looking direction on exactly the platforms where a developer
    reads it.
    """
    try:
        return KERNEL_FIPS_FLAG.read_text().strip() == "1"
    except (OSError, ValueError):
        return None


def crypto_is_enforcing() -> bool:
    """Does this process's crypto layer REFUSE an unapproved algorithm?

    The one signal that describes behaviour rather than configuration. If MD5 can still be
    used for a security purpose, then whatever the providers list says, this process is not
    constrained to validated cryptography.
    """
    try:
        hashlib.new("md5", usedforsecurity=True)
    except (ValueError, TypeError):
        # ValueError is the FIPS refusal. TypeError means a Python too old for the
        # `usedforsecurity` keyword, which is itself a Python that cannot express the
        # distinction — treated as not enforcing rather than as unknown.
        return True
    return False


def openssl_providers() -> tuple[str, ...]:
    """The active OpenSSL providers, best effort.

    Python exposes no provider API, so this shells out only if the binary is present. Absent
    output is not evidence of anything and is reported as an empty tuple rather than folded
    into the verdict.
    """
    import shutil
    import subprocess

    binary = shutil.which("openssl")
    if not binary:
        return ()
    try:
        result = subprocess.run(
            [binary, "list", "-providers"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    names = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("Providers", "name:", "version:", "status:")):
            names.append(stripped)
    return tuple(names)


def fips_status() -> Dict[str, object]:
    """Everything known about this process's cryptographic posture, for logs and evidence."""
    providers = openssl_providers()
    return {
        "enforcing": crypto_is_enforcing(),
        "kernel_fips": kernel_fips_enabled(),
        "openssl_version": ssl.OPENSSL_VERSION,
        "providers": list(providers),
        "fips_provider_active": any("fips" in name.lower() for name in providers),
        "python_hashlib_fips_hint": hasattr(hashlib, "get_fips_mode"),
    }


class FIPSModeNotActive(RuntimeError):
    """Raised at startup when a build that requires FIPS is not running under it."""


def assert_fips_mode(required: bool) -> Dict[str, object]:
    """Fail closed when a build claims FIPS and the process is not enforcing it.

    Returns the status either way so the caller can log it — a build that does NOT require
    FIPS still benefits from recording what it was actually running under, because "we
    thought that cluster was FIPS" is a discovery best made from a log line rather than from
    an assessor's question.
    """
    status = fips_status()
    if not required:
        return status
    if not status["enforcing"]:
        raise FIPSModeNotActive(
            "REQUIRE_FIPS_MODE is set and this process is not enforcing FIPS: "
            f"openssl={status['openssl_version']}, providers={status['providers']}, "
            f"kernel_fips={status['kernel_fips']}. A FIPS-capable base image is not a "
            "FIPS-enforcing runtime — the container inherits the host kernel's state, so "
            "boot the node with `fips=1` and verify with "
            "`openssl list -providers` inside the pod."
        )
    return status
