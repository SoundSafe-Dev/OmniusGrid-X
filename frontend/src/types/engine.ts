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

export interface TacticalEngineStatus {
  modelLoaded: boolean;
  modelVersion: string;
  maxLatencyTargetMs: number;
  safetyThresholds: Record<string, number>;
  lastInferenceAt?: string;
  averageLatencyMs?: number;
  totalInferences?: number;
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

export interface MLOpsStatus {
  currentModel: string;
  cachedModels: string[];
  pollIntervalSeconds: number;
  lastPollAt?: string;
  lastDeploymentAt?: string;
  deploymentHistory: ModelDeployment[];
}

export interface ModelDeployment {
  version: string;
  deployedAt: string;
  rolledBackAt?: string;
  performanceMetrics?: Record<string, number>;
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
