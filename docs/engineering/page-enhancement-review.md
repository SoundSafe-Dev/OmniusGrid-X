# Page-by-page enhancement review

Started 2026-08-13 on `hamad/converged-pre-main`. The mandate: enhance features and
functionality of the entire system, page by page. This document is the working plan — the
same contract as the sweeps documents: items land here measured, leave here shipped, and a
row nobody can act on is a row that should not have been written.

**Method.** Every page surveyed for: what it shows and from where; what actions it offers;
what a real operator would reach for and not find; what the backend already serves that the
page ignores (the cheapest enhancements are wires, not features); and what renders
placeholder data. Enhancement items are ranked by operator value, not by effort.

**Lanes.** Kanban = Harsh; engines + correlation-AI = HARSH; RAG = htreinen; OTA/fleet
rollouts = Hridyansh; intake = Alex. Cross-lane items are surveyed and recorded here but
implemented only with authorisation; in-lane items ship directly.

## Page inventory (37 pages, ~33 routes)

| Route | Page | Lane |
|---|---|---|
| `/` | Dashboard | platform |
| `/assets`, `/assets/:id` | Assets, AssetDetail | platform |
| `/alarms`, `/alarms/rules` | Alarms, AlarmRules | platform |
| `/oee` | OEE | platform |
| `/kanban` | Kanban | Harsh |
| `/shop-floor` | ShopFloor | platform |
| `/activations` | Activations | platform |
| `/engines/{tactical,strategic,mlops,cloud}` | four engine pages | HARSH |
| `/analytics/{telemetry,health,maintenance}` | TelemetryCharts, AssetHealth, PredictiveMaintenance | platform |
| `/predictive/{rul,historian}` | PredictiveRUL, Historian | platform |
| `/fleet`, `/fleet/organization` | FleetOverview, OrganizationTree | platform |
| `/logistics/{yard,transportation}` | YardManagement, TransportationManagement | platform |
| `/erp` | ERPIntegrations | platform |
| `/compliance` | ComplianceAssistant | platform |
| `/nlp` | CorrelationAIPane | HARSH |
| `/intake` | IntakeInbox | Alex |
| `/admin/*` | Users, Collectors, SystemHealth, Settings, Notifications, ExportDeliveries, ErrorTriage(+Detail), Fleet(+RolloutDetail) | platform / OTA |
| `/login`, `/accept-invite` | Login, AcceptInvitation | platform |

## Carried-in items (recorded before this review, still open)

- **Scheduled-exports management UI** — `/admin/export-deliveries` shows attempts; nothing
  lets a user see or edit the schedules behind them (old FS-571).
- **Decision history on StrategicEngine** — `get_recommendation_history` exists
  engine-side with no route; the page renders `—` (old FS-567; HARSH lane, route is small).
- **Geofence events on the authenticated `/ws`** — both geofencing clients poll because
  `/ws/geofencing` / `/ws/fleet-tracking` do not exist (old FS-570).
- **`useAcknowledgeAllAlarms` exists and is dead** — two panels hand-roll fire-and-forget
  loops instead (old FS-572).
- **"No patterns for this vendor" third state on ERP correlation** — a QuickBooks user
  sees a successful sync and an empty correlation list (old FS-562), pending the five
  vendor transformers (FS-557..561, L-sized each).
- **Frontend coverage `include` widening + kanban/common/fleet component tests**
  (old FS-541..547) — quality substrate for any page work in those areas.

## Per-page findings

### Logistics, fleet, compliance (surveyed)

**YardManagement** (`/logistics/yard`). Five tabs + 8 stat tiles over `yardApi`. Writes
bypass TanStack mutations (raw async + refetch); Refresh refetches trailers only; stats
are computed from the *filtered page*, so the tiles understate the yard; no
polling/websocket; detention rate schedule is hardcoded ($0/$50/$75). Backend surface the
page never calls: appointment create/start/complete, door create/update, `/checkpoints`,
`/driver-wait-times`, and **all of `logistics_correlation.py`** (detention-risk,
predict-detention, dock-production-sync, optimize-assignment, liability/costs — zero
frontend callers).
→ E1 Wire detention-risk/predict-detention into the Detention tab (see before charges
accrue, not after). E2 Appointment lifecycle + door management actions (backend already
supports; tabs are read-only). E3 Make the yard live: poll/subscribe and refetch all five
queries on Refresh.

