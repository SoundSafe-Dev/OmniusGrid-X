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

export interface AgentVersionDistributionItem {
  agent_version: string;
  asset_count: number;
  agent_count: number;
  latest_heartbeat: string | null;
}

export interface AgentVersionDistributionResponse {
  items: AgentVersionDistributionItem[];
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
  target_selector: Record<string, unknown>;
  strategy: Record<string, unknown>;
  status: AgentRolloutStatus;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  targets: AgentRolloutTarget[];
  events: AgentRolloutEvent[];
}

export interface AgentRolloutCreate {
  name: string;
  release_id: string;
  target_selector: {
    all?: boolean;
    asset_ids?: string[];
  };
  strategy: Record<string, unknown>;
}
