# Backend endpoint map — Omnius Grid mobile app

This document ties each **mobile screen** (from the product IA) to **existing FastAPI routes** under `backend/app/`. Paths are composed as `main.py` `include_router(prefix=...)` plus each sub-router’s own `prefix` (if any). **Some routers nest a second segment** (for example `yard` appears twice); always confirm with `/openapi.json` on the running server.

Global headers (except login): `Authorization: Bearer <token>`.

---

## 0. Path prefix cheat sheet

| Area | Base path fragment |
|------|---------------------|
| Auth | `/api/v1/auth` |
| Assets | `/api/v1/assets` |
| Telemetry | `/api/v1/telemetry` |
| Alarms | `/api/v1/alarms` |
| Operations | `/api/v1/operations` |
| Dashboard | `/api/v1/dashboard` |
| Engines (admin) | `/api/v1/engines` |
| Yard | `/api/v1/yard` + router prefix `/yard` → **`/api/v1/yard/yard`** |
| Transportation | `/api/v1/transportation` + router prefix `/transportation` → **`/api/v1/transportation/transportation`** |
| Logistics | `/api/v1/logistics` + router prefix `/logistics` → **`/api/v1/logistics/logistics`** |
| Commands (admin) | `/api/v1/commands` |
| OEE | `/api/v1/oee` |
| Kanban | `/api/v1/kanban` |
| Registries | `/api/v1/registries` |
| WebSocket | `/ws` (no `/api/v1` prefix) |
| Health | `/health`, `/health/live`, `/health/ready`, … |

Root: `GET /`, `GET /health`.

---

## 1. Authentication & role context

### 1.1 Login screen

| Action | Method | Path | Body / params | Notes |
|--------|--------|------|-----------------|-------|
| Log in | `POST` | `/api/v1/auth/login` | `application/x-www-form-urlencoded`: `username` (email), `password` | OAuth2 password form; **not** JSON. |
| Current user / profile | `GET` | `/api/v1/auth/me` | — | Returns `id`, `email`, `full_name`, `role`, `organization_id`, `last_login`. |
| Register (dev) | `POST` | `/api/v1/auth/register` | JSON `UserCreate`: `email`, `password`, `full_name`, `organization_id`, `role` | Intended for dev; production may disable. |

**Mock / filler**

- **Forgot password:** no API. Show static copy or deep link to IT; optionally open `mailto:` with a template.
- **Contact admin:** no messaging API. Use local queue + `mobile/fixtures/mock-contact-admin.json` pattern, or `mailto:` / SMS intent.

**Demo user**

- See `mobile/fixtures/omnius-supervisor.json` (Omnius K. Patel, `omnius@omniusgrid.com`).

---

## 2. Home screen

Purpose: greeting + summary cards (tasks, alerts, assets/trucks).

| Data | Method | Path | Query / notes |
|------|--------|------|----------------|
| User name for greeting | `GET` | `/api/v1/auth/me` | Use `full_name` or first token. |
| Task counts (by column) | `GET` | `/api/v1/kanban/metrics` | `tasks_by_column` keys: `backlog`, `triage`, `in_progress`, `review`, `rejected`, `done`; `tasks_completed_today`. |
| Full board (optional) | `GET` | `/api/v1/kanban/board` | Optional filters as query params from handler. |
| Active alarms summary | `GET` | `/api/v1/alarms/active` | Optional `organization_id`, `severity`. Returns `count`, `by_severity`, `alarms`. |
| Dashboard aggregates | `GET` | `/api/v1/dashboard/overview` | Optional `organization_id`; `active_alarms`, `critical_alarms`, `assets_by_state` (PackML), etc. |
| Real-time refresh (optional) | WebSocket | `/ws?token=...&organization_id=...` | Subscribes to `alarm`, `state`, etc. |

**Mobile “New / In Progress / Completed” vs backend Kanban**

