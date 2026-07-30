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
  /** WAS `isInMaintenance`, a name the wire has never used. The column is
   *  `assets.maintenance_mode` (migration 053) and `/api/v1/assets` is registered on the
   *  casing seam, so it arrives as `maintenanceMode`. The old name was declared as a
   *  required boolean and populated only by the mock fixtures, so it was `undefined` on
   *  every real response — and until the field was added to `AssetResponse` the wire did
   *  not carry it under any name at all. */
  maintenanceMode: boolean;
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
  /** Renamed with the read side. NOTE: `PATCH /assets/{id}` does not accept this — the
   *  only writer is `POST /admin/assets/{id}/maintenance`, which is admin-gated for a
   *  reason (it suppresses engine control commands). Declared here so the shape matches
   *  `Asset`, not because sending it does anything. */
  maintenanceMode?: boolean;
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