**TransportationManagement** (`/logistics/transportation`). Eight tabs + persistent map.
Known sharp edge: a **hardcoded `gt-device-002`** poll every 30s drives the "Live Fleet
Location (GeoTab)" card — one fabricated device, and unlike the fleet-summary card it
carries **no `simulated` warning**. No shipment creation despite `createShipment` +
`POST /shipments`; carriers/vehicles/routes read-only against a fully writable API
(carrier/driver/vehicle/route POST+PUT, load-plans, freight-charges,
`carriers/{id}/compliance`, `drivers/{id}/hos` all uncalled); stats from one page of a
paginated endpoint; no export of HOS/expiration compliance tables.
→ E1 Shipment create + carrier/vehicle/driver edit forms. E2 Fix or delete the
fabricated device card; label simulated either way. E3 Server-side filter + pagination +
CSV export on shipments and compliance tables.

**FleetOverview** (`/fleet`). Tiles + workcell cards, all inert. `limit: 500` cap makes
`onlineCount` and per-workcell counts silently wrong past 500 assets while the
"Total Assets" tile uses `total` — the two tiles can disagree today. `orgs?.[0]` assumes
single-org. No drill-down, no polling.
→ E1 Workcell cards navigate to a filtered asset list (the counts are the page's whole
value and are dead ends). E2 Per-workcell PackML breakdown instead of one org-wide
Execute count. E3 Server-side aggregation past the 500 cap + polling.

**OrganizationTree** (`/fleet/organization`). Expand/collapse only; asset nodes have no
click handler; one failed query blanks the whole tree; no search; no status roll-up on
parents; dead `site` icon branch.
→ E1 Search/filter + alarmed-child roll-up badges on workcell nodes. E2 Asset nodes
click through to detail. E3 Per-query loading/error so the skeleton survives one failure.

