"""Lock the deliberate non-mounting of data_retention.router.

data_retention.py defines two routers. `tenant_router` (per-org retention
policies) is mounted. `router` is a GLOBAL operator surface — it reads/writes
the table-keyed data_retention_config (no organization_id) and triggers the
archive_to_cold_storage() / purge_old_data() DB functions across all tables and
tenants, gated only by the PER-ORG `require_admin`. Mounting it as-is would let
any tenant admin purge or archive every tenant's data.

The audit flagged these 8 routes as "silently unreachable — nothing says why".
Now the file says why, and this guard makes the decision enforceable: if someone
mounts `router` (rather than a super-admin-gated replacement), this fails and
points them at the auth-model problem to solve first.
"""

import re
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"


def test_global_data_retention_router_is_not_mounted():
    source = MAIN.read_text()

    # tenant_router must stay mounted (the tenant-scoped surface).
    assert "data_retention.tenant_router" in source, (
        "the tenant-scoped data_retention.tenant_router should be mounted"
    )

    # The global `router` must NOT be mounted. `\brouter\b` after the dot
    # excludes `tenant_router`. If this trips, do not just delete the assertion:
    # gate the router behind a super-admin/operator role first (see the comment
    # on `router` in app/api/data_retention.py), because its routes act across
    # all tenants.
    mounts_global = re.search(r"data_retention\.router\b", source)
    assert mounts_global is None, (
        "app.main mounts the GLOBAL data_retention.router — its routes "
        "(config/archive/purge over table-keyed, tenant-less retention) run "
        "across all tenants but are only per-org require_admin gated. Gate it "
        "behind a super-admin role before mounting; see the comment on `router` "
        "in app/api/data_retention.py."
    )
