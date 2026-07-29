import { FC, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, ChevronDown, ChevronRight, Wrench } from 'lucide-react';
import { Card, Badge, SkeletonCard } from '../../components';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';
import { AnnotatedChart, FacilityHeatmap } from '../../components/charts';
import { assetsApi, dashboardApi, telemetryApi, maintenanceApi } from '../../api';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  Legend,
  ResponsiveContainer
} from 'recharts';

const RUNNING_STATES = ['Execute', 'Idle'];
const AT_RISK_STATES = ['Held', 'Holding', 'Suspended', 'Aborted', 'Aborting', 'Stopped', 'Stopping'];

export const AssetHealth: FC = () => {
  const { data: assetsPage, isLoading, isError } = useQuery({ queryKey: ['assethealth-assets'], queryFn: () => assetsApi.list({ limit: 500 }) });
  const assets = assetsPage?.items ?? [];

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Card title="Fleet Health Overview" subtitle="Asset state distribution">
          <SkeletonCard lines={4} />
        </Card>
      </div>
    );
  }

  if (isError) {
    return (
      <Card className="p-4">
        <p className="text-status-alarm text-sm">
          Failed to load asset health data. Please try again.
        </p>
      </Card>
    );
  }

  const buckets = [
    { status: 'Executing', count: assets.filter((a) => a.currentPackmlState === 'Execute').length },
    { status: 'Idle', count: assets.filter((a) => a.currentPackmlState === 'Idle').length },
    { status: 'At Risk', count: assets.filter((a) => AT_RISK_STATES.includes(a.currentPackmlState)).length },
    { status: 'Offline', count: assets.filter((a) => !RUNNING_STATES.includes(a.currentPackmlState) && !AT_RISK_STATES.includes(a.currentPackmlState)).length },
  ];
  const atRisk = assets.filter((a) => AT_RISK_STATES.includes(a.currentPackmlState));

  return (
    <div className="space-y-6">
      <Card title="Fleet Health Overview" subtitle="Asset state distribution">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {buckets.map(({ status, count }) => (
            <Tooltip key={status}>
              <TooltipTrigger asChild>
                <div className="p-4 bg-opsgrid-bg rounded-lg text-center">
                  <p className="text-3xl font-bold text-opsgrid-primary">{count}</p>
                  <p className="text-sm text-opsgrid-text-secondary">{status}</p>
                </div>
              </TooltipTrigger>
              <TooltipContent>Assets currently {status.toLowerCase()}</TooltipContent>
            </Tooltip>
          ))}
        </div>
      </Card>

      <Card title="At-Risk Assets" subtitle="Assets requiring attention">
        <div className="space-y-2">
          {atRisk.length === 0 ? (
            <p className="text-sm text-opsgrid-text-secondary">No assets currently at risk.</p>
          ) : atRisk.map((a) => (
            <Tooltip key={a.id}>
              <TooltipTrigger asChild>
                <div className="flex items-center justify-between p-3 bg-opsgrid-bg rounded-lg">
                  <div className="flex items-center gap-3">
                    <AlertTriangle className="text-status-warning" size={20} />
                    <div>
                      <p className="font-medium">{a.name}</p>
                      <p className="text-sm text-opsgrid-text-secondary">State: {a.currentPackmlState}</p>
                    </div>
                  </div>
                  <Badge variant="warning" size="sm">{a.currentPackmlState}</Badge>
                </div>
              </TooltipTrigger>
              <TooltipContent>At-risk asset requiring attention</TooltipContent>
            </Tooltip>
          ))}
        </div>
      </Card>
    </div>
  );
};

export const PredictiveMaintenance: FC = () => {
  const { data: upcoming, isLoading, isError } = useQuery({ queryKey: ['predictive-upcoming'], queryFn: () => maintenanceApi.getUpcomingMaintenance(30) });
  const items = upcoming ?? [];

  const dueLabel = (dateStr?: string) => {
    if (!dateStr) return 'No date';
    const days = Math.ceil((new Date(dateStr).getTime() - Date.now()) / 86_400_000);
    if (days < 0) return `Overdue by ${-days}d`;
    if (days === 0) return 'Due today';
    return `Due in ${days} day${days === 1 ? '' : 's'}`;
  };

  return (
    <div className="space-y-6">
      <Card title="Upcoming Maintenance" subtitle="Scheduled maintenance tasks (next 30 days)">
        <div className="space-y-2">
          {isLoading ? (
            <SkeletonCard lines={3} />
          ) : isError ? (
            <p className="text-status-alarm text-sm">
              Failed to load maintenance schedule. Please try again.
            </p>
          ) : items.length === 0 ? (
            <p className="text-sm text-opsgrid-text-secondary">No maintenance scheduled in the next 30 days.</p>
          ) : items.map((s) => (
            <Tooltip key={s.id}>
              <TooltipTrigger asChild>
                <div className="flex items-center justify-between p-3 bg-opsgrid-bg rounded-lg">
                  <div className="flex items-center gap-3">
                    <Wrench className="text-opsgrid-primary" size={20} />
                    <div>
                      <p className="font-medium">{s.serviceType} — {s.vehicleNumber || s.vehicleId}</p>
                      <p className="text-sm text-opsgrid-text-secondary">{dueLabel(s.scheduledDate)}</p>
                    </div>
                  </div>
                  <Badge variant={s.status === 'overdue' ? 'warning' : 'info'} size="sm">{s.status}</Badge>
                </div>
              </TooltipTrigger>
              <TooltipContent>{s.description || 'Scheduled maintenance task'}</TooltipContent>
            </Tooltip>
          ))}
        </div>
      </Card>
    </div>
  );
};

