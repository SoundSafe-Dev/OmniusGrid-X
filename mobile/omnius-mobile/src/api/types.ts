export type MeResponse = {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  organization_id: string | null;
  last_login: string | null;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
};

export type KanbanColumn = {
  id: string;
  board_id: string;
  name: string;
  position: number;
  column_type: string;
  color?: string;
  task_count?: number;
};

export type Task = {
  id: string;
  board_id: string;
  column_id: string;
  title: string;
  description: string | null;
  task_type: string;
  priority: string;
  status: string;
  approval_status: string;
  asset_id: string | null;
  assigned_at: string | null;
  due_date: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type KanbanBoardPayload = {
  columns: KanbanColumn[];
  tasks: Task[];
};

export type KanbanMetrics = {
  total_tasks: number;
  tasks_by_column: Record<string, number>;
  tasks_completed_today: number;
  tasks_awaiting_approval?: number;
};

export type Alarm = {
  id: string;
  asset_id: string;
  alarm_code: string;
  severity: string;
  message: string;
  description: string | null;
  is_active: boolean;
  is_acknowledged: boolean;
  occurred_at: string;
  acknowledged_at: string | null;
  acknowledged_comment: string | null;
  cleared_at: string | null;
};

export type ActiveAlarmsPayload = {
  count: number;
  alarms: Alarm[];
};

export type DashboardOverview = {
  total_assets: number;
  active_assets: number;
  assets_by_state: Record<string, number>;
  active_alarms: number;
  critical_alarms: number;
};

export type Asset = {
  id: string;
  name: string;
  organization_id: string;
  asset_type_id: string;
  current_packml_state: string;
  is_active: boolean;
  last_seen: string | null;
};

export type AssetStatus = {
  asset_id: string;
  name: string;
  current_packml_state: string;
  is_active: boolean;
  last_seen: string | null;
};

export type YardTrailer = {
  id: string;
  trailer_number: string;
  status: string;
  yard_location: string | null;
  organization_id: string;
};

/** Subset of TMS shipment row returned by `/api/v1/transportation/shipments`. */
export type TransportShipment = {
  id: string;
  organization_id: string;
  shipment_number: string;
  pro_number?: string | null;
  status: string;
  origin: Record<string, unknown>;
  destination: Record<string, unknown>;
  scheduled_delivery?: string | null;
  scheduled_pickup?: string | null;
};

export type TaskComment = {
  id: string;
  content: string;
  comment_type: string;
  created_at: string;
};
