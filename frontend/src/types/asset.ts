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

/** `AssetTypeResponse`, field for field (FS-439).
 *
 *  This declared FOUR fields `asset_types` does not have — `vendor`, `description`,
 *  `capabilities`, `updatedAt` — and MISSED four it does: `actionSpace`, `packmlConfig`,
 *  `sensorClass`, `telemetrySchema`. The response model matches its table exactly, so the
 *  divergence was entirely on this side.
 *
 *  The missing four are the interesting half. `actionSpace` and `packmlConfig` are what
 *  make an asset type mean anything operationally — which commands it accepts and which
 *  state machine it follows — and no screen could reach them through a type that did not
 *  admit they existed. */
export interface AssetType {
  id: string;
  name: string;
  category: string;
  sensorClass?: string | null;
  actionSpace?: Record<string, any> | null;
  packmlConfig?: Record<string, any> | null;
  telemetrySchema?: Record<string, any> | null;
  createdAt: string;
}

export interface Asset {
  id: string;
  name: string;
  assetTypeId: string;
  /** `assetType` and `workcell` are GONE (FS-439). Both were NESTED OBJECTS, and
   *  `AssetResponse` sends `asset_type_id` and `workcell_id` — ids, not expansions. No
   *  handler joins either, so a component reaching for `asset.assetType.name` would have
   *  read a property of `undefined`. Nothing did, which is why this was a trap rather than
   *  a crash. Resolve through the id, or add a join and declare what it sends. */
  vendor?: string;
  model?: string;
  serialNumber?: string;
  organizationId?: string;
  workcellId?: string;
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
  /** `metadata` is GONE (FS-439). `assets` has no such column — `connection_config`
   *  and `media_config` are the two config bags it does carry, and both are declared
   *  by name. A generic `metadata` beside them invites a caller to look for settings
   *  in a third place that does not exist. */
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
  // `metadata` was declared here and `POST /assets/` does not accept it, so it was
  // discarded in silence — Pydantic ignores unknown body fields (FS-423). The column is
  // `meta_data` and nothing on the create path sets it. Removed rather than aliased: a
  // write type that names a field the endpoint cannot apply is a promise the API does not
  // keep, and the next person to write an asset form would have believed it.
}

export interface AssetUpdate {
  name?: string;
  vendor?: string;
  model?: string;
  serialNumber?: string;
  connectionConfig?: Record<string, any>;
  isActive?: boolean;
  // THREE FIELDS REMOVED HERE (FS-423): `workcellId`, `metadata` and `maintenanceMode`.
  //
  // `PUT /assets/{id}` declares none of them, and Pydantic drops unknown body fields
  // silently — so setting any of them returned 200 with nothing changed. `maintenanceMode`
  // even carried a comment saying so: "PATCH /assets/{id} does not accept this ... declared
  // here so the shape matches `Asset`, not because sending it does anything." That is rule
  // 17 exactly — a limitation written into a comment is a finding waiting to be re-found.
  //
  // `AssetUpdate` is not `Asset`; it is the set of things an update can change. Matching
  // the read shape at the cost of naming three writes that do not happen is the wrong
  // trade, and no component constructed this type, so the traps were purely for whoever
  // came next.
  //
  // Maintenance mode has its own writer, admin-gated because it suppresses engine control
  // commands: `POST /api/v1/admin/assets/{id}/maintenance`.
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
