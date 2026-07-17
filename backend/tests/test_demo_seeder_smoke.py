"""Demo-seeder smoke (FS-137): the offline demo must keep working.

Runs ``scripts/seed_demo_data.py --verify`` against a throwaway SQLite database
in a subprocess and asserts the seeder's own 25-check verification passes. This
guards the `make demo` one-shot (FS-135): every page's demo data, the seeder's
dialect portability, and the endpoint contracts its verify walks (kanban, OEE,
fleet OTA, notifications, historian, RUL, ...). No docker required, so it runs
locally and in CI's backend job alike.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_offline_demo_seed_and_verify(tmp_path):
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'demo_smoke.db'}",
        "ALLOW_DEV_TOKEN": "true",
    }
    result = subprocess.run(
        [sys.executable, str(BACKEND / "scripts" / "seed_demo_data.py"), "--verify"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    tail = "\n".join(result.stdout.splitlines()[-40:])
    assert result.returncode == 0, (
        f"demo seeder verify failed (exit {result.returncode}):\n{tail}\n"
        f"stderr tail:\n{result.stderr[-1500:]}"
    )
    assert "VERIFY: PASS" in result.stdout, f"no VERIFY: PASS in output:\n{tail}"