**ComplianceAssistant** (`/compliance`). Grounded Q&A with citation jumps — solid core.
Backend `rag.py` exposes `/documents` list, `/ingest`, delete, `/health`; none surfaced,
so "nothing matches" is indistinguishable from "not loaded". No export of an answer with
citations (the natural audit artifact). Suggestions hardcoded. No corpus scoping filter.
→ E1 Document-library view over `GET /rag/documents` (makes the gap actionable).
E2 Export/print answer + citations for audit evidence. E3 Framework/doc-type retrieval
scoping. *(RAG lane: htreinen — record, don't ship without authorisation.)*

**Cross-cutting (this slice):** core writes skip `useMutation`/cache invalidation
everywhere except Compliance; `logistics_correlation.py` is entirely unreachable from the
UI; the simulated-telematics warning exists on one GeoTab card and not the other.

### Core operations (surveyed)

**Dashboard** (`/`). Six KPI tiles + five charts, per-widget states done properly. Gaps:
trend queries have no `refetchInterval` (only alarm-keyed WS invalidation), so charts go
stale; active-alarm feed is read-only despite `useAcknowledgeAlarm` existing; range
selector doesn't feed `getFleetOEE(hours)`; no workcell scoping though the data is there.
→ E1 Real OEE tile fed by the range selector. E2 Inline Acknowledge on the alarm widget.
E3 `refetchInterval` on the three trend queries.

**Assets** (`/assets`). Card grid, prev/next only. Backend `list_assets` accepts
`workcell_id`, `asset_type`, `is_active` — the page sends **none**; no search, no sort.
Admin CRUD (`POST/PUT/DELETE /assets/`) has zero UI. Status dot implies liveness
(`animate-pulse`) with no polling.
→ E1 Filter bar wired to the three existing params + name search. E2 Admin create/edit/
deactivate against the existing endpoints. E3 Poll or WS-subscribe PackML state.

**AssetDetail** (`/assets/:id`). Live telemetry + commands, solid. Missing: an active-
alarms panel scoped to the asset (`alarmsApi.list({assetId})` exists), an OEE card
(`getAssetOEE` + per-asset PDF export exist), a metric picker and date-range control for
the history chart (API takes them), and maintenance mode is shown but not settable.
→ E1 Asset-scoped alarms panel with inline acknowledge. E2 OEE breakdown card + PDF.
E3 Metric picker + date range on history.

**Alarms** (`/alarms`). THE LARGEST WIRE-GAP OF THE SURVEY: `alarmsApi.list` supports
`assetId`, `isActive`, `severity`, `acknowledged`, `startTime`, `endTime` — the page
passes **only `skip`**. `clear()` and `acknowledgeAll()` exist with no buttons.
Acknowledge sends no note though the API takes one. And the backend defaults to last-24h
when no range is sent, so the "Total Alarms" tile is a 24h count labelled as all-history.
→ E1 Filter bar (severity/active/acknowledged/asset/date) — also fixes the mislabelled
total. E2 Acknowledge-all (scoped to current filter) + per-row Clear. E3 Ack-note field +
asset links on rows.

**AlarmRules** (`/alarms/rules`). Full CRUD — most complete page. But the form has NO
scope controls: `assetId`/`assetTypeId`/`workcellId` sit in `EMPTY_FORM`, no input sets
them, so every rule is org-wide and backend `_validate_targets` is unreachable from the
UI. No scope column, no pagination, no rule preview.
→ E1 Scope selectors (asset/type/workcell) on the form. E2 Scope column + metric filter +
pagination. E3 "Test against recent telemetry" preview.

**OEE** (`/oee`). One query; expanding rows fetches per-asset breakdown. An ENTIRE ROUTER
(`api/oee.py`) goes unused: `/oee/losses/{id}` (Pareto — the most requested OEE view),
`/oee/historical/{id}` (hourly/daily/shift up to 168h), `/oee/current/{id}`. No time
range, no sorting, export hardcodes 24h.
→ E1 Loss Pareto in the expanded row via `/oee/losses`. E2 Time-range + aggregation
selector feeding fleet query, export, and historical. E3 Sortable columns (worst-first) +
per-asset PDF.

**ShopFloor** (`/shop-floor`). Operator terminal, careful error handling. But `assetId`
on Machine Down and Issue Part are **free-text UUID inputs** — unusable on a real floor;
open-downtime id lives in local state only, so a reload strands an in-progress downtime;
`listPartIssues` exists uncalled (no history of what was just submitted); ledger has no
pagination and ignores the `?status=` param.
→ E1 Asset picker replacing the free-text UUIDs. E2 Server-fetched open downtime (survives
reload, any operator can end it). E3 Recent-activity lists from the unused endpoints.

### Analytics, predictive, engines, kanban (surveyed)

**TelemetryCharts** (`/analytics/telemetry`). Hardcoded to `assets[0]` — no asset or
metric picker though `GET /telemetry/{id}/metrics` exists. A **phantom `oee` bar**: the
chart declares `dataKey="oee"` but rows only carry `availability`, so the legend entry
renders nothing, always. Annotations aren't persisted; `hasMore` warns with no paging.
→ E1 Asset + metric multi-select from the metrics endpoint. E2 Delete the phantom bar or
source real OEE. E3 Paging/downsampling for 30d ranges.

**AssetHealth** (`/analytics/health`). Read-only, no links, client-side buckets over a
hard 500-item page (larger fleets silently miscounted), and "health" is only current
PackML state — ignores `health_index.py`, `rul.py`, alarms entirely.
→ E1 Join RUL/health-index scores. E2 Rows link to asset + active alarms. E3 Truncation
notice + server-side counts.

**PredictiveMaintenance** (`/analytics/maintenance`). A *vehicle servicing* list that
duplicates the route-name of the richer RUL page — confusing overlap. 30-day window
hardcoded, nothing links anywhere, no overdue-first sort.
→ E1 "Create task" posting to kanban from a due service. E2 Horizon + overdue-first.
E3 Merge with RUL page or rename to Fleet Servicing.

**PredictiveRUL** (`/predictive/rul`). Best page of the set. Gaps: no paging despite
honest truncation flag; `hours` fixed at 24; nothing converts a critical RUL into work —
the recommended window is text the operator re-keys elsewhere.
→ E1 "Schedule maintenance"/"Create task" from a row. E2 Server-side risk ordering +
paging so critical can't fall off page one. E3 Per-asset driver history drill-down.

**Historian** (`/predictive/historian`). Metric is a **free-text input defaulting to
"temperature"** — operators must guess names though the metrics endpoint exists. Single
series only; no custom date range; silent 500-row table cap.
→ E1 Metric dropdown from `/telemetry/{id}/metrics` on asset select. E2 Multi-series
compare. E3 Custom start/end + load-more honouring `hasMore`.

**Engines (all four)** — HARSH's lane, recorded. THE CROSS-CUTTING CATCH:
`X-Engine-Not-Running` is defined (`core/pagination.py:120`) and set by
`api/engines.py:175,221`, and **no frontend code reads it** — since the loops
historically never start, every engine page renders confident status for a dead loop.
Per-page: Tactical never calls `/tactical/infer`; **Strategic's history route now EXISTS
(`engines.py:202`) but `api/engines.ts` has no client** — the History card still says
"not available from the API" and the Approved/Rejected tiles render `—`; reject reason is
hardcoded `'User rejected'` and operatorId is the literal `'current-user'`; MLOps
deploy/rollback have NO confirmation dialog and all of `model_monitoring.py`
(drift/performance) has no frontend client at all; CloudGateway's queue depth is a bare
number with no trend or last-sync.
→ E1 Read `X-Engine-Not-Running` in the API client → "loop stopped" banner on all four
pages. E2 `getRecommendationHistory` client + fill the two `—` tiles (closes old FS-567).
E3 Deploy/rollback confirm modal; drift panel from model_monitoring.

**Kanban** (`/kanban`) — Harsh's lane, recorded. Store still branches on `USE_MOCK` in
production code. Large unused surface: `/tasks/{id}/comments`, `/timer/start|stop`,
`/time-logs`, `/workload`, `/rules` (+premade +test), `/board/view` — no discussion
thread, no time tracking, no workload view, no rules UI.
→ E1 Comments thread in TaskDetailModal. E2 Task timer + actual-vs-estimate.
E3 Admin rules screen with premade templates and dry-run test.

**Activations** (`/activations`). Cleanest page surveyed. Gaps: no retry for a `failed`
posting; `activation.task` is text with no deep-link to the kanban card or source
session; fixed limit 100 with a reported-but-unpageable `truncated`; domain-routing
config invisible (client exists, no screen).
→ E1 Retry failed postings. E2 Deep-links task↔kanban and back to session. E3 Age sort +
paging + a routing view explaining "not routed here".

### ERP, intake, NLP, admin, auth (surveyed)

**ERPIntegrations** (`/erp`). Solid core. No edit/pause though `updateIntegration` +
`PUT /{id}` + `is_active` exist; field-mapping CRUD clients exist with no UI; webhook
config never fetched; no delete confirmation; server `correlation_reason` discarded for a
hardcoded sentence; Correlations tab global, not per-integration.
→ E1 Edit/enable-disable dialog on the existing PUT. E2 Field-mapping panel + webhook
config. E3 Show server correlation_reason; filter correlations by integration.

**IntakeInbox** (`/intake`) — Alex's lane; two genuine bugs, mechanical. **Dead button**:
"View Results" has no `onClick`. **Non-reactive filter**: `statusFilter` is passed to the
API but the effect has `[]` deps, so the dropdown only appears to filter. Also no polling
for `analyzing` rows; `GET /intake/{id}` and `POST /intake/cross-correlate` unused
anywhere.
→ E1 Fix the filter refetch + wire View Results to a detail drawer on `GET /intake/{id}`.
E2 Cross-correlate as a multi-select action. E3 TanStack migration + polling.

**CorrelationAIPane** (`/nlp`) — HARSH's lane. No session rename/archive/delete (ended
sessions vanish); transcript capped at 100 with no load-older; auto-integrate outcomes
unreported.
→ E1 Session management. E2 Transcript paging. E3 Auto-integrate outcome reporting.

