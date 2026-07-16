import { FC } from 'react';
import { useQuery, useMutation, useQueryClient } from 'react-query';
import { Lightbulb, CheckCircle, XCircle, Clock, Zap, TrendingUp } from 'lucide-react';
import { Card, Badge, Button, SkeletonCard } from '../../components';
import { enginesApi, twinOptimizerApi, defaultOptimizeRequest } from '../../api';
import type { OptimizeRecommendation } from '../../api/twinOptimizer';
import { StrategicRecommendation } from '../../types';
import { formatDateTime, formatPercentage } from '../../utils';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';

export const StrategicEngine: FC = () => {
  const queryClient = useQueryClient();

  const { data: recommendations, isLoading } = useQuery(
    'strategic-recommendations',
    () => enginesApi.getStrategicRecommendations(),
    { refetchInterval: 30000 }
  );

  const approveMutation = useMutation(
    ({ recId, operatorId }: { recId: string; operatorId: string }) =>
      enginesApi.approveRecommendation(recId, operatorId),
    {
      onSuccess: () => queryClient.invalidateQueries('strategic-recommendations'),
    }
  );

  const rejectMutation = useMutation(
    ({ recId, operatorId, reason }: { recId: string; operatorId: string; reason: string }) =>
      enginesApi.rejectRecommendation(recId, operatorId, reason),
    {
      onSuccess: () => queryClient.invalidateQueries('strategic-recommendations'),
    }
  );

  // Digital-twin what-if optimizer (FS-84): POST a default two-candidate
  // scenario and render the ranked recommendations the twin returns.
  const optimizeMutation = useMutation(() =>
    twinOptimizerApi.optimize(defaultOptimizeRequest())
  );
  const optimizeResult = optimizeMutation.data;

  if (isLoading) {
    return (
      <div className="space-y-6">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={6} />
      </div>
    );
  }

  const pendingRecs = recommendations?.filter((r) => r.status === 'pending') || [];
  const historyRecs = recommendations?.filter((r) => r.status !== 'pending') || [];

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <Lightbulb className="w-8 h-8 text-opsgrid-primary" />
                <div>
                  <p className="text-2xl font-bold">{pendingRecs.length}</p>
                  <p className="text-sm text-opsgrid-text-secondary">Pending Recommendations</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Recommendations awaiting your review</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <CheckCircle className="w-8 h-8 text-status-running" />
                <div>
                  <p className="text-2xl font-bold">
                    {historyRecs.filter((r) => r.status === 'approved').length}
                  </p>
                  <p className="text-sm text-opsgrid-text-secondary">Approved</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Total approved recommendations</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <XCircle className="w-8 h-8 text-status-alarm" />
                <div>
                  <p className="text-2xl font-bold">
                    {historyRecs.filter((r) => r.status === 'rejected').length}
                  </p>
                  <p className="text-sm text-opsgrid-text-secondary">Rejected</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Total rejected recommendations</TooltipContent>
        </Tooltip>
      </div>

      {/* Digital-Twin What-If Optimizer */}
      <Card
        title="Digital-Twin Optimizer"
        subtitle="Run a Monte-Carlo what-if simulation across the active fleet"
        action={
          <Button
            variant="primary"
            size="sm"
            loading={optimizeMutation.isLoading}
            disabled={optimizeMutation.isLoading}
            onClick={() => optimizeMutation.mutate()}
          >
            <Zap size={16} className="mr-1" />
            Run Optimization
          </Button>
        }
      >
        {optimizeMutation.isError ? (
          <p className="text-status-alarm text-sm py-4">
            Optimization failed. Please try again.
          </p>
        ) : !optimizeResult ? (
          <p className="text-opsgrid-text-secondary text-center py-8">
            Run an optimization to rank beneficial what-if actions for your fleet.
          </p>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
              <div className="p-3 bg-opsgrid-bg rounded-lg">
                <p className="text-opsgrid-text-secondary">Objective</p>
                <p className="font-medium">{optimizeResult.objective}</p>
              </div>
              <div className="p-3 bg-opsgrid-bg rounded-lg">
                <p className="text-opsgrid-text-secondary">Candidates Evaluated</p>
                <p className="font-medium">{optimizeResult.evaluatedCandidates}</p>
              </div>
            </div>
            {optimizeResult.recommendations.length === 0 ? (
              <p className="text-opsgrid-text-secondary text-sm">
                No candidate cleared the improvement threshold.
              </p>
            ) : (
              optimizeResult.recommendations.map((rec) => (
                <OptimizeResultCard key={rec.recommendationId} rec={rec} />
              ))
            )}
          </div>
        )}
      </Card>

      {/* Pending Recommendations */}
      <Card title="Pending Recommendations" subtitle="Cloud-derived optimization suggestions">
        <div className="space-y-4">
          {pendingRecs.length === 0 ? (
            <p className="text-opsgrid-text-secondary text-center py-8">
              No pending recommendations. Check back later for new suggestions from the cloud strategic engine.
            </p>
          ) : (
            pendingRecs.map((rec) => (
              <RecommendationCard
                key={rec.recommendationId}
                rec={rec}
                onApprove={() => approveMutation.mutate({ recId: rec.recommendationId, operatorId: 'current-user' })}
                onReject={() => rejectMutation.mutate({ recId: rec.recommendationId, operatorId: 'current-user', reason: 'User rejected' })}
              />
            ))
          )}
        </div>
      </Card>

      {/* History */}
      <Card title="History" subtitle="Past recommendations and outcomes">
        <div className="divide-y divide-opsgrid-border">
          {historyRecs.slice(0, 10).map((rec) => (
            <div key={rec.recommendationId} className="py-3 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Badge
                  variant={
                    rec.status === 'approved'
                      ? 'success'
                      : rec.status === 'rejected'
                      ? 'error'
                      : 'neutral'
                  }
                  size="sm"
                >
                  {rec.status}
                </Badge>
                <span className="text-sm">{rec.description}</span>
              </div>
              <span className="text-sm text-opsgrid-text-secondary">
                {rec.approvedAt || rec.rejectedAt
                  ? formatDateTime(rec.approvedAt || rec.rejectedAt!)
                  : '—'}
              </span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};

const OptimizeResultCard: FC<{ rec: OptimizeRecommendation }> = ({ rec }) => {
  const impact = rec.expectedImpact;
  return (
    <div className="p-4 bg-opsgrid-bg rounded-lg border border-opsgrid-border">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <Badge variant="info" size="sm">
            Rank {rec.rank}
          </Badge>
          <span className="font-medium">{rec.name}</span>
        </div>
        <Badge variant="info" size="sm">
          {formatPercentage(rec.confidence)} confidence
        </Badge>
      </div>

      <p className="text-sm text-opsgrid-text-secondary mb-3">{rec.description}</p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-2 p-3 bg-opsgrid-panel rounded">
        <div>
          <p className="text-xs text-opsgrid-text-secondary">Throughput</p>
          <p className="font-medium text-status-running flex items-center gap-1">
            <TrendingUp size={14} />+{impact.throughputImprovementPercent.toFixed(1)}%
          </p>
        </div>
        <div>
          <p className="text-xs text-opsgrid-text-secondary">Added Parts</p>
          <p className="font-medium">{Math.round(impact.throughputDeltaParts)}</p>
        </div>
        <div>
          <p className="text-xs text-opsgrid-text-secondary">Downtime Saved</p>
          <p className="font-medium">{impact.downtimeReductionHours.toFixed(1)}h</p>
        </div>
        <div>
          <p className="text-xs text-opsgrid-text-secondary">Availability</p>
          <p className="font-medium">+{impact.availabilityImprovementPoints.toFixed(1)} pts</p>
        </div>
      </div>

      <div className="flex items-center gap-2 text-xs text-opsgrid-text-secondary">
        <Badge variant="neutral" size="sm">{rec.recommendationType}</Badge>
        <span>Basis: {rec.simulationBasis}</span>
        {rec.requiresApproval && <span>· Requires approval</span>}
      </div>
    </div>
  );
};

interface RecommendationCardProps {
  rec: StrategicRecommendation;
  onApprove: () => void;
  onReject: () => void;
}

const RecommendationCard: FC<RecommendationCardProps> = ({ rec, onApprove, onReject }) => {
  return (
    <div className="p-4 bg-opsgrid-bg rounded-lg border border-opsgrid-border">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <Badge variant={rec.priority >= 8 ? 'error' : rec.priority >= 5 ? 'warning' : 'info'} size="sm">
            Priority {rec.priority}/10
          </Badge>
          <span className="text-sm text-opsgrid-text-secondary flex items-center gap-1">
            <Clock size={14} />
            Valid until {new Date(rec.validUntil).toLocaleDateString()}
          </span>
        </div>
        <Badge variant="info" size="sm">
          {formatPercentage(rec.confidence)} confidence
        </Badge>
      </div>

      <p className="font-medium mb-2">{rec.description}</p>

      {rec.assetName && (
        <p className="text-sm text-opsgrid-text-secondary mb-3">Asset: {rec.assetName}</p>
      )}

      <div className="grid grid-cols-3 gap-4 mb-4 p-3 bg-opsgrid-panel rounded">
        {rec.expectedImpact.oeeImprovement !== undefined && (
          <div>
            <p className="text-xs text-opsgrid-text-secondary">OEE Impact</p>
            <p className="font-medium text-status-running">
              +{formatPercentage(rec.expectedImpact.oeeImprovement)}
            </p>
          </div>
        )}
        {rec.expectedImpact.costSavings !== undefined && (
          <div>
            <p className="text-xs text-opsgrid-text-secondary">Cost Savings</p>
            <p className="font-medium text-status-running">
              ${rec.expectedImpact.costSavings.toLocaleString()}
            </p>
          </div>
        )}
        {rec.expectedImpact.timeSavings !== undefined && (
          <div>
            <p className="text-xs text-opsgrid-text-secondary">Time Savings</p>
            <p className="font-medium text-status-running">
              {rec.expectedImpact.timeSavings}h
            </p>
          </div>
        )}
      </div>

      <div className="flex items-center gap-3">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="primary" size="sm" onClick={onApprove}>
              <CheckCircle size={16} className="mr-1" />
              Approve
            </Button>
          </TooltipTrigger>
          <TooltipContent>Approve this recommendation for implementation</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="secondary" size="sm" onClick={onReject}>
              <XCircle size={16} className="mr-1" />
              Reject
            </Button>
          </TooltipTrigger>
          <TooltipContent>Reject this recommendation</TooltipContent>
        </Tooltip>
      </div>
    </div>
  );
};
