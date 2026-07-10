import type { ApiError } from '../api/client';
import type {
  Alarm,
  Asset,
  AssetStatus,
  KanbanBoardPayload,
  KanbanMetrics,
  Task,
  TaskComment,
  TransportShipment,
  YardTrailer,
} from '../api/types';
import {
  activeAlarmsPayload,
  buildInitialDemoState,
  dashboardOverviewFromState,
  DemoState,
  metricsFromState,
} from './buildInitialState';
import { COL, DEMO_ORG_ID } from './constants';

function isoDaysFromNow(days: number): string {
  return new Date(Date.now() + days * 86400000).toISOString();
}

const DEMO_TRANSPORT_SHIPMENTS: TransportShipment[] = [
  {
    id: 'ssssssss-0001-4000-8000-000000000001',
    organization_id: DEMO_ORG_ID,
    shipment_number: 'SHP-2024-0001',
    pro_number: 'PO-78234',
    status: 'in_transit',
    origin: { city: 'Chicago' },
    destination: { city: 'Los Angeles' },
    scheduled_delivery: isoDaysFromNow(1),
  },
  {
    id: 'ssssssss-0002-4000-8000-000000000001',
    organization_id: DEMO_ORG_ID,
    shipment_number: 'SHP-2024-0002',
    pro_number: 'PO-78235',
    status: 'in_transit',
    origin: { city: 'Denver' },
    destination: { city: 'Dallas' },
    scheduled_delivery: isoDaysFromNow(0),
  },
  {
    id: 'ssssssss-0003-4000-8000-000000000001',
    organization_id: DEMO_ORG_ID,
    shipment_number: 'SHP-2024-0003',
    pro_number: 'PO-78236',
    status: 'planned',
    origin: { city: 'Houston' },
    destination: { city: 'Atlanta' },
    scheduled_delivery: isoDaysFromNow(3),
  },
];

let state: DemoState | null = null;

function ensure(): DemoState {
  if (!state) {
    state = buildInitialDemoState();
  }
  return state;
}

function clone<T>(x: T): T {
  return JSON.parse(JSON.stringify(x)) as T;
}

function colType(s: DemoState, columnId: string): string {
  return s.columns.find((c) => c.id === columnId)?.column_type ?? '';
}

function refreshColumnCounts(s: DemoState) {
  for (const c of s.columns) {
    c.task_count = s.tasks.filter((t) => t.column_id === c.id).length;
  }
}

export function resetDemoStateForTests() {
  state = null;
}

export function applyDemoLiveTick() {
  const s = ensure();
  s.liveTick += 1;
  const i = s.liveTick;
  if (s.assets.length) {
    const a = s.assets[i % s.assets.length];
    a.last_seen = new Date().toISOString();
  }
  const tr = s.trailers.find((t) => t.id === 'dddddddd-0002-4000-8000-000000000001');
  if (tr) {
    tr.status = i % 2 === 0 ? 'yard' : 'checked_in';
    tr.yard_location = tr.status === 'yard' ? 'Row C slot 4' : 'Gate B staging';
  }
  const flap = s.alarms.find((a) => a.id === 'eeeeeeee-0002-4000-8000-000000000001');
  if (flap && flap.is_active) {
    flap.message = `Dock door 7 sensor oscillating (chattering) · live ${i % 10 === 0 ? '(spike)' : '(nominal)'}`;
  }
}

export function demoGetBoard(): KanbanBoardPayload {
  const s = ensure();
  return { columns: clone(s.columns), tasks: clone(s.tasks) };
}

export function demoGetMetrics(): KanbanMetrics {
  return metricsFromState(ensure());
}

export function demoGetTransportShipments(): TransportShipment[] {
  return clone(DEMO_TRANSPORT_SHIPMENTS);
}

export function demoGetDashboardOverview(_orgId?: string) {
  return clone(dashboardOverviewFromState(ensure()));
}

export function demoGetActiveAlarms(_orgId?: string) {
  return clone(activeAlarmsPayload(ensure()));
}

