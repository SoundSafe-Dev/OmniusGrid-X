import * as demo from '../demo/store';
import { useDemoDataLayer } from './dataLayer';
import { apiFetch } from './client';
import type {
  ActiveAlarmsPayload,
  Alarm,
  Asset,
  AssetStatus,
  DashboardOverview,
  KanbanBoardPayload,
  KanbanMetrics,
  MeResponse,
  Task,
  TaskComment,
  TokenResponse,
  TransportShipment,
  YardTrailer,
} from './types';

export async function loginRequest(email: string, password: string): Promise<TokenResponse> {
  return apiFetch<TokenResponse>('/api/v1/auth/login', {
    method: 'POST',
    auth: false,
    form: { username: email, password },
  });
}

export async function fetchMe(accessToken?: string): Promise<MeResponse> {
  if (accessToken !== undefined) {
    return apiFetch<MeResponse>('/api/v1/auth/me', { auth: true, authToken: accessToken });
  }
  return apiFetch<MeResponse>('/api/v1/auth/me');
}

export async function fetchKanbanBoard(): Promise<KanbanBoardPayload> {
  if (useDemoDataLayer()) return demo.demoGetBoard();
  const data = await apiFetch<Record<string, unknown>>('/api/v1/kanban/board');
  const rawTasks = (data.tasks as Task[]) ?? [];
  const tasks = rawTasks.map((t) => ({
    ...t,
    approval_status: t.approval_status ?? 'pending',
    description: t.description ?? null,
    asset_id: t.asset_id ?? null,
    assigned_at: t.assigned_at ?? null,
    due_date: t.due_date ?? null,
    completed_at: t.completed_at ?? null,
  }));
  return {
    columns: (data.columns as KanbanBoardPayload['columns']) ?? [],
    tasks,
  };
}

export async function fetchKanbanMetrics(): Promise<KanbanMetrics> {
  if (useDemoDataLayer()) return demo.demoGetMetrics();
  return apiFetch<KanbanMetrics>('/api/v1/kanban/metrics');
}

function normalizeDashboardOverview(raw: Record<string, unknown>): DashboardOverview {
  const num = (v: unknown, d = 0) => (typeof v === 'number' && Number.isFinite(v) ? v : d);
  const rec = (v: unknown): Record<string, number> =>
    v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, number>) : {};
  return {
    total_assets: num(raw.total_assets ?? raw.totalAssets),
    active_assets: num(raw.active_assets ?? raw.activeAssets),
    assets_by_state: rec(raw.assets_by_state ?? raw.assetsByState),
    active_alarms: num(raw.active_alarms ?? raw.activeAlarms),
    critical_alarms: num(raw.critical_alarms ?? raw.criticalAlarms),
  };
}

export async function fetchDashboardOverview(orgId?: string): Promise<DashboardOverview> {
  if (useDemoDataLayer()) return demo.demoGetDashboardOverview(orgId);
  const q = orgId ? `?organization_id=${encodeURIComponent(orgId)}` : '';
  const raw = await apiFetch<Record<string, unknown>>(`/api/v1/dashboard/overview${q}`);
  return normalizeDashboardOverview(raw);
}

export async function fetchActiveAlarms(orgId?: string): Promise<ActiveAlarmsPayload> {
  if (useDemoDataLayer()) return demo.demoGetActiveAlarms(orgId);
  const q = orgId ? `?organization_id=${encodeURIComponent(orgId)}` : '';
  return apiFetch<ActiveAlarmsPayload>(`/api/v1/alarms/active${q}`);
}

export type AlarmFilter = {
  is_active?: boolean;
  acknowledged?: boolean;
  limit?: number;
};

export async function fetchAlarms(filter: AlarmFilter = {}): Promise<Alarm[]> {
  if (useDemoDataLayer()) return demo.demoGetAlarms(filter);
  const params = new URLSearchParams();
  if (filter.is_active !== undefined) params.set('is_active', String(filter.is_active));
  if (filter.acknowledged !== undefined) params.set('acknowledged', String(filter.acknowledged));
  params.set('limit', String(filter.limit ?? 200));
  const q = params.toString();
  return apiFetch<Alarm[]>(`/api/v1/alarms/?${q}`);
}

export async function fetchAlarm(id: string): Promise<Alarm> {
  if (useDemoDataLayer()) return demo.demoGetAlarm(id);
  return apiFetch<Alarm>(`/api/v1/alarms/${id}`);
}

export async function acknowledgeAlarm(id: string, comment?: string): Promise<Alarm> {
  if (useDemoDataLayer()) return demo.demoAckAlarm(id, comment);
  return apiFetch<Alarm>(`/api/v1/alarms/${id}/acknowledge`, {
    method: 'POST',
    json: { comment: comment ?? null },
  });
}

export async function clearAlarm(id: string): Promise<Alarm> {
  if (useDemoDataLayer()) return demo.demoClearAlarm(id);
  return apiFetch<Alarm>(`/api/v1/alarms/${id}/clear`, { method: 'POST' });
}

