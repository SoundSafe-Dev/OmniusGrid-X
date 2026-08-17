"""The documentation may not claim point-in-time recovery while nothing archives WAL (FS-738).

WHAT ACTUALLY RUNS. A nightly logical backup — `pg_dump -Fc` to S3 via the `db-backup`
CronJob — with a restore drill in the blocking CI gate. That is a real, tested recovery
path, and its RPO is **up to 24 hours**.

WHAT DOES NOT RUN. Point-in-time recovery. Two artefacts describe it and neither is in
force:

  * `infrastructure/k8s/database-ha/cluster.yaml` configures CloudNativePG with barman WAL
    archiving, and `ci-cd.yml` applies that stack **only if** `clusters.postgresql.cnpg.io`
    exists in the target cluster. No current environment has the operator installed.
  * `infrastructure/k8s/legacy-patroni/pgbackrest-backup.yml` is in no kustomization and is
    applied by nothing.

Meanwhile the deployed image is `timescale/timescaledb:latest-pg15`, which ships no
`pgbackrest` binary, and no `archive_mode`/`archive_command` is set anywhere on that path.
Without WAL archiving there is no PITR, whatever the runbooks say.

WHY THIS IS A TEST. The gap was already written down — accurately — in `db-backup-cronjob.yaml`
and in one README bullet, and three other places went on presenting PITR as a live property
of the platform, including a table row reading `RPO≈0`. A caveat in one file does not
constrain a claim in another; only a test does. This pairs the claim to the artefact in both
directions, so the day WAL archiving is switched on, the stale caveats fail rather than
quietly understating the product.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
K8S = REPO / "infrastructure" / "k8s"
README = REPO / "README.md"

#: The phrase that must accompany a PITR claim while WAL archiving is off. Short and
#: greppable on purpose — when this clears, `grep` finds every site that has to change.
#: "not yet operational" is here because the README already said exactly that, in the one
#: place that was honest — and an over-tight marker list would have demanded the sentence be
#: reworded to satisfy the test rather than the reader. A guard that makes correct prose
#: fail teaches people to edit prose for the guard.
CAVEAT_MARKERS = (
    "not operational",
    "not yet operational",
    "aspirational",
    "no pitr",
)

#: Files that describe the DEPLOYED database path. `database-ha/` is deliberately excluded:
#: it is the manifest for a cluster nothing currently runs, and it is allowed to describe
#: PITR in full — that is what it is for.
DEPLOYED_DB_PATHS = [
    K8S / "base" / "timescaledb-statefulset.yaml",
    K8S / "base" / "db-backup-cronjob.yaml",
]


def _wal_archiving_is_on() -> bool:
    """Is anything on the deployed path actually archiving WAL?

    Narrow by design: it looks for `archive_mode` / `archive_command` on the StatefulSet
    path, which is what PITR needs and what the current image does not have. It does NOT
    consult `database-ha/`, because a manifest that is applied only where an operator
    exists is not evidence that the operator exists.
    """
    for path in DEPLOYED_DB_PATHS:
        if not path.exists():
            continue
        text = path.read_text()
        for marker in ("archive_mode", "archive_command"):
            # Only count an ENABLING occurrence: both files currently mention the words
            # in comments explaining their absence, and a substring match would read
            # those as proof of the opposite.
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if marker in stripped:
                    return True
    return False


def _pitr_claims() -> list[tuple[int, str]]:
    """README lines asserting PITR or a near-zero RPO."""
    pattern = re.compile(r"PITR|point-in-time recovery|RPO\s*[≈~]\s*0", re.I)
    return [
        (n, line)
        for n, line in enumerate(README.read_text().splitlines(), 1)
        if pattern.search(line)
    ]


class TestTheMeasurementIsReal:
    def test_the_deployed_paths_exist(self):
        """If these manifests move, every assertion below evaluates over nothing."""
        missing = [p.name for p in DEPLOYED_DB_PATHS if not p.exists()]
        assert not missing, f"{missing} not found under {K8S}; this check cannot run"

    def test_the_readme_still_mentions_recovery(self):
        assert _pitr_claims(), (
            "no PITR/RPO claim found in the README at all. If the wording changed, this "
            "guard is now watching a phrase nobody uses."
        )

    def test_the_archiving_detector_ignores_comments(self):
        """Both manifests explain the ABSENCE of archiving in prose. A detector that
        counted those would report archiving as on and silently invert this whole file."""
        text = (K8S / "base" / "db-backup-cronjob.yaml").read_text()
        assert "archive_mode" in text, (
            "the cronjob no longer explains why there is no archive_mode; the control for "
            "this detector is gone"
        )
        assert not _wal_archiving_is_on(), (
            "the detector counted a commented mention of archive_mode as archiving being "
            "enabled"
        )


class TestAClaimMatchesTheDeployment:
    def test_no_pitr_claim_stands_uncaveated(self):
        if _wal_archiving_is_on():
            pytest.skip("WAL archiving is configured; PITR claims are allowed to stand")
        text = README.read_text()
        lines = text.splitlines()
        bare = []
        for n, line in _pitr_claims():
            # The caveat must be on the claim's own line or within the two lines around
            # it — a reader scanning a table row does not read the next section.
            window = " ".join(lines[max(0, n - 3): n + 2]).lower()
            if not any(marker in window for marker in CAVEAT_MARKERS):
                bare.append(f"README:{n}: {line.strip()[:110]}")
        assert not bare, (
            "these lines present point-in-time recovery (or an RPO near zero) as a live "
            "property, and nothing on the deployed path archives WAL — the image ships no "
            "`pgbackrest` and sets no `archive_mode`, so the real RPO is the nightly "
            "`pg_dump`'s, up to 24 hours:\n  " + "\n  ".join(bare)
        )

    def test_the_caveat_goes_once_pitr_is_real(self):
        """THE DIRECTION THAT ROTS. When WAL archiving lands, a stale 'not operational'
        understates the platform, and nobody re-reads the README on an infra change."""
        if not _wal_archiving_is_on():
            pytest.skip("WAL archiving is still off; the caveats are correct")
        text = README.read_text().lower()
        stale = [m for m in ("point-in-time recovery is not", "pitr is not operational") if m in text]
        assert not stale, (
            f"WAL archiving is configured and the README still says {stale}. Remove the "
            f"caveat, and re-point the DR runbooks that were marked aspirational."
        )