const RANGE_HOURS: Record<string, number> = { '24h': 24, '7d': 168, '30d': 720 };
const METRIC_COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#8B5CF6', '#EF4444'];

export const TelemetryCharts: FC = () => {
  const [timeRange, setTimeRange] = useState('24h');
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Real data: first asset's telemetry history, current fleet OEE, and the
  // fleet's PackML-state distribution. (Nozzle/bed/vibration were 3D-printer
  // demo metrics; the chart now plots whatever metrics the asset actually has.)
  const { data: assetsPage, isLoading: assetsLoading, isError: assetsError } = useQuery({ queryKey: ['analytics-assets'], queryFn: () => assetsApi.list({ limit: 500 }) });
  const assets = assetsPage?.items ?? [];
  const firstAsset = assets[0];

  const startTime = new Date(Date.now() - (RANGE_HOURS[timeRange] ?? 24) * 3600_000).toISOString();
  const { data: history, isLoading: historyLoading, isError: historyError } = useQuery({
    queryKey: ['analytics-telemetry', firstAsset?.id, timeRange],
    queryFn: () => telemetryApi.getHistory(firstAsset!.id, { startTime }),
    enabled: !!firstAsset,
  });
  const { data: fleetOEE, isLoading: oeeLoading, isError: oeeError } = useQuery({ queryKey: ['analytics-fleet-oee'], queryFn: () => dashboardApi.getFleetOEE() });

  // Pivot the flat TelemetryPoint[] into chart rows keyed by the full timestamp
  // (not time-of-day) so multi-day ranges don't collapse different days into the
  // same HH:MM bucket. Label includes the date for ranges longer than a day.
  const points = history ?? [];
  const metricNames = Array.from(new Set(points.map((p) => p.metricName))).slice(0, METRIC_COLORS.length);
  const multiDay = (RANGE_HOURS[timeRange] ?? 24) > 24;
  const byTime = new Map<number, Record<string, any>>();
  for (const p of points) {
    const d = new Date(p.timestamp);
    const key = Math.floor(d.getTime() / 60_000) * 60_000; // minute bucket
    const label = multiDay
      ? d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
      : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const row = byTime.get(key) ?? { time: label };
    row[p.metricName] = p.value;
    byTime.set(key, row);
  }
  const metricSeries = Array.from(byTime.entries()).sort((a, b) => a[0] - b[0]).map(([, row]) => row);

  // Current fleet OEE as a single real period (no historical OEE series yet).
  // FleetOEE exposes fleet-average AVAILABILITY only (0-1 fraction). It used to
  // also carry `fleetAverageOee`, which was the same availability number — so
  // plotting both drew one series twice and called one of them OEE.
  const asPct = (v: number) => Math.round((v ?? 0) * (v > 1 ? 1 : 100));
  // No point is plotted when there is nothing to average. `asPct(null)` would render a
  // bar at 0% — a fleet-wide outage drawn from an empty fleet — which is the same
  // defect the API was just fixed for, recreated one layer up.
  const oeeData =
    fleetOEE && fleetOEE.fleetAverageAvailability != null
      ? [{ time: 'Current', availability: asPct(fleetOEE.fleetAverageAvailability) }]
      : [];

  // Health distribution from real PackML states.
  const healthBuckets = { Executing: 0, Idle: 0, Held: 0, 'Down/Other': 0 };
  for (const a of assets) {
    const s = a.currentPackmlState;
    if (s === 'Execute') healthBuckets.Executing++;
    else if (s === 'Idle') healthBuckets.Idle++;
    else if (s === 'Held') healthBuckets.Held++;
    else healthBuckets['Down/Other']++;
  }
  const healthDistribution = Object.entries(healthBuckets).map(([status, count]) => ({ status, count }));

  // Advanced Plotly section (FS-62): per-asset OEE mapped onto a grid for the
  // heatmap (x = index % cols, y = row, value = OEE %), plus the fleet OEE
  // trend rendered through the annotatable plotly wrapper.
  const HEATMAP_COLS = 4;
  // Availability per asset — the endpoint no longer reports a per-asset `oee`
  // (it was the availability figure under another name).
  const oeeHeatmapData = (fleetOEE?.assets ?? []).map((a, i) => ({
    x: i % HEATMAP_COLS,
    y: Math.floor(i / HEATMAP_COLS),
    value: asPct(a.availability),
    label: `${a.assetName}: ${asPct(a.availability)}% availability`,
  }));
  const oeeTrendTraces = [
    {
      type: 'scatter',
      mode: 'lines+markers',
      name: 'Availability (%)',
      x: oeeData.map((d) => d.time),
      y: oeeData.map((d) => d.availability),
      line: { color: '#3B82F6' },
    },
    // A second "OEE (%)" trace used to be plotted here from `fleetAverageOee`,
    // which the API computed as exactly `fleetAverageAvailability` — so the
    // chart drew one series twice and labelled one of them OEE.
  ];

  const anyError = assetsError || historyError || oeeError;
  const anyLoading = assetsLoading || historyLoading || oeeLoading;

  if (anyError) {
    return (
      <Card className="p-4">
        <p className="text-status-alarm text-sm">
          Failed to load telemetry data. Please try again.
        </p>
      </Card>
    );
  }

  if (anyLoading) {
    return (
      <div className="space-y-6">
        <Card title="Telemetry Visualization" subtitle="Historical data analysis">
          <SkeletonCard lines={6} />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card title="Telemetry Visualization" subtitle="Historical data analysis">
        <div className="mb-4">
          <select 
            value={timeRange} 
            onChange={(e) => setTimeRange(e.target.value)}
            className="px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-opsgrid-text-primary"
          >
            <option value="24h">Last 24 Hours</option>
            <option value="7d">Last 7 Days</option>
            <option value="30d">Last 30 Days</option>
          </select>
        </div>

        <div className="space-y-8">
          {/* Real metric trends for the first asset */}
          <div>
            <h3 className="text-lg font-semibold mb-4 text-opsgrid-text-primary">
              Metric Trends{firstAsset ? ` — ${firstAsset.name}` : ''}
            </h3>
            {metricSeries.length === 0 ? (
              <p className="text-sm text-opsgrid-text-secondary">
                {firstAsset ? 'No telemetry in this range.' : 'No assets available.'}
              </p>
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={metricSeries}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis dataKey="time" stroke="#9CA3AF" />
                    <YAxis stroke="#9CA3AF" />
                    <RechartsTooltip
                      contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                      itemStyle={{ color: '#F3F4F6' }}
                    />
                    <Legend />
                    {metricNames.map((m, i) => (
                      <Line key={m} type="monotone" dataKey={m} stroke={METRIC_COLORS[i % METRIC_COLORS.length]} strokeWidth={2} name={m} dot={false} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          {/* Current fleet OEE */}
          <div>
            <h3 className="text-lg font-semibold mb-4 text-opsgrid-text-primary">Fleet OEE (current)</h3>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={oeeData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="time" stroke="#9CA3AF" />
                  <YAxis stroke="#9CA3AF" domain={[0, 100]} />
                  <RechartsTooltip
                    contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                    itemStyle={{ color: '#F3F4F6' }}
                  />
                  <Legend />
                  <Bar dataKey="availability" fill="#3B82F6" name="Availability (%)" />
                  <Bar dataKey="oee" fill="#10B981" name="OEE (%)" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Asset Health Distribution (real PackML states) */}
          <div>
            <h3 className="text-lg font-semibold mb-4 text-opsgrid-text-primary">Asset State Distribution</h3>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={healthDistribution}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="status" stroke="#9CA3AF" />
                  <YAxis stroke="#9CA3AF" />
                  <RechartsTooltip 
                    contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                    itemStyle={{ color: '#F3F4F6' }}
                  />
                  <Bar 
                    dataKey="count" 
                    fill="#3B82F6"
                    name="Asset Count"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </Card>

      {/* Advanced Plotly visualizations (FS-62), collapsed by default */}
      <Card
        title="Advanced Visualizations"
        subtitle="Per-asset OEE heatmap and annotatable OEE trend"
        action={
          <button
            onClick={() => setShowAdvanced((v) => !v)}
            className="flex items-center gap-1 px-3 py-1.5 text-sm text-opsgrid-text-secondary hover:text-opsgrid-text border border-opsgrid-border rounded-lg transition-colors"
            aria-expanded={showAdvanced}
          >
            {showAdvanced ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            {showAdvanced ? 'Hide' : 'Show'}
          </button>
        }
      >
        {showAdvanced ? (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            {oeeHeatmapData.length > 0 ? (
              <FacilityHeatmap
                data={oeeHeatmapData}
                title="OEE by Asset"
                height={400}
              />
            ) : (
              <p className="text-sm text-opsgrid-text-secondary">No per-asset OEE data available.</p>
            )}
            <AnnotatedChart
              data={oeeTrendTraces}
              title="Fleet OEE Trend"
              editable
            />
          </div>
        ) : (
          <p className="text-sm text-opsgrid-text-secondary">
            Expand to load the plotly-based OEE heatmap and annotatable trend chart.
          </p>
        )}
      </Card>
    </div>
  );
};