**Admin/Users**. No server-side search/role filter (hard 200-cap with advice to "narrow"
and no control to narrow); no user detail (audit/sessions/API keys backends exist); no
invite-link copy for failed email delivery.
→ E1 Search + role/status filters. E2 User detail drawer w/ audit log. E3 Copy-invite-link
+ expiry display.

**Admin/Collectors**. Read-only; `GET /edge/fleet/{agent_id}` never called; cert expiry
hidden in a tooltip; dead-letter backlog uninspectable; no cross-links.
→ E1 Per-agent detail on the existing endpoint. E2 Badged, sortable cert/DLQ columns.
E3 Cross-link agent ↔ assets ↔ rollouts.

**Admin/SystemHealth**. Good news: it iterates `Object.entries(health.checks)`, so all
nine new FS-693..705 subsystems render automatically. The gap: the per-component
`details` payload (consecutive-failure counts, running flags, error strings) is
**fetched and discarded**, as are top-level `status`/`checked_at`. `/health/db|redis|
kafka` and `/admin/system/status` + vacuum unused.
→ E1 Expand tiles with their `details` (the FS-693 arc's counters become visible).
E2 Overall status + checked_at banner. E3 Admin actions panel.

**Admin/Settings**. Five settings; timezone is free-text; whole backends (SSO,
data-residency, feature flags, API keys, GDPR) have no admin surface; no unsaved-changes
guard.
→ E1 IANA timezone picker. E2 Tabbed settings exposing SSO/retention/API keys. E3 Dirty
guard + reset.

**Admin/Notifications**. No edit (delete-and-recreate); `enabled` badge with no toggle
(needs backend PATCH); Send Test hardcodes `warning` severity so critical-only
subscriptions always "match 0"; log unfilterable.
→ E1 Edit + toggle (with PATCH). E2 Severity selector on test. E3 Log filter/paging +
resend.

**Admin/ExportDeliveries** — **THE BIGGEST HOLE OF THE SURVEY**: backend has full
schedule CRUD (`GET/POST /exports/schedules`, `GET/PUT/DELETE /exports/schedules/{id}`)
and template CRUD (`/exports/definitions`, `/exports/templates` + item routes) — **nine
endpoints, zero frontend references**. Users see a schedule failed and cannot see what it
is, who receives it, when it next runs, or pause it. (Old FS-571, confirmed and larger.)
→ E1 `/admin/export-schedules` CRUD page. E2 Link delivery→schedule + retry. E3 Status
filter/paging + template manager.

**Admin/ErrorTriage(+Detail)**. List: no bulk status ops, no regressions-only filter, no
total count. Detail: PATCH carries status only — no resolution note or assignee; no
occurrence list; no mute for known-noisy fingerprints.
→ E1 Bulk status changes. E2 Note+assignee on PATCH. E3 Mute/snooze rules.

**Admin/Fleet(+RolloutDetail)** — Hridyansh's OTA lane. Pause/resume exist in `useFleet`
but are only wired on the detail page; rollback (`rollback_command_id`) displayed, never
triggerable; silent 6-target slice; detail renders 1000-row fleets unpaginated with raw
JSON event cells.
→ E1 Pause/resume in the table + rollback action. E2 Target filter/paging. E3 Readable
event detail + agent links.

**Login / AcceptInvitation**. **SSO entirely absent** though `sso.py` exposes
status/me/callback — no conditional "Sign in with SSO". Field says Username, store sends
email. Invitation flow: bare length check, no display-name capture, no re-request on
expiry.
→ E1 Conditional SSO button off `GET /sso/status`. E2 Field/label honesty + lockout copy.
E3 Invite: strength meter, name capture, re-request.

**User workspace** (`/` for non-admins). A literal placeholder — the whole non-admin
experience is a dead end. Not a page gap; a missing surface.
→ E1 Route operators into a scoped subset (Alarms ack, ShopFloor, their Kanban tasks).
E2 Mobile-first floor view. E3 Shift handover notes.

## Synthesis — the shape of the whole system

1. **The frontend is roughly one release behind its own backend.** The dominant gap class
   is not missing features but UNCALLED ENDPOINTS: export schedules/templates (9), all of
   `logistics_correlation.py`, all of `model_monitoring.py`, OEE losses/historical,
   alarm filters, asset filters, kanban comments/timers/rules, SSO, intake detail/
   cross-correlate, RAG document library. The cheapest large wins are wires.
2. **Read-only where the backend is writable**: transportation, yard, assets,
   notifications, ERP edit — operators can observe and not act.
3. **Liveness asymmetry**: some pages poll well; others (yard, fleet, assets, health
   buckets) are static snapshots with liveness-implying UI.
4. **Honesty debt is small but real**: phantom OEE bar, mislabelled 24h alarm total,
   unlabelled fabricated GeoTab card, System Health discarding the details it fetches,
   IntakeInbox's inert filter and dead button.
5. **Two structural absences**: the operator (non-admin) surface, and admin surfaces for
   whole backends (SSO, API keys, feature flags, retention).

## Execution order (my lane first; ranked value ÷ effort)

| # | Item | Pages | Size |
|---|---|---|---|
| P1 | ✅ SHIPPED — Alarms filter bar + ack-all + clear + ack-note + honest total | Alarms | M |
| P2 | ✅ SHIPPED — SystemHealth details + overall banner + neutral 'disabled' badges | SystemHealth | S |
| P3 | ✅ SHIPPED — IntakeInbox reactive filter + View Results wired to GET /intake/{id} | Intake | S |
| P4 | ✅ SHIPPED — EngineStoppedBanner on all four pages; history client + tiles + real reject reason/operator | engines/* | S–M |
| P5 | ✅ SHIPPED — ShopFloor asset picker; open downtime is server truth (new GET /downtime/open) | ShopFloor | M |
| P6 | ✅ SHIPPED — Assets filter bar: debounced name search (new backend param) + workcell/type/active | Assets | S |
| P7 | ✅ SHIPPED — AssetDetail: asset-scoped alarms with inline ack + OEE card (panel extracted from pages/OEE) | AssetDetail | M |
| P8 | ✅ SHIPPED — loss Pareto from the uncalled /api/v1/oee router + one time range driving table, panels and export | OEE | M |
| P9 | ✅ SHIPPED — /admin/export-schedules: list, create-paused, pause/resume, delete + both export pages added to the nav | new page | L |
| P10 | ✅ SHIPPED — AlarmRules: asset/type/workcell scope selectors + a Scope column | AlarmRules | M |
| P11 | ✅ SHIPPED — Notifications: new PATCH route, inline edit, enable/disable toggle, test-severity selector | Notifications | M |
| P12 | ✅ SHIPPED — Collectors: `dropped` finally rendered, cert-expiry badges, worst-first order. (Per-agent detail NOT built: `GET /edge/fleet/{id}` returns the same shape as a list row, so a drill-in would show identical data.) | Collectors | M |
| P13 | TelemetryCharts asset/metric pickers; Historian metric dropdown | analytics | M |
| P14 | ◐ PARTIAL — trend queries now poll (were frozen at mount under polling KPIs). OEE tile + inline ack still open. | Dashboard | S |
| — | Cross-lane (recorded, need authorisation): kanban comments/timers/rules, engine test-fire, NLP session mgmt, OTA table actions, RAG library, ERP mapping UI, operator workspace | — | — |

