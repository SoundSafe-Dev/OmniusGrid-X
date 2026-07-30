"""The edge-fleet page is empty for every tenant, always — and the reason is a column
nobody writes.

`GET /api/v1/edge/fleet` backs the `/admin/collectors` page. It filters on
`EdgeAgentStatus.organization_id`, and `POST /api/v1/edge/heartbeat` — the only writer of
that table — **never sets that column**. Nothing else in the tree does either: the sole
occurrences of `organization_id` in `app/api/edge_fleet.py` are the two read filters.

So `organization_id` is NULL on every row, `NULL = '<uuid>'` is NULL, no row ever satisfies the
predicate, and the collectors page shows nothing no matter how many agents are heartbeating.
`GET /fleet/{agent_id}` 404s for the same reason. **This session's defect class exactly**: an
empty list reads as "no agents are enrolled" when what it means is "the query cannot match".

WHAT MAKES IT INSTRUCTIVE. The filter is not a mistake — it was ADDED as a security fix, and
the comment above it says so: the read used to be unscoped and every authenticated user saw
every tenant's agent ids, versions, cert expiry and buffer depths. That fix was right. It just
scoped a read against a column the write path never populated, so it turned a leak into a
permanent emptiness, and nothing failed. There was no test on either endpoint — the only edge
fleet tests cover the pure liveness helper.

AND THE OBVIOUS FIX WOULD HAVE BEEN A HOLE. The natural place to carry an agent's tenant is its
certificate, which is already the verified identity. But `sign_csr` copies the CSR's subject
wholesale (`.subject_name(csr.subject)`) and validates only the CN — so any attribute an agent
puts in its own CSR comes back CA-signed and indistinguishable from a server assertion. Reading
the organisation out of that subject would have been the tenant-from-body defect wearing a
certificate. The CA now builds the subject itself; `TestTheCaWillNotSignAClaimItDidNotMake`
is the guard, and it is written against the pre-fix behaviour.
"""

from __future__ import annotations

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

pytestmark = pytest.mark.asyncio


def _csr(agent_id: str, *, organization: str | None = None) -> str:
    """A CSR for `agent_id`, optionally CLAIMING an organisation in its own subject."""
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, agent_id)]
    if organization is not None:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization))
    key = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name(attrs))
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode()


def _enrolled_cert(agent_id: str, organization_id: str) -> str:
    """Mint an agent certificate through the same global the request path verifies against."""
    from app.services.edge_ca import edge_ca

    return edge_ca.sign_csr(
        _csr(agent_id), agent_id, organization_id=organization_id
    ).decode()


async def _heartbeat(client, cert_pem: str, **payload):
    return await client.post(
        "/api/v1/edge/heartbeat",
        json={"agent_version": "1.2.3", "buffer_pending": 7, **payload},
        headers={"X-Client-Cert": cert_pem},
    )


# ---------------------------------------------------------------------------
# The CA must not sign a claim it did not make
# ---------------------------------------------------------------------------

class TestTheCaWillNotSignAClaimItDidNotMake:
    """`sign_csr` used to do `.subject_name(csr.subject)` — copy the CSR's subject into the
    signed certificate, validating only the CN. Nothing read the other attributes, so it was
    harmless right up until something did."""

    async def test_the_organisation_comes_from_the_server_not_the_csr(self, seeded_orgs):
        from app.services.edge_ca import edge_ca

        org_a = str(seeded_orgs["org_a_id"])
        org_b = str(seeded_orgs["org_b_id"])

        # The agent asks for org B in its own CSR; the server is enrolling it into org A.
        pem = edge_ca.sign_csr(
            _csr("agent-forger", organization=org_b), "agent-forger", organization_id=org_a
        )
        principal = edge_ca.verify_agent_certificate(pem.decode())

        assert principal.organization_id == org_a, (
            "the certificate carries the organisation the CSR claimed, not the one the server "
            "assigned — client-supplied tenancy, CA-signed"
        )

    async def test_no_stray_csr_attribute_survives_into_the_certificate(self, seeded_orgs):
        """Not just the organisation. The subject is REBUILT, so an agent cannot smuggle any
        attribute past the CA — the guard is on the shape of the subject, not on one field."""
        from app.services.edge_ca import edge_ca

        key = ec.generate_private_key(ec.SECP256R1())
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(
                x509.Name(
                    [
                        x509.NameAttribute(NameOID.COMMON_NAME, "agent-smuggler"),
                        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "super-admin"),
                        x509.NameAttribute(NameOID.EMAIL_ADDRESS, "root@example.test"),
                    ]
                )
            )
            .sign(key, hashes.SHA256())
        )
        pem = edge_ca.sign_csr(
            csr.public_bytes(serialization.Encoding.PEM).decode(),
            "agent-smuggler",
            organization_id=str(seeded_orgs["org_a_id"]),
        )
        cert = x509.load_pem_x509_certificate(pem)
        oids = {a.oid for a in cert.subject}
        assert NameOID.ORGANIZATIONAL_UNIT_NAME not in oids
        assert NameOID.EMAIL_ADDRESS not in oids
        assert oids == {NameOID.COMMON_NAME, NameOID.ORGANIZATION_NAME}

    async def test_the_cn_check_still_holds(self, seeded_orgs):
        """Rebuilding the subject must not have removed the check that was already there."""
        from app.services.edge_ca import CertificateVerificationError, edge_ca

        with pytest.raises(CertificateVerificationError):
            edge_ca.sign_csr(
                _csr("attacker"), "agent-42", organization_id=str(seeded_orgs["org_a_id"])
            )


