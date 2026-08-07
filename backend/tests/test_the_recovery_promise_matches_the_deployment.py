"""No document promises point-in-time recovery the deployment cannot perform (FS-513).

WHAT THE PLAN SAID, AND WHY IT WAS WRONG. FS-513 was filed as "PITR still does not exist,
while root `README.md:405-406` presents it as live". The first half is true. **The second is
not** — those lines are a branch-comparison table mapping one repository path to another, and
they claim nothing about capability.

Measuring the actual documents found the opposite of the reported defect. Every one of them is
already explicit:

  * `docs/runbooks/database-backup-restore.md:11` — "**RPO** | Up to 24 h (no point-in-time
    recovery)"
  * `:19` — "Treat any pgBackRest instructions in the `docs/deployment/dr-*.md` runbooks as
    **not yet operational**"
  * `:72` — a section titled "**Restoring PITR (not yet done)**", listing the two things
    required: an image shipping the `pgbackrest` binary, and an `archive_command`.

So there is nothing dishonest to fix, and the capability itself needs a database image the
deployed stack does not run — which is not a defect fix and cannot be done from here.

WHAT IS WORTH BUILDING IS THE THING THAT KEEPS IT TRUE. This is a claim about a *capability*,
made in prose, contradicted by a manifest, and it has already gone wrong once in this repository
in the harder direction: `legacy-patroni/` held a pgBackRest CronJob that was in no
kustomization, so **staging and production had no backups at all while the DR runbooks
described restoring from a repository nothing wrote to**. The runbook now records that. The
next person to add `pgbackrest` to the image will update one document and not the other four,
and the failure will look exactly like the last one.

So this pairs the promise against the deployment: the qualifier stays until the CNPG
cutover has actually happened, and the moment it does, the qualifier must go — an
under-promising runbook sends an operator to the slower recovery during an incident, which is
the same kind of wrong pointing the other way.

IT ALSO FOUND ONE. `infrastructure/k8s/README.md` described `database-ha/` as providing
"continuous WAL archiving to S3 for PITR" and noted two lines later that the stack is opt-in —
but not on the sentence making the promise. An operator scanning for "PITR" reads the promise
and not the caveat, so the caveat now sits in the sentence itself.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNBOOK = REPO / "docs" / "runbooks" / "database-backup-restore.md"
STATEFULSET = REPO / "infrastructure" / "k8s" / "base" / "timescaledb-statefulset.yaml"
CNPG_CLUSTER = REPO / "infrastructure" / "k8s" / "database-ha" / "cluster.yaml"

#: Documents that describe recovery and could claim more than the stack can do.
RECOVERY_DOCS = [
    "docs/runbooks/database-backup-restore.md",
    "docs/runbooks/rto-rpo-checklist.md",
    "infrastructure/k8s/README.md",
]


def _pitr_is_deployed() -> tuple[bool, str]:
    """Whether the stack that is ACTUALLY DEPLOYED could perform a point-in-time restore.

    THE DETECTOR WAS WRONG FIRST, and instructively. Its first version asked for a database
    image shipping the `pgbackrest` binary. That is the requirement for the *legacy-patroni*
    path — the archived one — and it is not how CloudNativePG does PITR at all: CNPG uses
    barman-cloud, built into the operator's own image, driven by `backup.barmanObjectStore`.
    So the check demanded evidence the working path would never produce, and would have gone
    on reporting "no PITR" for the rest of the repository's life, including after somebody
    built it.

    The question that actually decides it is **which database the cluster is running**, not
    which binaries exist somewhere in the tree:

      * `base/timescaledb-statefulset.yaml` — a single pod, `pg_dump -Fc` nightly to S3, no
        WAL archiving. RPO up to 24 h. This is what ships.
      * `database-ha/` — CNPG with `barmanObjectStore` configured, which is genuine PITR. It
        is **opt-in**: it needs the CloudNativePG operator, the deploy job applies it only if
        the CRDs are present, and the cutover has never been performed.

    So PITR is real only once the CNPG cluster is what runs — which means the single-pod
    StatefulSet is gone from `base/`. Until then the documents must say so.
    """
    reasons = []

    archiving = False
    if CNPG_CLUSTER.exists():
        # Multi-document: the Cluster ships alongside its ScheduledBackup, so `safe_load`
        # raises rather than returning the first one.
        for doc in yaml.safe_load_all(CNPG_CLUSTER.read_text()):
            if doc and ((doc.get("spec") or {}).get("backup") or {}).get("barmanObjectStore"):
                archiving = True
    if STATEFULSET.exists() and "archive_command" in STATEFULSET.read_text():
        archiving = True
    if not archiving:
        reasons.append("no CNPG barmanObjectStore and no archive_command")

    single_pod_still_ships = STATEFULSET.exists()
    if single_pod_still_ships:
        reasons.append(
            "base/ still ships the single-pod TimescaleDB StatefulSet, so the CNPG cutover "
            "has not happened and the deployed database has no WAL archive"
        )

    return (archiving and not single_pod_still_ships), "; ".join(reasons)


class TestTheDeploymentIsMeasuredNotAssumed:
    def test_the_manifests_are_readable(self):
        """If neither manifest can be found, every assertion below reports "PITR is not
        deployed" for the wrong reason and would keep passing after somebody built it."""
        assert STATEFULSET.exists() or CNPG_CLUSTER.exists(), (
            "neither the TimescaleDB StatefulSet nor the CNPG Cluster was found; this guard "
            "cannot tell whether PITR is deployed and is silently answering 'no'"
        )