export async function fetchTask(id: string): Promise<Task> {
  if (useDemoDataLayer()) return demo.demoGetTask(id);
  return apiFetch<Task>(`/api/v1/kanban/tasks/${id}`);
}

export async function startTask(id: string): Promise<Task> {
  if (useDemoDataLayer()) return demo.demoStartTask(id);
  return apiFetch<Task>(`/api/v1/kanban/tasks/${id}/start`, { method: 'POST', json: {} });
}

export async function completeTask(id: string): Promise<Task> {
  if (useDemoDataLayer()) return demo.demoCompleteTask(id);
  return apiFetch<Task>(`/api/v1/kanban/tasks/${id}/complete`, { method: 'POST', json: {} });
}

export async function approveTask(id: string, action: 'approve' | 'reject', reason?: string): Promise<Task> {
  if (useDemoDataLayer()) return demo.demoApproveTask(id, action, reason);
  return apiFetch<Task>(`/api/v1/kanban/tasks/${id}/approve`, {
    method: 'POST',
    json: { action, reason: reason ?? null },
  });
}

export async function moveTask(id: string, target_column_id: string, position?: number): Promise<Task> {
  if (useDemoDataLayer()) return demo.demoMoveTask(id, target_column_id);
  const body: Record<string, unknown> = { target_column_id };
  if (position !== undefined) body.position = position;
  return apiFetch<Task>(`/api/v1/kanban/tasks/${id}/move`, {
    method: 'POST',
    json: body,
  });
}

export async function fetchTaskComments(taskId: string): Promise<TaskComment[]> {
  if (useDemoDataLayer()) return demo.demoGetComments(taskId);
  return apiFetch<TaskComment[]>(`/api/v1/kanban/tasks/${taskId}/comments`);
}

export async function addTaskComment(taskId: string, content: string): Promise<TaskComment> {
  if (useDemoDataLayer()) return demo.demoAddComment(taskId, content);
  return apiFetch<TaskComment>(`/api/v1/kanban/tasks/${taskId}/comments`, {
    method: 'POST',
    json: { content, comment_type: 'comment' },
  });
}

/** List assets */
export async function fetchAssetsList(orgId?: string): Promise<Asset[]> {
  if (useDemoDataLayer()) return demo.demoGetAssets(orgId);
  const path =
    orgId != null
      ? `/api/v1/assets/?organization_id=${encodeURIComponent(orgId)}`
      : '/api/v1/assets/';
  return apiFetch<Asset[]>(path);
}

export async function fetchAsset(id: string): Promise<Asset> {
  if (useDemoDataLayer()) return demo.demoGetAsset(id);
  return apiFetch<Asset>(`/api/v1/assets/${id}`);
}

export async function fetchAssetStatus(id: string): Promise<AssetStatus> {
  if (useDemoDataLayer()) return demo.demoGetAssetStatus(id);
  return apiFetch<AssetStatus>(`/api/v1/assets/${id}/status`);
}

export async function updateAsset(
  id: string,
  patch: Partial<{ name: string; current_packml_state: string; is_active: boolean }>
): Promise<Asset> {
  if (useDemoDataLayer()) return demo.demoUpdateAsset(id, patch);
  return apiFetch<Asset>(`/api/v1/assets/${id}`, { method: 'PUT', json: patch });
}

export async function fetchTransportShipments(organizationId: string): Promise<TransportShipment[]> {
  if (useDemoDataLayer()) return demo.demoGetTransportShipments();
  const q = `?organization_id=${encodeURIComponent(organizationId.trim())}`;
  try {
    return await apiFetch<TransportShipment[]>(`/api/v1/transportation/shipments${q}`);
  } catch {
    return [];
  }
}

export async function fetchYardTrailers(organizationId?: string | null): Promise<YardTrailer[]> {
  if (useDemoDataLayer()) return demo.demoGetTrailers();
  if (!organizationId?.trim()) {
    return [];
  }
  const q = `?organization_id=${encodeURIComponent(organizationId.trim())}`;
  return apiFetch<YardTrailer[]>(`/api/v1/yard/yard/trailers${q}`);
}

export async function fetchYardTrailer(id: string): Promise<YardTrailer> {
  if (useDemoDataLayer()) return demo.demoGetTrailer(id);
  return apiFetch<YardTrailer>(`/api/v1/yard/yard/trailers/${encodeURIComponent(id)}`);
}

export async function updateYardTrailer(
  id: string,
  patch: Partial<{ status: string; yard_location: string | null }>
): Promise<YardTrailer> {
  if (useDemoDataLayer()) return demo.demoUpdateTrailer(id, patch);
  return apiFetch<YardTrailer>(`/api/v1/yard/yard/trailers/${encodeURIComponent(id)}`, {
    method: 'PUT',
    json: patch,
  });
}