# ---------------------------------------------------------------------------
# The heartbeat has to attribute the row, or the list can never match
# ---------------------------------------------------------------------------

class TestTheHeartbeatAttributesTheAgent:
    async def test_a_heartbeat_records_the_organisation_from_the_certificate(
        self, app, client_a, seeded_orgs, admin_sync_url
    ):
        """THE WRITE HALF OF THE DEFECT. Before the fix this row was created with
        `EdgeAgentStatus(agent_id=...)` and nothing else — organization_id NULL, forever."""
        import psycopg2

        org_a = str(seeded_orgs["org_a_id"])
        cert = _enrolled_cert("agent-alpha", org_a)
        resp = await _heartbeat(client_a, cert)
        assert resp.status_code == 200, resp.text

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT organization_id FROM edge_agent_status WHERE agent_id = %s",
                    ("agent-alpha",),
                )
                row = cur.fetchone()
        finally:
            conn.close()

        assert row is not None, "the heartbeat wrote no row at all"
        assert row[0] == org_a, (
            "the status row is unattributed, so no tenant's query can ever match it — this is "
            "the whole defect, and it is why /admin/collectors is empty"
        )

    async def test_a_second_heartbeat_does_not_lose_the_attribution(
        self, app, client_a, seeded_orgs, admin_sync_url
    ):
        """The upsert path is the one that runs forever after; the insert path runs once. A fix
        that only sets the column on creation looks right in a fresh database and decays."""
        import psycopg2

        org_a = str(seeded_orgs["org_a_id"])
        cert = _enrolled_cert("agent-repeat", org_a)
        await _heartbeat(client_a, cert)
        await _heartbeat(client_a, cert, buffer_pending=99)

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT organization_id, buffer_pending FROM edge_agent_status "
                    "WHERE agent_id = %s",
                    ("agent-repeat",),
                )
                org, pending = cur.fetchone()
        finally:
            conn.close()

        assert pending == 99, "the second heartbeat did not update the row"
        assert org == org_a, "the update path dropped the attribution the insert path set"

    async def test_a_certificate_with_no_organisation_is_refused_not_silently_dropped(
        self, app, client_a, admin_sync_url
    ):
        """A certificate issued before agents carried a tenant. Under migration 057's policy
        there is no GUC to bind, so the write cannot succeed — and an unattributed row would be
        invisible to every tenant anyway. A 200 here would be a success response for a discarded
        write, which is the shape of every defect in this file. It is a 409 naming the remedy."""
        import psycopg2

        from app.services.edge_ca import edge_ca

        legacy = edge_ca.sign_csr(_csr("agent-legacy"), "agent-legacy").decode()
        resp = await _heartbeat(client_a, legacy)

        assert resp.status_code == 409, f"expected a refusal, got {resp.status_code}"
        assert "re-enroll" in resp.json()["detail"]

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM edge_agent_status WHERE agent_id = %s",
                    ("agent-legacy",),
                )
                assert cur.fetchone()[0] == 0, "an unattributed row was written anyway"
        finally:
            conn.close()


class TestThePolicyIsTheSecondLayer:
    """The handlers filter AND the table has a policy — migration 051's order, application
    layer first. These assert the policy independently of the handlers, so a future handler
    that forgets its filter is still contained."""

    async def test_the_table_is_protected_and_forced(self, app, admin_sync_url):
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = 'edge_agent_status'"
                )
                enabled, forced = cur.fetchone()
        finally:
            conn.close()

        assert enabled, "migration 057 did not enable row-level security"
        assert forced, (
            "RLS is enabled but not FORCEd — the owner bypasses the policy, and the application "
            "connects as the owner in several deployments, so this reads as protected and is not"
        )

    async def test_an_unbound_session_sees_nothing(self, app, client_a, seeded_orgs):
        """The mechanism, exercised rather than assumed: the same query that the handler runs,
        on a session with no GUC set, returns nothing."""
        from sqlalchemy import select

        from app.db import database as _database
        from app.db.edge_fleet_models import EdgeAgentStatus

        await _heartbeat(client_a, _enrolled_cert("agent-policy", str(seeded_orgs["org_a_id"])))

        async with _database.AsyncSessionLocal() as session:
            rows = (await session.execute(select(EdgeAgentStatus))).scalars().all()
        assert rows == [], "the policy did not filter an unbound read"


