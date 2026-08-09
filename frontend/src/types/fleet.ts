export type AgentReleaseStatus = 'draft' | 'published' | 'yanked';
export type AgentRolloutStatus =
  | 'pending'
  | 'paused'
  | 'running'
  | 'completed'
  | 'cancelled'
  | 'rolled_back'
  | 'failed';
export type AgentRolloutTargetStatus =
  | 'pending'
  | 'updating'
  | 'success'
  | 'failed'
  | 'rolled_back'
  | 'cancelled'
  | 'skipped';

export type FleetTargetMode = 'all' | 'assets' | 'cohort';
export type FleetCohortField =
  | 'tag'
  | 'group'
  | 'site_id'
  | 'workcell_id'
  | 'collector_type'
  | 'asset_type_id'
  | 'asset_category'
  | 'active'
  | 'heartbeat_age_seconds'
  | 'agent_id'
  | 'agent_version';
export type FleetCohortOperator =
  | 'any'
  | 'all'
  | 'eq'
  | 'ne'
  | 'in'
  | 'lt'
  | 'lte'
  | 'gt'
  | 'gte';

export interface FleetCohortPredicate {
  field: FleetCohortField;
  operator: FleetCohortOperator;
  value: string | number | boolean | string[];
}

export type FleetCohortQuery =
  | FleetCohortPredicate
  | { all_of: FleetCohortQuery[] }
  | { any_of: FleetCohortQuery[] };

export type FleetTargetSelector =
  | { all: true }
  | { asset_ids: string[] }
  | { cohort_id: string }
  | { query: FleetCohortQuery };