- Backend columns are **not** literally named `new`. Map UI **New** to tasks in **`triage`** and/or **`backlog`** (and optionally **`review`**) depending on product rules; **In Progress** → `in_progress` (and optionally `review`); **Completed** → `done` + `tasks_completed_today` from metrics.
- Prefer one `GET /api/v1/kanban/board` call, then **client-side** filter by column `column_type` from embedded column metadata, or multiple `GET /api/v1/kanban/tasks?column_id=<uuid>` calls using column ids from the board payload.

**Trucks / yard snapshot (optional)**

- `GET /api/v1/yard/yard/trailers` (see prefix note) — list trailers and statuses for “arrived / docked” style cards.
- `GET /api/v1/transportation/transportation/shipments` — shipment list if TMS data is populated.

**Mock / filler**

- If metrics fail (e.g. duplicate boards), fall back to counting tasks from `GET /kanban/board` client-side and show a generic error toast.

---

## 3. Tasks module

### 3.1 Tasks list (Kanban simplified)

| Action | Method | Path | Query / body |
|--------|--------|------|--------------|
| List tasks | `GET` | `/api/v1/kanban/tasks` | `board_id`, `column_id`, `assignee_id`, `task_type`, `priority`, `status`, `approval_status`, `limit`, `offset` |
| Board + columns + tasks | `GET` | `/api/v1/kanban/board` | Same as web; good for initial load. |
| Filtered board view | `POST` | `/api/v1/kanban/board/view` | JSON `KanbanViewFilter` |

**Task card fields (from `TaskResponse`)**

- Title, description, `priority`, `status`, `task_type`, `asset_id`, `assigned_at`, `due_date`, `column_id` (resolve column type via board columns).

### 3.2 Task detail & actions

| Action | Method | Path | Notes |
|--------|--------|------|-------|
| Task detail | `GET` | `/api/v1/kanban/tasks/{task_id}` | |
| Update fields | `PUT` | `/api/v1/kanban/tasks/{task_id}` | JSON `TaskUpdate` |
| Move column | `POST` | `/api/v1/kanban/tasks/{task_id}/move` | JSON `TaskMoveRequest` (`target_column_id`, optional `position`) |
| Approve from backlog | `POST` | `/api/v1/kanban/tasks/{task_id}/approve` | JSON `TaskApprovalRequest`: `approve` or `reject` + `reason` if reject |
| **Accept / start work** | `POST` | `/api/v1/kanban/tasks/{task_id}/start` | Moves **Triage → In Progress** (per handler). |
| **Complete** | `POST` | `/api/v1/kanban/tasks/{task_id}/complete` | Moves to **Done**, stops timer. |
| **Reopen** | `PUT` or `POST` | `/api/v1/kanban/tasks/{task_id}` + `/move` | No dedicated “reopen”; move from `done` to `triage` / `in_progress` with `TaskUpdate` / `TaskMoveRequest`. |
| Notes / activity | `GET` | `/api/v1/kanban/tasks/{task_id}/comments` | |
| Add note | `POST` | `/api/v1/kanban/tasks/{task_id}/comments` | JSON `TaskCommentBase` (`content`, `comment_type`) |
| Time (optional) | `POST` | `/api/v1/kanban/tasks/{task_id}/timer/start` | |
| | `POST` | `/api/v1/kanban/tasks/{task_id}/timer/stop` | |
| | `GET` | `/api/v1/kanban/tasks/{task_id}/time-logs` | |

**Mapping UI buttons**

- **Accept** (task ready in triage): `POST .../start`.
- If task is still in **backlog** pending approval: `POST .../approve` with `action: approve` first, then `start` as needed.
- **Complete:** `POST .../complete`.
- **Alert admin:** mock / `mailto:` / future messaging API.

**Related entity names**

- If `asset_id` set: `GET /api/v1/assets/{asset_id}` for machine/truck name.
- `created_by` is a UUID; no public “user lookup by id” for non-admins in the listed routes—show “Admin” or cache assigner names from `auth/me` only for self.

---

## 4. Alerts module

### 4.1 Alerts list

