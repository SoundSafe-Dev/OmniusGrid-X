import { FC } from 'react';
import { useQuery } from 'react-query';
import { Activity, AlertTriangle, HeartPulse } from 'lucide-react';
import { Card, Badge, SkeletonCard } from '../../components';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';
import { rulApi } from '../../api';
import type { RULAssessment } from '../../api/rul';
import { formatDateTime, formatPercentage } from '../../utils';

const riskVariant = (risk: string): 'success' | 'warning' | 'error' | 'info' | 'neutral' => {
  switch (risk.toLowerCase()) {
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

export const PredictiveMaintenance: FC = () => {
  const { data, isLoading, isError } = useQuery(
    'rul-assessments',
    () => rulApi.listAssessments({ hours: 24, limit: 100 }),
    { refetchInterval: 60000 }
  );

  if (isLoading) {
    return (
      <div className="space-y-6">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={8} />
      </div>
    );
  }

  const assessments: RULAssessment[] = data ?? [];
  const atRisk = assessments.filter((a) =>
    ['critical', 'high'].includes(a.riskLevel.toLowerCase())
  );
  const avgHealth =
    assessments.length > 0
      ? assessments.reduce((s, a) => s + a.healthScore, 0) / assessments.length
      : 0;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <HeartPulse className="w-8 h-8 text-opsgrid-primary" />
                <div>
                  <p className="text-2xl font-bold">{assessments.length}</p>
                  <p className="text-sm text-opsgrid-text-secondary">Assets Assessed</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Assets with a current RUL assessment</TooltipContent>
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
        subtitle="Predictive-maintenance assessment per asset"
      >
        {isError ? (
          <p className="text-status-alarm text-sm py-4">
            Failed to load RUL assessments.
          </p>
        ) : assessments.length === 0 ? (
          <p className="text-opsgrid-text-secondary text-center py-8">
            No assets available for assessment.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-opsgrid-text-secondary border-b border-opsgrid-border">
                  <th className="py-2 pr-4 font-medium">Asset</th>
                  <th className="py-2 pr-4 font-medium">Health</th>
                  <th className="py-2 pr-4 font-medium">RUL</th>
                  <th className="py-2 pr-4 font-medium">Failure Prob.</th>
                  <th className="py-2 pr-4 font-medium">Risk</th>
                  <th className="py-2 pr-4 font-medium">Maintenance Window</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-opsgrid-border">
                {assessments.map((a) => (
                  <tr key={a.assetId}>
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
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
};
