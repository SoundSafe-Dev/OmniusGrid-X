import { FC, useState } from 'react';
import { Activity, AlertTriangle, Wrench } from 'lucide-react';
import { Card, Badge, SkeletonCard } from '../../components';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';

export const AssetHealth: FC = () => {
  return (
    <div className="space-y-6">
      <Card title="Fleet Health Overview" subtitle="Asset health distribution">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {['Excellent', 'Good', 'Fair', 'Poor'].map((status, i) => (
            <Tooltip key={status}>
              <TooltipTrigger asChild>
                <div className="p-4 bg-opsgrid-bg rounded-lg text-center">
                  <p className="text-3xl font-bold text-opsgrid-primary">{[12, 8, 3, 1][i]}</p>
                  <p className="text-sm text-opsgrid-text-secondary">{status}</p>
                </div>
              </TooltipTrigger>
              <TooltipContent>Assets with {status.toLowerCase()} health condition</TooltipContent>
            </Tooltip>
          ))}
        </div>
      </Card>

      <Card title="At-Risk Assets" subtitle="Assets requiring attention">
        <div className="space-y-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center justify-between p-3 bg-opsgrid-bg rounded-lg">
                <div className="flex items-center gap-3">
                  <AlertTriangle className="text-status-warning" size={20} />
                  <div>
                    <p className="font-medium">Printer #3 (Bambu Labs X1)</p>
                    <p className="text-sm text-opsgrid-text-secondary">Vibration anomaly detected</p>
                  </div>
                </div>
                <Badge variant="warning" size="sm">Fair</Badge>
              </div>
            </TooltipTrigger>
            <TooltipContent>At-risk asset requiring maintenance attention</TooltipContent>
          </Tooltip>
        </div>
      </Card>
    </div>
  );
};

export const PredictiveMaintenance: FC = () => {
  return (
    <div className="space-y-6">
      <Card title="Upcoming Maintenance" subtitle="Scheduled maintenance tasks">
        <div className="space-y-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center justify-between p-3 bg-opsgrid-bg rounded-lg">
                <div className="flex items-center gap-3">
                  <Wrench className="text-opsgrid-primary" size={20} />
                  <div>
                    <p className="font-medium">Preventive Maintenance - Line A</p>
                    <p className="text-sm text-opsgrid-text-secondary">Due in 3 days</p>
                  </div>
                </div>
                <Badge variant="info" size="sm">Scheduled</Badge>
              </div>
            </TooltipTrigger>
            <TooltipContent>Scheduled preventive maintenance task</TooltipContent>
          </Tooltip>
        </div>
      </Card>
    </div>
  );
};

export const TelemetryCharts: FC = () => {
  const [timeRange, setTimeRange] = useState('24h');

  return (
    <div className="space-y-6">
      <Card title="Telemetry Visualization" subtitle="Historical data analysis">
        <div className="h-64 flex items-center justify-center bg-opsgrid-bg rounded-lg">
          <p className="text-opsgrid-text-secondary">Charts will be rendered here with Recharts</p>
        </div>
      </Card>
    </div>
  );
};