# ---------------------------------------------------------------------------
# The read half: what /admin/collectors actually shows
# ---------------------------------------------------------------------------

class TestTheFleetPageShowsTheFleet:
    async def test_an_agent_that_heartbeats_appears_in_its_own_fleet(
        self, app, client_a, seeded_orgs
    ):
        """THE ASSERTION THIS FILE EXISTS FOR, and it failed before the fix — the list was `[]`
        for every organisation, in every deployment, since the endpoint was written."""
        cert = _enrolled_cert("agent-visible", str(seeded_orgs["org_a_id"]))
        await _heartbeat(client_a, cert)

        resp = await client_a.get("/api/v1/edge/fleet")
        assert resp.status_code == 200, resp.text
        ids = [a["agent_id"] for a in resp.json()]
        assert "agent-visible" in ids, (
            "the fleet list is empty while the agent is heartbeating; an operator reads that as "
            f"'no agents enrolled'. Got: {resp.json()}"
        )

    async def test_the_detail_endpoint_finds_it_too(self, app, client_a, seeded_orgs):
        cert = _enrolled_cert("agent-detail", str(seeded_orgs["org_a_id"]))
        await _heartbeat(client_a, cert, buffer_pending=12)

        resp = await client_a.get("/api/v1/edge/fleet/agent-detail")
        assert resp.status_code == 200, resp.text
        assert resp.json()["buffer_pending"] == 12

    async def test_the_other_tenant_still_sees_none_of_it(
        self, app, client_a, client_b, seeded_orgs
    ):
        """The scoping was added for a reason. Making the list non-empty must not restore the
        leak it was fixing — this is the control on the fix, not a separate concern."""
        cert = _enrolled_cert("agent-of-a", str(seeded_orgs["org_a_id"]))
        await _heartbeat(client_a, cert)

        resp = await client_b.get("/api/v1/edge/fleet")
        assert resp.status_code == 200, resp.text
        assert [a["agent_id"] for a in resp.json()] == []

        detail = await client_b.get("/api/v1/edge/fleet/agent-of-a")
        assert detail.status_code == 404, (
            "org B can read org A's agent by id — ids, cert expiry and buffer depth"
        )

    async def test_one_tenant_cannot_claim_anothers_agent_id(
        self, app, client_a, client_b, seeded_orgs
    ):
        """`agent_id` is the PRIMARY KEY of `edge_agent_status` — one global namespace across
        every tenant, and `sign_csr` will issue a certificate for any id that is asked for.

        This was harmless while the column was never written: a second tenant enrolling the
        same id just overwrote buffer counters on a row nobody could read. Attributing the row
        gives the overwrite teeth — the last heartbeat wins the tenancy, so B enrolling
        `agent-of-a` silently moves A's agent onto B's fleet page and off A's. Fixing one half
        of a defect can arm the other half; the heartbeat now refuses the rebind.
        """
        org_a = str(seeded_orgs["org_a_id"])
        org_b = str(seeded_orgs["org_b_id"])

        await _heartbeat(client_a, _enrolled_cert("contested-id", org_a))

        # B enrols an agent using an id that already belongs to A.
        stolen = await _heartbeat(client_b, _enrolled_cert("contested-id", org_b))
        assert stolen.status_code == 409, (
            f"B's heartbeat was accepted for A's agent id (status {stolen.status_code})"
        )

        a_ids = {x["agent_id"] for x in (await client_a.get("/api/v1/edge/fleet")).json()}
        b_ids = {x["agent_id"] for x in (await client_b.get("/api/v1/edge/fleet")).json()}
        assert "contested-id" in a_ids, "A lost its own agent to B"
        assert "contested-id" not in b_ids, "B acquired A's agent"

    async def test_each_tenant_sees_exactly_its_own(
        self, app, client_a, client_b, seeded_orgs
    ):
        """Two populated fleets, not one populated and one empty. An assertion that B sees
        nothing passes just as well when the whole feature is broken — which is precisely how
        this defect survived. B must see B's agent and only B's."""
        await _heartbeat(client_a, _enrolled_cert("agent-a1", str(seeded_orgs["org_a_id"])))
        await _heartbeat(client_b, _enrolled_cert("agent-b1", str(seeded_orgs["org_b_id"])))

        a_ids = {x["agent_id"] for x in (await client_a.get("/api/v1/edge/fleet")).json()}
        b_ids = {x["agent_id"] for x in (await client_b.get("/api/v1/edge/fleet")).json()}

        assert "agent-a1" in a_ids and "agent-b1" not in a_ids
        assert "agent-b1" in b_ids and "agent-a1" not in b_ids