class TestTheRunbookQualifierTracksTheStack:
    def test_the_runbook_still_says_pitr_is_not_done(self):
        """Until the stack can do it. The moment it can, this test fails and the qualifier
        must be removed — a runbook that under-promises after the capability lands is the
        same kind of wrong, and sends an operator to a slower recovery in an incident."""
        deployed, why = _pitr_is_deployed()
        text = RUNBOOK.read_text()
        says_not_done = "not yet done" in text or "no point-in-time recovery" in text

        if deployed:
            assert not says_not_done, (
                "the CNPG cutover has happened and WAL archiving is configured, so "
                "point-in-time recovery is real — but the runbook still says it is not done. "
                "Update it: an operator reading this during an incident will fall back to the "
                "24-hour logical dump instead of restoring to the minute."
            )
        else:
            assert says_not_done, (
                f"the runbook no longer qualifies point-in-time recovery, and the deployment "
                f"still cannot perform one ({why}). This exact shape has already cost once "
                f"here: legacy-patroni/ held the pgBackRest CronJob, was in no kustomization, "
                f"and the DR runbooks described restoring from a repository nothing wrote to "
                f"— so staging and production had no backups at all."
            )

    def test_the_stated_rpo_matches_the_mechanism(self):
        """A logical `pg_dump` on a nightly CronJob has an RPO of up to a day. Stating
        anything tighter is a promise the schedule cannot keep."""
        deployed, _ = _pitr_is_deployed()
        if deployed:
            pytest.skip("PITR is deployed; the RPO is no longer bounded by the dump schedule")
        text = RUNBOOK.read_text()
        assert re.search(r"RPO.*24\s*h", text), (
            "the runbook's RPO line no longer says 24 hours while the only backup mechanism "
            "is a nightly logical dump. The number an operator plans around has to be the "
            "one the schedule produces."
        )

    @pytest.mark.parametrize("doc", RECOVERY_DOCS)
    def test_no_recovery_doc_claims_pitr_unqualified(self, doc: str):
        """The sweep. One document being honest is not the property that matters — the
        operator reads whichever one they found first."""
        deployed, why = _pitr_is_deployed()
        if deployed:
            pytest.skip("PITR is deployed; an unqualified claim is now correct")

        path = REPO / doc
        if not path.exists():
            pytest.skip(f"{doc} does not exist")

        unqualified = []
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if not re.search(r"\bPITR\b|point-in-time", line, re.I):
                continue
            # The vocabulary that counts as qualifying a claim. Deliberately explicit:
            # a looser pattern (any negation anywhere on the line) would let "PITR is not
            # optional" pass, and the point of this sweep is that the operator reads the
            # sentence, not the sentiment.
            qualified = re.search(
                r"not yet|not done|not available|no point-in-time|nobody is running|"
                r"has not happened|needs|requires|would|cannot|unavailable|opt-in|"
                r"planned|TODO|is a plan",
                line,
                re.I,
            )
            if not qualified:
                unqualified.append(f"{doc}:{number}: {line.strip()}")

        assert not unqualified, (
            f"these lines mention point-in-time recovery without saying it is unavailable, "
            f"while the deployment cannot perform one ({why}):\n  "
            + "\n  ".join(unqualified)
        )