| Action | Method | Path | Query |
|--------|--------|------|--------|
| List alarms | `GET` | `/api/v1/alarms/` | `asset_id`, `is_active`, `severity`, `acknowledged`, `start_time`, `end_time`, `skip`, `limit` (defaults to last 24h if no time range) |
| Active only | `GET` | `/api/v1/alarms/active` | `organization_id`, `severity` |

**Filter mapping**

- **Active:** `is_active=true` and `acknowledged=false` (or use `/alarms/active`).
- **Acknowledged:** `acknowledged=true` (and typically still `is_active` per your rules).
- **Resolved / cleared:** `is_active=false` or use cleared timestamps; **`POST .../clear`** sets inactive.

### 4.2 Alert detail & actions

| Action | Method | Path | Body |
|--------|--------|------|------|
| Detail | `GET` | `/api/v1/alarms/{alarm_id}` | |
| Acknowledge | `POST` | `/api/v1/alarms/{alarm_id}/acknowledge` | JSON `AlarmAcknowledge`: optional `comment` |
| Clear / resolve | `POST` | `/api/v1/alarms/{alarm_id}/clear` | — |
| Acknowledge all | `POST` | `/api/v1/alarms/acknowledge-all` | Optional `asset_id`, `severity`; handler also takes `user_id` in code—verify OpenAPI |

**Asset line on card**

- Join with `GET /api/v1/assets/{asset_id}` using `AlarmResponse.asset_id`.

**Gaps**

- `acknowledge_alarm` accepts `user_id: UUID = None` without `Depends` auth injection—mobile should still send JWT; consider a backend follow-up to set `acknowledged_by` from the token. Until then, comment may still persist.

- **“Alert admin”** after acknowledge: mock / external channel.

---

## 5. Assets module

### 5.1 Assets overview (machines + “other”)

| Action | Method | Path | Query |
|--------|--------|------|--------|
| List assets | `GET` | `/api/v1/assets/` | `organization_id`, `workcell_id`, `asset_type_id`, `is_active`, `skip`, `limit` |
| Asset types | `GET` | `/api/v1/assets/types/` | optional `category` |

**Status / metrics**

- `GET /api/v1/assets/{asset_id}/status` — PackML-oriented snapshot (`current_packml_state`, `last_seen`).
- `GET /api/v1/telemetry/{asset_id}/latest` — latest telemetry points.
- `GET /api/v1/telemetry/{asset_id}/history` — history (time range query per OpenAPI).
- `GET /api/v1/oee/current/{asset_id}` — OEE block for detail screen.

**Trucks (yard / TMS)**

- Trailers: `GET /api/v1/yard/yard/trailers` (+ `GET /.../trailers/{trailer_id}`).
- Shipments: `GET /api/v1/transportation/transportation/shipments`, `GET .../shipments/{shipment_id}`.

**Search**

- Client-side filter on `name` / id from list payloads unless you add a dedicated search endpoint later.

### 5.2 Asset detail & supervisor actions

| Domain | Method | Path | Notes |
|--------|--------|------|-------|
| Refresh asset | `GET` | `/api/v1/assets/{asset_id}` and `/status` | Pull-to-refresh |
| Update asset metadata | `PUT` | `/api/v1/assets/{asset_id}` | JSON `AssetUpdate` — use only fields your role is allowed to change |
| **Machine-style state** | — | — | PackML / machine state may come from telemetry/OEE, not a single “Mark Running” REST button. Map **Running / Idle / Alert / Down** from `current_packml_state`, `is_active`, and linked **alarms** (`GET /api/v1/alarms/?asset_id=...`). |
| **Trailer / yard status** | `PUT` | `/api/v1/yard/yard/trailers/{trailer_id}` | JSON `YardTrailerUpdate` — `status` values per schema (e.g. `checked_in`, `docked`, `yard`, `checked_out`) |
| Dock flow | `POST` | `/api/v1/yard/yard/dock/appointments/.../start`, `/complete` | See `yard.py` |
| Shipment status | `POST` | `/api/v1/transportation/transportation/shipments/{shipment_id}/status` | Query param **`status`** (required), optional `actual_pickup`, `actual_delivery` |

