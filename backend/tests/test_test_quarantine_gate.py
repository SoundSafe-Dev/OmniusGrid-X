"""Regression coverage for the CI test-quarantine policy."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
CHECKER = BACKEND_ROOT / "scripts/check_test_quarantines.py"
CI_WORKFLOW = REPO_ROOT / ".github/workflows/ci-cd.yml"


def _check(tmp_path: Path, workflow: str) -> subprocess.CompletedProcess[str]:
    target = tmp_path / "ci.yml"
    target.write_text(workflow)
    return subprocess.run(
        [sys.executable, str(CHECKER), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_current_ci_has_no_unregistered_test_exclusions():
    if not CI_WORKFLOW.exists():
        pytest.skip("The backend-only container does not mount the repository's .github directory.")
    result = subprocess.run(
        [sys.executable, str(CHECKER), str(CI_WORKFLOW)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_pytest_exclusion_requires_a_named_marker(tmp_path):
    result = _check(tmp_path, "run: pytest --ignore=tests/test_broken.py\n")
    assert result.returncode == 1
    assert "requires a preceding TEST_QUARANTINE marker" in result.stderr


def test_expired_quarantine_fails_the_gate(tmp_path):
    result = _check(
        tmp_path,
        "# TEST_QUARANTINE --deselect=tests/test_broken.py::test_case "
        "owner=harsh expires=2000-01-01 reason=tracked regression\n"
        "run: pytest --deselect=tests/test_broken.py::test_case\n",
    )
    assert result.returncode == 1
    assert "expired on 2000-01-01" in result.stderr


def test_current_quarantine_with_future_expiry_is_allowed(tmp_path):
    result = _check(
        tmp_path,
        "# TEST_QUARANTINE --ignore=tests/test_broken.py "
        "owner=harsh expires=2099-01-01 reason=tracked regression\n"
        "run: pytest --ignore=tests/test_broken.py\n",
    )
    assert result.returncode == 0, result.stderr
