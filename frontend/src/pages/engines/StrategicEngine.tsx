import { FC } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Lightbulb, CheckCircle, XCircle, Clock, Zap, TrendingUp } from 'lucide-react';
import { Card, Badge, Button, SkeletonCard } from '../../components';
import { enginesApi, twinOptimizerApi, defaultOptimizeRequest } from '../../api';
import type { OptimizeRecommendation } from '../../api/twinOptimizer';
import { StrategicRecommendation } from '../../types';
import { formatDateTime, formatPercentage } from '../../utils';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';

export const StrategicEngine: FC = () => {
  const queryClient = useQueryClient();

  const { data: recommendations, isLoading, isError } = useQuery({
    queryKey: ['strategic-recommendations'],
    queryFn: () => enginesApi.getStrategicRecommendations(),
    refetchInterval: 30000,
  });

  const approveMutation = useMutation({
    mutationFn: ({ recId, operatorId }: { recId: string; operatorId: string }) =>
      enginesApi.approveRecommendation(recId, operatorId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['strategic-recommendations'] }),
  });

  const rejectMutation = useMutation({
    mutationFn: ({ recId, operatorId, reason }: { recId: string; operatorId: string; reason: string }) =>
      enginesApi.rejectRecommendation(recId, operatorId, reason),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['strategic-recommendations'] }),
  });

  const actionError = approveMutation.isError || rejectMutation.isError;

  // Digital-twin what-if optimizer (FS-84): POST a default two-candidate
  // scenario and render the ranked recommendations the twin returns.
  const optimizeMutation = useMutation({
    mutationFn: () => twinOptimizerApi.optimize(defaultOptimizeRequest()),
  });
  const optimizeResult = optimizeMutation.data;

  if (isLoading) {
    return (
      <div className="space-y-6">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={6} />
      </div>
    );
  }

  // The backend recommendations response has no `status` field (it only ever
  // returns pending recs), so treat a missing/unknown status as pending —
  // otherwise the Approve/Reject cards would never render. History keeps only
  // recs that carry an explicit resolved status.
  const pendingRecs = recommendations?.filter((r) => !r.status || r.status === 'pending') || [];
  const historyRecs = recommendations?.filter((r) => r.status && r.status !== 'pending') || [];

  return (
    <div className="space-y-6">
      {isError && (
        <Card className="p-4">
          <p className="text-status-alarm text-sm">
            Failed to load recommendations. Retrying automatically…
          </p>
        </Card>
      )}

      {actionError && (
        <Card className="p-4">
          <p className="text-status-alarm text-sm">
            Action failed. The recommendation could not be updated — please try again.
          </p>
        </Card>
      )}

      {/* Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <Lightbulb className="w-8 h-8 text-opsgrid-primary" />
                <div>
                  {/* 0 Pending, 0 Approved and 0 Rejected sat beside the failure
                      banner — three counts of nothing, from nothing. */}
                  <p className="text-2xl font-bold">{isError ? '—' : pendingRecs.length}</p>
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
                    {isError ? '—' : historyRecs.filter((r) => r.status === 'approved').length}
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
                    {isError ? '—' : historyRecs.filter((r) => r.status === 'rejected').length}
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
            loading={optimizeMutation.isPending}
            disabled={optimizeMutation.isPending}
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
          {isError ? (
            /* The banner at the top of the page marks the failure; it does not guard
               anything below it. `recommendations` is undefined on a failed query, so
               `pendingRecs` is [] and this said "No pending recommendations. Check back
               later" — an instruction to stop looking, given to someone whose
               recommendations could not be fetched. Rule 24. */
            <p role="alert" className="text-status-alarm text-center py-8">
              Recommendations could not be loaded. This is a failed request — it does not
              mean the strategic engine has nothing to suggest.
            </p>
          ) : pendingRecs.length === 0 ? (
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


// `expectedImpact` is an open-ended dict — the engine sends a different set of keys per
// recommendation type (`oee_improvement`, `cost_reduction`, `throughput_gain`,
// `rul_extension_days`) — so the card labels whatever arrives rather than naming three slots
// in advance. `costSavings` and `timeSavings` were two of those three names and matched
// nothing the server sends.
const IMPACT_LABELS: Record<string, string> = {
  oeeImprovement: 'OEE Impact',
  costReduction: 'Cost Reduction',
  throughputGain: 'Throughput Gain',
  rulExtensionDays: 'RUL Extension',
};

const impactLabel = (key: string): string =>
  IMPACT_LABELS[key] ??
  // camelCase -> "Camel Case", so an impact nobody has named yet still reads as words.
  key.replace(/([A-Z])/g, ' $1').replace(/^./, (c) => c.toUpperCase());

const impactValue = (key: string, value: unknown): string => {
  if (typeof value !== 'number') return String(value);
  if (key === 'costReduction') return `$${value.toLocaleString()}`;
  if (key === 'rulExtensionDays') return `${value.toLocaleString()} days`;
  // The remaining known impacts are fractions; anything unrecognised is shown as sent rather
  // than multiplied by a hundred on a guess.
  if (key in IMPACT_LABELS) return `+${formatPercentage(value)}`;
  return value.toLocaleString();
};

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

      {/* THREE FIXED SLOTS, TWO OF WHICH COULD NEVER FILL. `expectedImpact` is free-form —
          the engine documents it as `{'oee_improvement': ..., 'cost_reduction': ...}` and
          sends a different set per recommendation type — and this grid named `costSavings`
          (the key is `costReduction`) and `timeSavings` (nothing produces it). So a
          recommendation whose impact was a throughput gain or forty-five days of extra RUL
          showed an empty box, and the cost figure never appeared at all.

          Rendered from what arrives instead. The two known keys keep their formatting; the
          rest are labelled from the key, which is the only honest thing to do with an
          open-ended dict. */}
      <div className="grid grid-cols-3 gap-4 mb-4 p-3 bg-opsgrid-panel rounded">
        {Object.entries(rec.expectedImpact ?? {})
          .filter(([, value]) => value !== undefined && value !== null)
          .map(([key, value]) => (
            <div key={key}>
              <p className="text-xs text-opsgrid-text-secondary">{impactLabel(key)}</p>
              <p className="font-medium text-status-running">{impactValue(key, value)}</p>
            </div>
          ))}
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
