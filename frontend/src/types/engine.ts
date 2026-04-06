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
  expectedImpact: {
    oeeImprovement?: number;
    costSavings?: number;
    timeSavings?: number;
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

export interface CloudGatewayStatus {
  connected: boolean;
  lastConnectedAt?: string;
  lastDisconnectedAt?: string;
  connectionUptimeSeconds: number;
  mTlsCertificateExpiry?: string;
  egressStats: {
    totalBytesSent: number;
    totalBytesCompressed: number;
    compressionRatio: number;
    averageBandwidthKbps: number;
    queueDepth: number;
  };
  lastSyncAt?: string;
}

export interface InferenceRequest {
  assetId: string;
  featureVector: Record<string, number>;
}