**Admin-only (not for typical supervisor app)**

- `POST /api/v1/commands/submit`, emergency stop, collector restart, etc. require **`require_admin_user`** in `commands.py` and parts of `health.py`. Hide for supervisor persona unless you relax backend policy.

---

## 6. More / settings

| Action | Method | Path |
|--------|--------|------|
| Profile | `GET` | `/api/v1/auth/me` |
| Logout | — | Client-only: drop token. |
| Org user list (admin) | `GET` | `/api/v1/auth/users` | **Admin-only** (`require_admin_user`). |

**Mock**

- Help / static pages / `mailto:support@...`.

---

## 7. Global UX patterns (backend support)

| Pattern | Endpoint / approach |
|---------|---------------------|
| Pull to refresh | Re-call list/detail `GET`s above. |
| Live alarms / state | `WebSocket` `/ws?token=<jwt>&organization_id=<uuid>` |
| Connectivity check | `GET /health` or `GET /health/live` |

---

## 8. Full route inventory (reference)

### Auth — `/api/v1/auth`

- `POST /login`
- `POST /register`
- `GET /me`
- `GET /users` (admin)

### Assets — `/api/v1/assets`

- `GET /`
- `GET /{asset_id}`
- `POST /`
- `PUT /{asset_id}`
- `DELETE /{asset_id}`
- `GET /types/`
- `GET /{asset_id}/status`

### Telemetry — `/api/v1/telemetry`

- `GET /{asset_id}/latest`
- `GET /{asset_id}/history`
- `GET /{asset_id}/metrics`

### Alarms — `/api/v1/alarms`

- `GET /`
- `GET /active`
- `GET /{alarm_id}`
- `POST /{alarm_id}/acknowledge`
- `POST /{alarm_id}/clear`
- `POST /acknowledge-all`

### Operations — `/api/v1/operations`

- `GET /`
- `GET /active`
- `GET /{operation_id}`
- `POST /`
- `POST /{operation_id}/complete`
- `GET /{operation_id}/packml-summary`

### Dashboard — `/api/v1/dashboard`

- `GET /overview`
- `GET /workcells/{workcell_id}/status`
- `GET /assets/{asset_id}/oee`
- `GET /fleet/oee`

### Engines — `/api/v1/engines` (admin)

- `GET /tactical/status`, `POST /tactical/infer`
- `GET /strategic/recommendations`, `POST /.../approve`, `POST /.../reject`
- `GET /mlops/status`, `POST /mlops/deploy/{version}`, `POST /mlops/rollback`
- `GET /cloud/status`, `POST /cloud/flush`

### Yard — `/api/v1/yard/yard`

- `POST /trailers/checkin`
- `POST /trailers/{trailer_id}/checkout`
- `GET /trailers`, `GET /trailers/{trailer_id}`, `PUT /trailers/{trailer_id}`
- Dock doors: `POST /dock/doors`, `GET /dock/doors`, `POST /dock/doors/{door_id}/assign/{trailer_id}`
- Appointments: `POST /dock/appointments`, `GET /dock/appointments`, `POST /dock/appointments/{appointment_id}/start`, `POST /.../complete`
- Moves: `POST /moves`, `POST /moves/{move_id}/complete`
- `GET /dwell-times`, `POST /driver-wait-times`, `POST /checkpoints`

### Transportation — `/api/v1/transportation/transportation`

- Carriers: `POST/GET /carriers`, `GET/PUT /carriers/{carrier_id}`, `GET /carriers/{carrier_id}/compliance`
- Drivers: `POST/GET /drivers`, `GET/PUT /drivers/{driver_id}`, `GET /drivers/{driver_id}/hos`
- Shipments: `POST/GET /shipments`, `GET/PUT /shipments/{shipment_id}`, `POST /shipments/{shipment_id}/dispatch`, `POST /shipments/{shipment_id}/status`, `GET /shipments/{shipment_id}/costs`
- Routes: `POST/GET /routes`
- Load plans: `POST /load-plans`, `GET /shipments/{shipment_id}/load-plan`
- Freight: `POST /freight-charges`, `GET /shipments/{shipment_id}/freight-charges`