export interface FleetNamedResource {
  id: string;
  key: string;
  name: string;
  description: string | null;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export type FleetSite = FleetNamedResource;

export interface FleetTag extends FleetNamedResource {
  color: string | null;
}

export type FleetGroup = FleetNamedResource;

export interface FleetWorkcell {
  id: string;
  name: string;
  description: string | null;
  location: string | null;
  site_id: string | null;
  site_name: string | null;
}

export interface FleetCohort {
  id: string;
  name: string;
  description: string | null;
  query_version: number;
  query: FleetCohortQuery;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface FleetMembershipLabel {
  id: string;
  key: string;
  name: string;
}

export interface FleetInventoryAsset {
  id: string;
  name: string;
  is_active: boolean;
  agent_id: string | null;
  agent_version: string | null;
  last_heartbeat: string | null;
  workcell_id: string;
  workcell_name: string;
  site_id: string | null;
  site_name: string | null;
  asset_type_id: string;
  asset_type_name: string;
  asset_category: string | null;
  collector_types: string[];
  tags: FleetMembershipLabel[];
  groups: FleetMembershipLabel[];
}

export interface FleetInventoryResponse {
  assets: FleetInventoryAsset[];
}

export interface FleetResolvedAsset {
  asset_id: string;
  name: string;
  agent_id: string | null;
  agent_version: string | null;
  workcell_id: string;
  workcell_name: string;
  site_id: string | null;
  site_name: string | null;
  asset_type_id: string;
  asset_type_name: string;
  asset_category: string | null;
  collector_types: string[];
  tags: FleetMembershipLabel[];
  groups: FleetMembershipLabel[];
}

export interface FleetResolvedAgent {
  agent_key: string;
  agent_id: string | null;
  route_asset_id: string;
  asset_ids: string[];
  assets: FleetResolvedAsset[];
}

export interface FleetExcludedAsset {
  asset_id: string;
  name: string;
  reason: string;
}

export interface FleetTargetWarning {
  code: string;
  message: string;
  agent_id?: string | null;
  site_ids?: string[];
  [key: string]: unknown;
}

export interface FleetTargetPreview {
  id: string;
  release_id: string;
  selector: FleetTargetSelector;
  asset_ids: string[];
  agents: FleetResolvedAgent[];
  excluded_assets: FleetExcludedAsset[];
  warnings: FleetTargetWarning[];
  membership_hash: string;
  asset_count: number;
  agent_count: number;
  created_by: string;
  expires_at: string;
  created_at: string | null;
  expired: boolean;
}

export interface FleetNamedCreate {
  name: string;
  key?: string;
  description?: string;
}

export interface FleetNamedUpdate {
  name?: string;
  key?: string;
  description?: string | null;
  is_active?: boolean;
}

export interface FleetTagCreate extends FleetNamedCreate {
  color?: string;
}

export interface FleetTagUpdate extends FleetNamedUpdate {
  color?: string | null;
}

export interface FleetCohortCreate {
  name: string;
  description?: string;
  query: FleetCohortQuery;
}

export interface FleetCohortUpdate {
  name?: string;
  description?: string | null;
  query?: FleetCohortQuery;
  is_active?: boolean;
}

export interface FleetBulkTagAssignment {
  tag_id: string;
  asset_ids: string[];
  operation: 'add' | 'remove';
}

export interface FleetBulkAssignmentResult {
  asset_id: string;
  status: 'added' | 'removed' | 'unchanged' | 'error';
  error?: string;
}

export interface FleetBulkTagAssignmentResponse {
  tag_id: string;
  operation: 'add' | 'remove';
  changed_count: number;
  results: FleetBulkAssignmentResult[];
}

export interface FleetGroupMembershipRequest {
  group_id: string;
  asset_ids: string[];
  operation: 'add' | 'remove';
}

export interface FleetGroupMembershipResponse {
  group_id: string;
  operation: 'add' | 'remove';
  changed_count: number;
}

export interface FleetTargetPreviewCreate {
  release_id: string;
  selector: FleetTargetSelector;
  ttl_seconds?: number;
}

export interface AgentVersionDistributionItem {
  agent_version: string;
  asset_count: number;
  agent_count: number;
  latest_heartbeat: string | null;
}

export interface AgentVersionDistributionResponse {
  items: AgentVersionDistributionItem[];
}

export type AgentRemoteOperationAction =
  | 'agent_fetch_logs'
  | 'agent_diagnostics'
  | 'collector_restart'
  | 'agent_effective_config';

export type AgentRemoteOperationStatus =
  | 'pending'
  | 'executing'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'timeout';

export interface AgentRemoteOperationSubmission {
  command_id: string;
  status: AgentRemoteOperationStatus;
  action: AgentRemoteOperationAction;
  asset_id: string;
  agent_id: string;
  status_url: string;
}

export interface AgentRemoteLogEntry {
  timestamp: string;
  level: 'debug' | 'info' | 'warning' | 'error' | 'critical';
  event: string;
  fields: Record<string, unknown>;
}

export interface AgentRemoteLogsResult {
  schema_version: 1;
  action: 'agent_fetch_logs';
  agent_id: string;
  generated_at: string;
  entries: AgentRemoteLogEntry[];
  returned_count: number;
  available_count: number;
  truncated: boolean;
  redacted_fields: number;
}

export interface AgentRemoteDiagnosticsResult {
  schema_version: 1;
  action: 'agent_diagnostics';
  agent_id: string;
  generated_at: string;
  overall_status: 'healthy' | 'degraded';
  agent: Record<string, unknown>;
  buffer: Record<string, unknown>;
  transport: Record<string, unknown>;
  disk: Record<string, unknown>;
  clock: Record<string, unknown>;
  collectors: Record<string, unknown>;
  warnings: string[];
  truncated: boolean;
}

export interface AgentRemoteRestartResult {
  schema_version: 1;
  action: 'collector_restart';
  agent_id: string;
  generated_at: string;
  collector_asset_id: string;
  ready: boolean;
  duration_ms: number;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
}

export interface AgentRemoteConfigResult {
  schema_version: 1;
  action: 'agent_effective_config';
  agent_id: string;
  generated_at: string;
  config_hash: string;
  effective_config: Record<string, unknown>;
  redacted_fields: number;
  omitted_collectors: number;
  truncated: boolean;
}

export interface AgentRemoteErrorResult {
  schema_version: 1;
  action: AgentRemoteOperationAction;
  error_code: string;
  message: string;
}

export type AgentRemoteOperationResult =
  | AgentRemoteLogsResult
  | AgentRemoteDiagnosticsResult
  | AgentRemoteRestartResult
  | AgentRemoteConfigResult
  | AgentRemoteErrorResult;

export interface AgentRemoteOperationCommand
  extends AgentRemoteOperationSubmission {
  issued_at: string | null;
  executed_at: string | null;
  completed_at: string | null;
  result: AgentRemoteOperationResult | null;
  error: string | null;
}

export interface SubmitAgentRemoteOperation {
  assetId: string;
  action: AgentRemoteOperationAction;
  payload?: {
    schema_version: 1;
    limit?: number;
    since?: string;
    levels?: Array<'debug' | 'info' | 'warning' | 'error' | 'critical'>;
    readiness_timeout_seconds?: number;
  };
}

export interface AgentRelease {
  id: string;
  organization_id: string;
  version: string;
  channel: string;
  image_tag: string;
  checksum_sha256: string;
  signature_ed25519: string;
  signing_key_id: string;
  release_notes: string | null;
  status: AgentReleaseStatus;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  bundle_url?: string | null;
}

export interface AgentReleaseCreate {
  version: string;
  channel: string;
  image_tag: string;
  config_bundle: string;
  bundle_encoding: 'text' | 'base64';
  release_notes?: string;
}

export interface AgentRolloutTarget {
  id: string;
  asset_id: string;
  agent_id?: string | null;
  route_asset_id?: string | null;
  site_id?: string | null;
  wave_index: number;
  status: AgentRolloutTargetStatus;
  current_version: string | null;
  attempts: number;
  command_id?: string | null;
  rollback_command_id?: string | null;
  failure_reason?: string | null;
  dispatched_at?: string | null;
  completed_at?: string | null;
  last_event_at: string | null;
}

export interface AgentRolloutEvent {
  id: string;
  event_type: string;
  asset_id: string | null;
  detail: Record<string, unknown>;
  created_at: string | null;
}

export interface AgentRollout {
  id: string;
  organization_id: string;
  release_id: string;
  name: string;
  target_selector: FleetTargetSelector;
  strategy: Record<string, unknown>;
  status: AgentRolloutStatus;
  target_preview_id?: string | null;
  target_membership_hash?: string | null;
  scheduled_start_at?: string | null;
  enforce_maintenance_windows: boolean;
  pause_reason?: 'manual' | 'maintenance_window' | null;
  next_eligible_at?: string | null;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  targets: AgentRolloutTarget[];
  events: AgentRolloutEvent[];
}

export interface AgentRolloutCreate {
  name: string;
  release_id: string;
  target_selector: FleetTargetSelector;
  preview_id: string;
  membership_hash: string;
  strategy: Record<string, unknown>;
  scheduled_start_at?: string;
  enforce_maintenance_windows?: boolean;
}

export type MaintenanceWindowWeekday = 0 | 1 | 2 | 3 | 4 | 5 | 6;

export interface MaintenanceWindow {
  id: string;
  organization_id: string;
  site_id: string | null;
  site_name: string | null;
  name: string;
  timezone: string;
  weekdays: MaintenanceWindowWeekday[];
  local_start_time: string;
  local_end_time: string;
  overnight: boolean;
  enabled: boolean;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MaintenanceWindowCreate {
  name: string;
  site_id: string | null;
  timezone: string;
  weekdays: MaintenanceWindowWeekday[];
  local_start_time: string;
  local_end_time: string;
  enabled?: boolean;
}

export type MaintenanceWindowUpdate = Partial<MaintenanceWindowCreate>;

export interface MaintenanceWindowPreviewRequest {
  site_ids: Array<string | null>;
  at?: string;
  horizon_days?: number;
}

export interface MaintenanceWindowOccurrence {
  start_at: string;
  end_at: string;
}

export interface MaintenanceWindowPreview {
  at: string;
  site_ids: Array<string | null>;
  is_open: boolean;
  next_eligible_at: string | null;
  current_closes_at: string | null;
  missing_scopes: string[];
  effective_window_ids: string[];
  occurrences: MaintenanceWindowOccurrence[];
}
