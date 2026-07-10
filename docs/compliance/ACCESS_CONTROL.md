# Compliance Access Control

## Authorization Model

Compliance APIs enforce both role-based authorization and tenant isolation.
Passing a role check never grants access to another organization. Tenant-owned
records are always queried using the authenticated user's organization, and a
cross-organization record is returned as not found.

| Capability | Admin | Operator | Viewer |
|---|---:|---:|---:|
| View compliance inventories and summary | Yes | Yes | Yes |
| Create, update, or delete compliance records | Yes | No | No |
| Generate compliance reports | Yes | No | No |
| View report status | Yes | No | Yes |
| Download completed reports | Yes | No | Yes |
| Create or manage report schedules | Yes | No | No |
| Receive scheduled report email | Yes | No | No |
| Create data-processing records | Yes | No | No |
| Use personal GDPR export and erasure | Yes | Yes | Yes |
| Export or erase another tenant user's data | Yes | No | No |
| Use manual `/admin/*` maintenance operations | Yes | No | No |

The existing `viewer` role is used for read-only report access. There is no
separate `report_viewer` role.

## GDPR Operations

Personal GDPR endpoints remain self-service:

- `GET /api/v1/gdpr/data-export`
- `DELETE /api/v1/gdpr/data-delete?confirmation=DELETE`

Administrator-assisted operations use separate endpoints:

- `GET /api/v1/gdpr/admin/users/{user_id}/data-export`
- `DELETE /api/v1/gdpr/admin/users/{user_id}/data-delete?confirmation=DELETE`

The administrator endpoints require the `admin` role and restrict the target
user to the administrator's organization. Cross-organization user IDs return
`404`.

## Report Access

Report generation and schedule management remain admin-only. Administrators
and viewers may check the status of and download reports belonging to their
organization.

Time-limited signed download links are capability credentials. Their public
route does not require a bearer token, but validates the token purpose,
organization, report job, signature, and expiration before serving a file.

Scheduled-report recipients remain restricted to active administrators in the
schedule's organization.

## Role Assignment

Authorization roles cannot be changed through the self-service user-context
endpoint. That endpoint accepts only department and priority updates.

The development registration endpoint always creates an `operator`, regardless
of a caller-supplied role. Administrative role assignment must use an approved
administrator or identity-provider workflow.

## Response Semantics

- `401 Unauthorized`: authentication is absent or invalid.
- `403 Forbidden`: the authenticated role cannot perform the operation, or the
  account has no organization where one is required.
- `404 Not Found`: a tenant-owned target does not exist in the caller's
  organization. This avoids revealing cross-organization identifiers.

## New Endpoint Checklist

When adding a protected compliance endpoint:

1. Inject `get_current_active_user`.
2. Use `get_tenant_org_id` and `get_tenant_db` for tenant-owned data.
3. Add `@require_admin()` for administrative actions or `@require_roles(...)`
   for an explicitly approved role set.
4. Keep role checks and tenant checks independent.
5. Add integration tests for unauthenticated, unauthorized, authorized, and
   cross-tenant requests.