export function demoGetAlarms(filter: {
  is_active?: boolean;
  acknowledged?: boolean;
  limit?: number;
}): Alarm[] {
  const s = ensure();
  let rows = clone(s.alarms);
  if (filter.is_active !== undefined) {
    rows = rows.filter((a) => a.is_active === filter.is_active);
  }
  if (filter.acknowledged !== undefined) {
    rows = rows.filter((a) => a.is_acknowledged === filter.acknowledged);
  }
  const lim = filter.limit ?? 200;
  rows.sort((a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime());
  return rows.slice(0, lim);
}

export function demoGetAlarm(id: string): Alarm {
  const a = ensure().alarms.find((x) => x.id === id);
  if (!a) {
    const err: ApiError = { status: 404, message: 'Alarm not found' };
    throw err;
  }
  return clone(a);
}

export function demoAckAlarm(id: string, comment?: string | null): Alarm {
  const s = ensure();
  const a = s.alarms.find((x) => x.id === id);
  if (!a) {
    const err: ApiError = { status: 404, message: 'Alarm not found' };
    throw err;
  }
  a.is_acknowledged = true;
  a.acknowledged_at = new Date().toISOString();
  a.acknowledged_comment = comment ?? null;
  return clone(a);
}

export function demoClearAlarm(id: string): Alarm {
  const s = ensure();
  const a = s.alarms.find((x) => x.id === id);
  if (!a) {
    const err: ApiError = { status: 404, message: 'Alarm not found' };
    throw err;
  }
  a.is_active = false;
  a.cleared_at = new Date().toISOString();
  return clone(a);
}

export function demoGetAssets(orgId?: string): Asset[] {
  const s = ensure();
  if (orgId != null && orgId !== DEMO_ORG_ID) {
    return [];
  }
  return clone(s.assets);
}

export function demoGetAsset(id: string): Asset {
  const a = ensure().assets.find((x) => x.id === id);
  if (!a) {
    const err: ApiError = { status: 404, message: 'Asset not found' };
    throw err;
  }
  return clone(a);
}

export function demoGetAssetStatus(id: string): AssetStatus {
  const a = demoGetAsset(id);
  return {
    asset_id: a.id,
    name: a.name,
    current_packml_state: a.current_packml_state,
    is_active: a.is_active,
    last_seen: a.last_seen,
  };
}

export function demoUpdateAsset(
  id: string,
  patch: Partial<{ name: string; current_packml_state: string; is_active: boolean }>
): Asset {
  const s = ensure();
  const a = s.assets.find((x) => x.id === id);
  if (!a) {
    const err: ApiError = { status: 404, message: 'Asset not found' };
    throw err;
  }
  Object.assign(a, patch);
  a.last_seen = new Date().toISOString();
  return clone(a);
}

export function demoGetTrailers(): YardTrailer[] {
  return clone(ensure().trailers);
}

export function demoGetTrailer(id: string): YardTrailer {
  const t = ensure().trailers.find((x) => x.id === id);
  if (!t) {
    const err: ApiError = { status: 404, message: 'Trailer not found' };
    throw err;
  }
  return clone(t);
}

export function demoUpdateTrailer(
  id: string,
  patch: Partial<{ status: string; yard_location: string | null }>
): YardTrailer {
  const s = ensure();
  const t = s.trailers.find((x) => x.id === id);
  if (!t) {
    const err: ApiError = { status: 404, message: 'Trailer not found' };
    throw err;
  }
  Object.assign(t, patch);
  return clone(t);
}

export function demoGetTask(id: string): Task {
  const t = ensure().tasks.find((x) => x.id === id);
  if (!t) {
    const err: ApiError = { status: 404, message: 'Task not found' };
    throw err;
  }
  return clone(t);
}

export function demoGetComments(taskId: string): TaskComment[] {
  return clone(ensure().commentsByTaskId[taskId] ?? []);
}

export function demoAddComment(taskId: string, content: string): TaskComment {
  const s = ensure();
  if (!s.tasks.some((t) => t.id === taskId)) {
    const err: ApiError = { status: 404, message: 'Task not found' };
    throw err;
  }
  const list = s.commentsByTaskId[taskId] ?? (s.commentsByTaskId[taskId] = []);
  const cm: TaskComment = {
    id: `nnnnnnnn-${Date.now().toString(16).slice(-12)}-4000-8000-000000000001`,
    content,
    comment_type: 'comment',
    created_at: new Date().toISOString(),
  };
  list.push(cm);
  return clone(cm);
}

export function demoApproveTask(id: string, action: 'approve' | 'reject', reason?: string | null): Task {
  const s = ensure();
  const t = s.tasks.find((x) => x.id === id);
  if (!t) {
    const err: ApiError = { status: 404, message: 'Task not found' };
    throw err;
  }
  if (action === 'reject') {
    t.approval_status = 'rejected';
    t.updated_at = new Date().toISOString();
    refreshColumnCounts(s);
    return clone(t);
  }
  t.approval_status = 'approved';
  t.updated_at = new Date().toISOString();
  refreshColumnCounts(s);
  return clone(t);
}

export function demoStartTask(id: string): Task {
  const s = ensure();
  const t = s.tasks.find((x) => x.id === id);
  if (!t) {
    const err: ApiError = { status: 404, message: 'Task not found' };
    throw err;
  }
  t.column_id = COL.inProgress;
  t.status = 'in_progress';
  t.updated_at = new Date().toISOString();
  refreshColumnCounts(s);
  return clone(t);
}

export function demoCompleteTask(id: string): Task {
  const s = ensure();
  const t = s.tasks.find((x) => x.id === id);
  if (!t) {
    const err: ApiError = { status: 404, message: 'Task not found' };
    throw err;
  }
  t.column_id = COL.done;
  t.status = 'done';
  t.completed_at = new Date().toISOString();
  t.updated_at = t.completed_at;
  refreshColumnCounts(s);
  return clone(t);
}

export function demoMoveTask(id: string, target_column_id: string): Task {
  const s = ensure();
  const t = s.tasks.find((x) => x.id === id);
  if (!t) {
    const err: ApiError = { status: 404, message: 'Task not found' };
    throw err;
  }
  const typ = colType(s, target_column_id);
  t.column_id = target_column_id;
  if (typ === 'done') {
    t.status = 'done';
    t.completed_at = new Date().toISOString();
  } else if (typ === 'in_progress' || typ === 'review') {
    t.status = typ === 'review' ? 'review' : 'in_progress';
    t.completed_at = null;
  } else {
    t.status = 'open';
    t.completed_at = null;
  }
  t.updated_at = new Date().toISOString();
  refreshColumnCounts(s);
  return clone(t);
}
