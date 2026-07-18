import { FC, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Zap, Activity, Shield, Eye, EyeOff } from 'lucide-react';
import { Card, Badge, Button, SkeletonCard } from '../../components';
import { enginesApi } from '../../api';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';

export const TacticalEngine: FC = () => {
  const { data: status, isLoading, isError } = useQuery({
    queryKey: ['tactical-status'],
    queryFn: () => enginesApi.getTacticalStatus(),
    refetchInterval: 5000,
  });

  // Local display-only toggle — reveals the safety thresholds reported by the
  // engine. There is no endpoint to change enforcement from here.
  const [showThresholds, setShowThresholds] = useState(true);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={6} />
      </div>
    );
  }

  const thresholds = status?.safetyThresholds ?? {};
  const thresholdEntries = Object.entries(thresholds);

  return (
    <div className="space-y-6">
      {isError && (
        <Card className="p-4">
          <p className="text-status-alarm text-sm">
            Failed to load tactical engine status. Retrying automatically…
          </p>
        </Card>
      )}

      {/* Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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
      </div>

      {/* Safety Thresholds (display only) */}
      <Card title="Safety Thresholds" subtitle="Configured limits reported by the engine (view only)">
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center justify-between p-4 bg-opsgrid-bg rounded-lg">
              <div className="flex items-center gap-3">
                <Shield className="w-5 h-5 text-opsgrid-primary" />
                <div>
                  <p className="font-medium">Configured Safety Thresholds</p>
                  <p className="text-sm text-opsgrid-text-secondary">
                    Read-only view of the limits the engine reports
                  </p>
                </div>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowThresholds((v) => !v)}
              >
                {showThresholds ? <EyeOff size={16} /> : <Eye size={16} />}
                {showThresholds ? 'Hide' : 'Show'}
              </Button>
            </div>
          </TooltipTrigger>
          <TooltipContent>Show or hide the reported safety thresholds (local view only)</TooltipContent>
        </Tooltip>

        {showThresholds && (
          <div className="mt-4">
            {thresholdEntries.length === 0 ? (
              <p className="text-opsgrid-text-secondary text-sm">
                No safety thresholds reported by the engine.
              </p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {thresholdEntries.map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between p-3 bg-opsgrid-bg rounded-lg">
                    <span className="text-sm text-opsgrid-text-secondary">{key}</span>
                    <span className="font-medium">{String(value)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
};
