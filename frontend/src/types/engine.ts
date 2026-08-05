export interface TacticalDecision {
  assetId: string;
  actionType: string;
  parameters: Record<string, any>;
  confidence: number;
  latencyMs: number;
  modelVersion: string;
  reasoning?: string;
  timestamp: string;
}

/** EXACTLY what `GET /api/v1/engines/tactical/status` sends, verified against a running
 *  backend on 2026-08-01: `model_loaded`, `model_version`, `max_latency_target_ms`,
 *  `safety_thresholds`.
 *
 *  It also declared `lastInferenceAt`, `averageLatencyMs` and `totalInferences`, which no
 *  endpoint produces — and `mockApi` invented all three. Since the default dev experience
 *  is `VITE_USE_MOCK=true`, a pane built against them would show live latency and an
 *  inference count in development and render blank the moment it met the real API. That is
 *  not a hypothetical: it is what happened to the Decision History pane (FS-366), which was
 *  built on seven `StrategicRecommendation` fields the server never sends.
 *
 *  Removed rather than marked optional. An optional field that nothing can ever populate
 *  still reads as an invitation. */
export interface TacticalEngineStatus {
  modelLoaded: boolean;
  modelVersion: string;
  maxLatencyTargetMs: number;
  safetyThresholds: Record<string, number>;
}

export interface StrategicRecommendation {
  recommendationId: string;
  assetId?: string;
  assetName?: string;
  type: string;
  priority: number;
  description: string;
  /** FREE-FORM BY DESIGN, and the declared keys did not match the ones sent. The engine
   *  documents it as `{'oee_improvement': 0.05, 'cost_reduction': 1000}` and emits a different
   *  set per recommendation type — `cost_reduction`, `throughput_gain`, `rul_extension_days`.
   *  The type named `costSavings` (the key is `costReduction` after the casing seam) and
   *  `timeSavings` (produced by nothing), so of the three slots the panel rendered, two could
   *  never fill and the impacts that WERE sent had nowhere to go.
   *
   *  Only the two the panel formats specially are named; the rest arrive through the index
   *  signature and are rendered generically, which is what an open-ended dict requires. */
  expectedImpact: {
    /** A fraction, rendered as a percentage. */
    oeeImprovement?: number;
    /** Currency. */
    costReduction?: number;
    [key: string]: any;
  };
  confidence: number;
  /** Where this came from, and whether it came from anywhere at all (FS-434).
   *
   *  Neither field was declared and the API did not send them, so a recommendation arrived
   *  as a description, an impact and a confidence with no provenance whatsoever — and the
   *  demo seeds loaded under ALLOW_DEV_TOKEN carried a `simulationBasis` reading
   *  "Fleet OEE rollup + maintenance-window scheduler (14 days)" beside 0.88 confidence,
   *  describing a computation over the reader's own fleet that never happened.
   *
   *  `simulated` is optional because a server that predates the field sends nothing, and
   *  absent must not render as "simulated: false" — that would be the same lie by default. */
  simulated?: boolean;
  simulationBasis?: string;
  validUntil: string;
  requiresApproval: boolean;
  status: 'pending' | 'approved' | 'rejected' | 'expired' | 'implemented';
  createdAt: string;
  approvedAt?: string;
  approvedBy?: string;
  rejectedAt?: string;
  rejectedBy?: string;
  rejectionReason?: string;
}

/** EXACTLY what `GET /api/v1/engines/mlops/status` sends, verified against a running
 *  backend on 2026-08-01: `current_model`, `cached_models`, `poll_interval_seconds`.
 *
 *  `lastPollAt`, `lastDeploymentAt` and `deploymentHistory` are gone, along with the whole
 *  `ModelDeployment` interface they were the only use of. No endpoint produces any of them.
 *
 *  `deploymentHistory` was the dangerous one: declared **required**, so every consumer was
 *  entitled to `status.deploymentHistory.map(...)` without a guard, and at runtime it is
 *  `undefined`. TypeScript was actively vouching for a field the server has never sent.
 *
 *  `mockApi` supplied all three, including two fully-populated deployment records with
 *  rollback timestamps. The default dev experience is `VITE_USE_MOCK=true`, so a deployment
 *  history table would have looked complete in development and been empty — or thrown —
 *  against the real API. Same shape as FS-366 and as the eleven fields removed from
 *  `CloudGatewayStatus` below. */
export interface MLOpsStatus {
  currentModel: string;
  cachedModels: string[];
  pollIntervalSeconds: number;
}

/** What `/api/v1/engines/cloud/status` returns — `cloud_gateway.get_stats()`, four keys.
 *
 *  THIS INTERFACE DESCRIBED A DIFFERENT SERVICE. It declared `lastConnectedAt`,
 *  `lastDisconnectedAt`, `connectionUptimeSeconds`, `mTlsCertificateExpiry`, `lastSyncAt` and
 *  a nested `egressStats` of five more — eleven fields, none of them sent, all of them
 *  populated by the mock alone. Only `lastConnectedAt` was reported by the wire-vocabulary
 *  sweep; the rest are named by other things in the tree, so the global vocabulary credits
 *  them.
 *
 *  The page had already worked this out and declared its OWN local `CloudStatus` with the four
 *  real fields, under a comment saying the rest "is not sent, so we render strictly from what
 *  actually arrives". That was right, and it left the exported type wrong — so the api client
 *  still promised eleven fields and only the mock could deliver them. One type now, matching
 *  the wire.
 */
export interface CloudGatewayStatus {
  connected: boolean;
  queueSize: number;
  endpoint: string;
  mtlsEnabled: boolean;
}

export interface InferenceRequest {
  assetId: string;
  featureVector: Record<string, number>;
}