### Logistics — `/api/v1/logistics/logistics`

- `GET /correlation-dashboard`, `GET /dock-production-sync`, `POST /dock-appointments/{appointment_id}/sync`
- `GET /truck-asset-readiness`, `POST /load-quality`, `GET /load-quality-correlation`, `GET /delivery-efficiency`
- `POST /predict-detention`, `GET /detention-risk/upcoming`
- `GET /compliance/summary`, `POST /optimize-assignment`, `GET /liability/costs`

### Commands — `/api/v1/commands` (mostly admin)

- `POST /submit`, `GET /status/{command_id}`, `POST /cancel/{command_id}`
- `GET /asset/{asset_id}`, `GET /queue/status`, `POST /asset/{asset_id}/emergency-stop`

### OEE — `/api/v1/oee`

- `GET /current/{asset_id}`, `GET /historical/{asset_id}`, `GET /dashboard/summary`, `GET /losses/{asset_id}`

### Kanban — `/api/v1/kanban`

- `GET /board`, `POST /board/view`
- Tasks: `GET/POST /tasks`, `GET/PUT/DELETE /tasks/{task_id}`
- `POST /tasks/{task_id}/move`, `approve`, `start`, `complete`
- Comments: `GET/POST /tasks/{task_id}/comments`
- Timers: `POST /tasks/{task_id}/timer/start`, `POST /.../stop`, `GET /tasks/{task_id}/time-logs`
- `GET /metrics`, `GET /workload`
- Rules: `GET/POST /rules`, `PUT /rules/{rule_id}`, `POST /rules/{rule_id}/test`, `GET /rules/premade`, `DELETE /rules/{rule_id}`

### Registries — `/api/v1/registries`

- Registries CRUD, items CRUD, correlations CRUD, scoring endpoints (see `registries.py`; many routes use **admin** dependency—check before use on mobile).

### WebSocket

- `WS /ws`

### Health / metrics — mounted at **root** (no `/api/v1` prefix on `health.router`)

- `GET /health/live`, `/health/ready`, `/health/startup`, `/metrics`
- Admin: `POST /admin/collectors/{collector_id}/restart`, `POST /admin/assets/{asset_id}/maintenance`, `POST /admin/database/vacuum`, `GET /admin/system/status`

---

## 9. CORS and mobile builds

`backend/app/main.py` CORS `allow_origins` lists local web dev hosts. **Native apps** do not send an Origin header like browsers; for **Capacitor / WebView** builds you may need to add your `capacitor://` or `ionic://` origin, or proxy through your own backend. Adjust CORS when you introduce a hybrid shell.

---

## 10. Summary table — screen → primary endpoints

| Screen | Primary endpoints |
|--------|-------------------|
| Login | `POST /api/v1/auth/login`, then `GET /api/v1/auth/me` |
| Home | `GET /api/v1/auth/me`, `GET /api/v1/kanban/metrics`, `GET /api/v1/alarms/active`, `GET /api/v1/dashboard/overview`, optional `GET /kanban/board`, `GET /yard/yard/trailers` |
| Tasks list | `GET /api/v1/kanban/board` or `GET /api/v1/kanban/tasks` |
| Task detail | `GET /api/v1/kanban/tasks/{id}`, `GET /comments`, `POST /start`, `POST /complete`, `POST /comments` |
| Alerts list | `GET /api/v1/alarms/`, `GET /api/v1/alarms/active` |
| Alert detail | `GET /api/v1/alarms/{id}`, `POST /acknowledge`, `POST /clear` |
| Assets list | `GET /api/v1/assets/`, `GET /types/`, yard/TMS lists as needed |
| Asset detail | `GET /api/v1/assets/{id}`, `/status`, `GET /telemetry/.../latest`, `GET /oee/current/{id}`, alarms by `asset_id` |
| More / profile | `GET /api/v1/auth/me` |
