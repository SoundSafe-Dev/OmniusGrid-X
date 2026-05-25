import { FC, useState } from 'react';
import { useQuery } from 'react-query';
import { Zap, Activity, Shield, Play, Pause } from 'lucide-react';
import { Card, Badge, Button, SkeletonCard } from '../../components';
import { enginesApi } from '../../api';
import { TacticalDecision } from '../../types';
import { formatDuration, formatNumber } from '../../utils';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';

export const TacticalEngine: FC = () => {
  const { data: status, isLoading } = useQuery(
    'tactical-status',
    () => enginesApi.getTacticalStatus(),
    { refetchInterval: 5000 }
  );

  const [decisions] = useState<TacticalDecision[]>([]);
  const [safetyEnabled, setSafetyEnabled] = useState(true);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={6} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-opsgrid-primary/20 rounded-lg">
                  <Zap className="w-5 h-5 text-opsgrid-primary" />
                </div>
                <div>
                  <p className="text-sm text-opsgrid-text-secondary">Model Status</p>
                  <Badge variant={status?.modelLoaded ? 'success' : 'error'} size="sm">
                    {status?.modelLoaded ? 'Loaded' : 'Not Loaded'}
                  </Badge>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Tactical AI model loading status</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-opsgrid-primary/20 rounded-lg">
                  <Activity className="w-5 h-5 text-opsgrid-primary" />
                </div>
                <div>
                  <p className="text-sm text-opsgrid-text-secondary">Model Version</p>
                  <p className="font-medium">{status?.modelVersion || 'N/A'}</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Current model version in use</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-opsgrid-primary/20 rounded-lg">
                  <Activity className="w-5 h-5 text-opsgrid-primary" />
                </div>
                <div>
                  <p className="text-sm text-opsgrid-text-secondary">Avg Latency</p>
                  <p className="font-medium">{formatNumber(status?.averageLatencyMs || 0)} ms</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Average inference latency in milliseconds</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-opsgrid-primary/20 rounded-lg">
                  <Activity className="w-5 h-5 text-opsgrid-primary" />
                </div>
                <div>
                  <p className="text-sm text-opsgrid-text-secondary">Total Inferences</p>
                  <p className="font-medium">{formatNumber(status?.totalInferences || 0)}</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Total number of inferences made</TooltipContent>
        </Tooltip>
      </div>

      {/* Controls */}
      <Card title="Safety Controls" subtitle="Manage automated decision-making">
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center justify-between p-4 bg-opsgrid-bg rounded-lg">
              <div className="flex items-center gap-3">
                <Shield className="w-5 h-5 text-opsgrid-primary" />
                <div>
                  <p className="font-medium">Safety Thresholds</p>
                  <p className="text-sm text-opsgrid-text-secondary">
                    Override automated actions with hard limits
                  </p>
                </div>
              </div>
              <Button
                variant={safetyEnabled ? 'primary' : 'secondary'}
                size="sm"
                onClick={() => setSafetyEnabled(!safetyEnabled)}
              >
                {safetyEnabled ? <Pause size={16} /> : <Play size={16} />}
                {safetyEnabled ? 'Enabled' : 'Disabled'}
              </Button>
            </div>
          </TooltipTrigger>
          <TooltipContent>Toggle safety threshold enforcement for automated decisions</TooltipContent>
        </Tooltip>
      </Card>

      {/* Recent Decisions */}
      <Card title="Recent Decisions" subtitle="Live inference outputs">
        <div className="space-y-2">
          {decisions.length === 0 ? (
            <p className="text-opsgrid-text-secondary text-center py-8">
              No recent decisions. Decisions will appear here when the engine makes automated adjustments.
            </p>
          ) : (
            decisions.map((decision) => (
              <div
                key={`${decision.assetId}-${decision.timestamp}`}
                className="flex items-center justify-between p-3 bg-opsgrid-bg rounded-lg"
              >
                <div className="flex items-center gap-3">
                  <Badge variant={decision.confidence > 0.8 ? 'success' : 'warning'} size="sm">
                    {(decision.confidence * 100).toFixed(0)}%
                  </Badge>
                  <div>
                    <p className="font-medium">{decision.actionType}</p>
                    <p className="text-sm text-opsgrid-text-secondary">
                      {decision.assetId} • {decision.latencyMs.toFixed(1)}ms
                    </p>
                  </div>
                </div>
                <span className="text-sm text-opsgrid-text-secondary">
                  {formatDuration((Date.now() - new Date(decision.timestamp).getTime()) / 1000)} ago
                </span>
              </div>
            ))
          )}
        </div>
      </Card>
    </div>
  );
};
