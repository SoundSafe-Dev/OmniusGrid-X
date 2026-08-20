import { FC, Fragment, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Activity, AlertTriangle, ChevronDown, ChevronRight, ExternalLink, HeartPulse } from 'lucide-react';
import { Card, Badge, SkeletonCard } from '../../components';
import { Tooltip, TooltipTrigger, TooltipContent, ErrorState } from '../../components/ui';
import { rulApi } from '../../api';
import type { RULAssessment } from '../../api/rul';
import { formatDateTime, formatPercentage, cn } from '../../utils';

const RISK_LEVELS = ['critical', 'high', 'medium', 'low'] as const;

const riskVariant = (risk: string): 'success' | 'warning' | 'error' | 'info' | 'neutral' => {
  switch (risk?.toLowerCase()) {
    case 'critical':
      return 'error';
    case 'high':
      return 'warning';
    case 'medium':
      return 'info';
    case 'low':
      return 'success';
    default:
      return 'neutral';
  }
};

const formatHours = (hours: number): string => {
  if (hours >= 168) return `${(hours / 168).toFixed(1)} wk`;
  if (hours >= 24) return `${(hours / 24).toFixed(1)} d`;
  return `${Math.round(hours)} h`;
};

/** Rows requested per load. Named because the truncation notice quotes it. */
const PAGE_LIMIT = 100;

