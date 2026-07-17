export type PackMLState = 
  | 'Idle'
  | 'Starting'
  | 'Execute'
  | 'Held'
  | 'Suspended'
  | 'Aborted'
  | 'Stopped'
  | 'Completing'
  | 'Complete'
  | 'Clearing'
  | 'Resetting'
  | 'Unholding'
  | 'Suspending'
  | 'Aborting'
  | 'Stopping';

export interface AssetType {
  id: string;
  name: string;
  category: string;
  vendor?: string;
  description?: string;
  capabilities?: string[];
  createdAt: string;
  updatedAt: string;
}

export interface Asset {
  id: string;
  name: string;
  assetTypeId: string;
  assetType?: AssetType;
  vendor?: string;
  model?: string;
  serialNumber?: string;
  organizationId?: string;
  workcellId?: string;
  workcell?: Workcell;
  currentPackmlState: PackMLState;
  isActive: boolean;
  isInMaintenance: boolean;
  lastSeen?: string;
  connectionConfig?: Record<string, any>;
  // Sensor taxonomy (migration 024): drives type-aware AssetDetail panes.
  sensorClass?: 'machinery' | 'audio' | 'video' | 'environmental' | 'generic';
  mediaConfig?: Record<string, any>;
  metadata?: Record<string, any>;
  createdAt: string;
  updatedAt: string;
}

export interface Workcell {
  id: string;
  name: string;
  description?: string;
  organizationId?: string;
  supervisorId?: string;
  location?: string;
  metadata?: Record<string, any>;
  createdAt: string;
  updatedAt: string;
}

export interface Organization {
  id: string;
  name: string;
  description?: string;
  parentId?: string;
  metadata?: Record<string, any>;
  createdAt: string;
  updatedAt: string;
}

export interface AssetCreate {
  name: string;
  assetTypeId: string;
  vendor?: string;
  model?: string;
  serialNumber?: string;
  organizationId?: string;
  workcellId?: string;
  connectionConfig?: Record<string, any>;
  metadata?: Record<string, any>;
}

export interface AssetUpdate {
  name?: string;
  vendor?: string;
  model?: string;
  serialNumber?: string;
  workcellId?: string;
  connectionConfig?: Record<string, any>;
  metadata?: Record<string, any>;
  isActive?: boolean;
  isInMaintenance?: boolean;
}

export interface AssetStatus {
  assetId: string;
  name: string;
  currentPackmlState: PackMLState;
  isActive: boolean;
  lastSeen?: string;
  connectionConfig?: Record<string, any>;
}

export interface PackMLStateTransition {
  id: string;
  assetId: string;
  state: PackMLState;
  previousState?: PackMLState;
  stateEnteredAt: string;
  stateExitedAt?: string;
  durationSeconds?: number;
  metadata?: Record<string, any>;
}