export const PredictiveMaintenance: FC = () => {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['rul-assessments'],
    queryFn: () => rulApi.listAssessments({ hours: 24, limit: PAGE_LIMIT }),
    refetchInterval: 60000,
  });

  const [riskFilter, setRiskFilter] = useState<string | null>(null);
  const [expandedAssetId, setExpandedAssetId] = useState<string | null>(null);

  const assessments: RULAssessment[] = useMemo(() => data?.items ?? [], [data]);
  // The endpoint caps at `limit` and orders by asset NAME, because remaining useful
  // life is computed per asset rather than stored — so risk cannot be sorted on in SQL.
  // Truncation therefore drops the alphabetically-last assets from the one view whose
  // job is finding machines about to fail, and the tiles below counted the survivors as
  // though the fleet had been fully assessed.
  const truncated = data?.truncated ?? false;

  // Most-urgent-first: RUL ascending, optionally narrowed to one risk level.
  const visibleAssessments = useMemo(() => {
    const filtered = riskFilter
      ? assessments.filter((a) => a.riskLevel?.toLowerCase() === riskFilter)
      : assessments;
    return [...filtered].sort(
      (a, b) => a.remainingUsefulLifeHours - b.remainingUsefulLifeHours
    );
  }, [assessments, riskFilter]);

  const riskCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const a of assessments) {
      const key = a.riskLevel?.toLowerCase();
      counts[key] = (counts[key] ?? 0) + 1;
    }
    return counts;
  }, [assessments]);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={8} />
      </div>
    );
  }

  const atRisk = assessments.filter((a) =>
    ['critical', 'high'].includes(a.riskLevel?.toLowerCase())
  );
  const avgHealth =
    assessments.length > 0
      ? assessments.reduce((s, a) => s + a.healthScore, 0) / assessments.length
      : 0;

  const toggleRow = (assetId: string) =>
    setExpandedAssetId((cur) => (cur === assetId ? null : assetId));

  const chipClass = (active: boolean) =>
    cn(
      'px-3 py-1 rounded-full text-xs font-medium border transition-colors',
      active
        ? 'bg-opsgrid-primary/20 border-opsgrid-primary text-opsgrid-primary'
        : 'border-opsgrid-border text-opsgrid-text-secondary hover:bg-opsgrid-border hover:text-opsgrid-text'
    );

  return (
    <div className="space-y-6">
      {truncated && (
        <Card className="p-3 border-status-warning" role="status">
          <p className="text-sm text-opsgrid-text">
            Showing the first {assessments.length} assets by name — your fleet has more.
            The figures below cover only these, so an asset outside this page is not
            counted even if it is close to failure.
          </p>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <HeartPulse className="w-8 h-8 text-opsgrid-primary" />
                <div>
                  <p className="text-2xl font-bold">
                    {assessments.length}
                    {truncated && <span className="text-base font-normal">+</span>}
                  </p>
                  <p className="text-sm text-opsgrid-text-secondary">Assets Assessed</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>
            {truncated
              ? `Assets with a current RUL assessment. More exist than were assessed here — this page requests ${PAGE_LIMIT}, ordered by asset name.`
              : 'Assets with a current RUL assessment'}
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <AlertTriangle className="w-8 h-8 text-status-alarm" />
                <div>
                  <p className="text-2xl font-bold">{atRisk.length}</p>
                  <p className="text-sm text-opsgrid-text-secondary">High / Critical Risk</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Assets projected to need attention soon</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <Activity className="w-8 h-8 text-status-running" />
                <div>
                  <p className="text-2xl font-bold">{formatPercentage(avgHealth)}</p>
                  <p className="text-sm text-opsgrid-text-secondary">Average Health</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Mean health score across assessed assets</TooltipContent>
        </Tooltip>
      </div>

      <Card
        title="Remaining Useful Life"
        subtitle="Predictive-maintenance assessment per asset, most urgent first"
      >
        {isError ? (
          <ErrorState message="Failed to load RUL assessments." />
        ) : assessments.length === 0 ? (
          <p className="text-opsgrid-text-secondary text-center py-8">
            No assets available for assessment.
          </p>
        ) : (
          <div className="space-y-4">
            {/* Risk-level filter chips */}
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter by risk level">
              <button
                type="button"
                className={chipClass(riskFilter === null)}
                onClick={() => setRiskFilter(null)}
              >
                All ({assessments.length})
              </button>
              {RISK_LEVELS.map((level) => (
                <button
                  key={level}
                  type="button"
                  className={chipClass(riskFilter === level)}
                  onClick={() => setRiskFilter((cur) => (cur === level ? null : level))}
                >
                  {level.charAt(0).toUpperCase() + level.slice(1)} ({riskCounts[level] ?? 0})
                </button>
              ))}
            </div>

            {visibleAssessments.length === 0 ? (
              <p className="text-opsgrid-text-secondary text-center py-8">
                No assets at this risk level.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-opsgrid-text-secondary border-b border-opsgrid-border">
                      <th className="py-2 pr-2 font-medium w-8" aria-label="Expand" />
                      <th className="py-2 pr-4 font-medium">Asset</th>
                      <th className="py-2 pr-4 font-medium">Health</th>
                      <th className="py-2 pr-4 font-medium">RUL ↑</th>
                      <th className="py-2 pr-4 font-medium">Failure Prob.</th>
                      <th className="py-2 pr-4 font-medium">Risk</th>
                      <th className="py-2 pr-4 font-medium">Maintenance Window</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-opsgrid-border">
                    {visibleAssessments.map((a) => {
                      const expanded = expandedAssetId === a.assetId;
                      return (
                        <Fragment key={a.assetId}>
                          <tr
                            className="cursor-pointer hover:bg-opsgrid-bg/60 transition-colors"
                            onClick={() => toggleRow(a.assetId)}
                            aria-expanded={expanded}
                          >
                            <td className="py-2 pr-2 text-opsgrid-text-secondary">
                              {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                            </td>
                            <td className="py-2 pr-4 font-mono text-xs">{a.assetId}</td>
                            <td className="py-2 pr-4">{formatPercentage(a.healthScore)}</td>
                            <td className="py-2 pr-4">{formatHours(a.remainingUsefulLifeHours)}</td>
                            <td className="py-2 pr-4">{formatPercentage(a.failureProbability)}</td>
                            <td className="py-2 pr-4">
                              <Badge variant={riskVariant(a.riskLevel)} size="sm">
                                {a.riskLevel}
                              </Badge>
                            </td>
                            <td className="py-2 pr-4 text-opsgrid-text-secondary">
                              {formatDateTime(a.recommendedMaintenanceWindow.start)}
                            </td>
                          </tr>
                          {expanded && (
                            <tr>
                              <td colSpan={7} className="p-0">
                                <AssessmentDetail assessment={a} />
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
};

/** Drill-down panel with the full assessment payload for one asset. */
const AssessmentDetail: FC<{ assessment: RULAssessment }> = ({ assessment: a }) => {
  const window = a.recommendedMaintenanceWindow;
  return (
    <div className="m-2 p-4 bg-opsgrid-bg rounded-lg border border-opsgrid-border space-y-4">
      <div className="flex items-center justify-between">
        <p className="font-medium text-sm">Assessment Detail — {a.assetId}</p>
        <Link
          to={`/assets/${a.assetId}`}
          className="inline-flex items-center gap-1 text-sm text-opsgrid-primary hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          <ExternalLink size={14} />
          View asset
        </Link>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        <div>
          <p className="text-xs text-opsgrid-text-secondary">Confidence</p>
          <p className="font-medium">{formatPercentage(a.confidence)}</p>
        </div>
        <div>
          <p className="text-xs text-opsgrid-text-secondary">Probability Horizon</p>
          <p className="font-medium">{formatHours(a.probabilityHorizonHours)}</p>
        </div>
        <div>
          <p className="text-xs text-opsgrid-text-secondary">Model Source</p>
          <p className="font-medium">{a.modelSource}</p>
        </div>
        <div>
          <p className="text-xs text-opsgrid-text-secondary">Computed At</p>
          <p className="font-medium">{formatDateTime(a.computedAt)}</p>
        </div>
      </div>

      <div className="p-3 bg-opsgrid-panel rounded text-sm space-y-1">
        <div className="flex items-center gap-2">
          <p className="text-xs text-opsgrid-text-secondary">Recommended Maintenance Window</p>
          <Badge variant={riskVariant(window.urgency)} size="sm">
            {window.urgency}
          </Badge>
        </div>
        <p className="font-medium">
          {formatDateTime(window.start)} — {formatDateTime(window.end)}
        </p>
        <p className="text-opsgrid-text-secondary">{window.reason}</p>
      </div>

      {a.drivers.length > 0 && (
        <div className="text-sm">
          <p className="text-xs text-opsgrid-text-secondary mb-2">Top Drivers</p>
          <div className="flex flex-wrap gap-2">
            {a.drivers.map((driver, i) => {
              const feature = typeof driver.feature === 'string' ? driver.feature : `driver-${i + 1}`;
              const contribution =
                typeof driver.contribution === 'number'
                  ? ` · ${formatPercentage(driver.contribution)}`
                  : '';
              return (
                <Badge key={`${feature}-${i}`} variant="neutral" size="sm">
                  {feature}
                  {contribution}
                </Badge>
              );
            })}
          </div>
        </div>
      )}

      <p className="text-xs text-opsgrid-text-secondary">
        {a.notificationDispatched
          ? `Notification dispatched (${a.notificationDeliveryCount} deliver${
              a.notificationDeliveryCount === 1 ? 'y' : 'ies'
            })`
          : 'No notification dispatched for this assessment'}
      </p>
    </div>
  );
};
