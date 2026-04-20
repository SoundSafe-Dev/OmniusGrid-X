import { FC, useEffect, useState, useCallback, useMemo } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { format } from 'date-fns';
import { Activity, Wifi, WifiOff } from 'lucide-react';
import { websocketManager } from '../../api';
import { ChartContainer } from '../ui';

interface TelemetryDataPoint {
  timestamp: number;
  [metric: string]: number | string;
}

interface RealtimeTelemetryChartProps {
  assetId: string;
  assetName?: string;
  metrics?: string[];  // e.g., ['temp_nozzle', 'temp_bed', 'print_speed']
  timeWindow?: number; // seconds, default 300 (5 minutes)
  height?: number;
  showLegend?: boolean;
  title?: string;
}

const COLORS = [
  '#3b82f6', // blue-500
  '#10b981', // emerald-500
  '#f59e0b', // amber-500
  '#ef4444', // red-500
  '#8b5cf6', // violet-500
  '#ec4899', // pink-500
];

export const RealtimeTelemetryChart: FC<RealtimeTelemetryChartProps> = ({
  assetId,
  assetName,
  metrics = ['temp_nozzle', 'temp_bed'],
  timeWindow = 300,
  height = 300,
  showLegend = true,
  title,
}) => {
  const [data, setData] = useState<TelemetryDataPoint[]>([]);
  const [connected, setConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [metricColors] = useState(() => {
    const colors: Record<string, string> = {};
    metrics.forEach((metric, i) => {
      colors[metric] = COLORS[i % COLORS.length];
    });
    return colors;
  });

  // Initialize with empty data points for the time window
  useEffect(() => {
    const now = Date.now();
    const initialData: TelemetryDataPoint[] = [];
    for (let i = 20; i >= 0; i--) {
      initialData.push({
        timestamp: now - i * (timeWindow * 1000 / 20),
      });
    }
    setData(initialData);
  }, [timeWindow]);

  // Subscribe to WebSocket telemetry
  useEffect(() => {
    const unsubscribeStatus = websocketManager.subscribe<{ connected: boolean }>(
      'connection_status',
      ({ connected }) => {
        setConnected(connected);
      }
    );

    const unsubscribeTelemetry = websocketManager.subscribe<{
      asset_id: string;
      telemetry: Record<string, number | string>;
      packml_state?: string;
    }>('telemetry', (message) => {
      if (message.asset_id !== assetId) return;

      const now = Date.now();
      const newPoint: TelemetryDataPoint = {
        timestamp: now,
      };

      // Add all metric values
      metrics.forEach((metric) => {
        const value = message.telemetry[metric];
        if (value !== undefined && value !== null) {
          newPoint[metric] = typeof value === 'number' ? value : parseFloat(value as string);
        }
      });

      setData((prev) => {
        const cutoff = now - timeWindow * 1000;
        const filtered = prev.filter((p) => p.timestamp > cutoff);
        return [...filtered, newPoint];
      });

      setLastUpdate(new Date());
    });

    return () => {
      unsubscribeStatus();
      unsubscribeTelemetry();
    };
  }, [assetId, metrics, timeWindow]);

  // Format timestamp for X-axis
  const formatXAxis = useCallback((timestamp: number) => {
    return format(new Date(timestamp), 'HH:mm:ss');
  }, []);

  // Custom tooltip
  const CustomTooltip = useCallback(
    ({ active, payload, label }: any) => {
      if (active && payload && payload.length) {
        return (
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-3 shadow-lg">
            <p className="text-sm text-opsgrid-text-secondary mb-2">
              {format(new Date(label), 'HH:mm:ss')}
            </p>
            {payload.map((entry: any, index: number) => (
              <p
                key={index}
                className="text-sm"
                style={{ color: entry.color }}
              >
                {entry.name}: {entry.value?.toFixed(2)}
              </p>
            ))}
          </div>
        );
      }
      return null;
    },
    []
  );

  // Calculate statistics
  const stats = useMemo(() => {
    if (data.length === 0) return {};

    const result: Record<string, { min: number; max: number; avg: number; latest: number }> = {};

    metrics.forEach((metric) => {
      const values = data
        .map((p) => p[metric])
        .filter((v): v is number => typeof v === 'number' && !isNaN(v));

      if (values.length > 0) {
        result[metric] = {
          min: Math.min(...values),
          max: Math.max(...values),
          avg: values.reduce((a, b) => a + b, 0) / values.length,
          latest: values[values.length - 1],
        };
      }
    });

    return result;
  }, [data, metrics]);

  // Format metric name for display
  const formatMetricName = useCallback((name: string) => {
    return name
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (l) => l.toUpperCase());
  }, []);

  return (
    <ChartContainer
      title={title || `Real-time Telemetry - ${assetName || assetId}`}
      subtitle={
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1">
            {connected ? (
              <>
                <Wifi className="w-3 h-3 text-green-500" />
                <span className="text-green-500 text-xs">Live</span>
              </>
            ) : (
              <>
                <WifiOff className="w-3 h-3 text-red-500" />
                <span className="text-red-500 text-xs">Disconnected</span>
              </>
            )}
          </span>
          {lastUpdate && (
            <span className="text-xs text-opsgrid-text-secondary">
              Last update: {format(lastUpdate, 'HH:mm:ss')}
            </span>
          )}
          <span className="text-xs text-opsgrid-text-secondary">
            Window: {timeWindow / 60}min
          </span>
        </div>
      }
      height={height}
      className="w-full"
    >
      {/* Metric Stats */}
      {Object.keys(stats).length > 0 && (
        <div className="flex flex-wrap gap-3 mb-4">
          {metrics.map((metric) => {
            const stat = stats[metric];
            if (!stat) return null;
            return (
              <div
                key={metric}
                className="px-3 py-1.5 bg-opsgrid-bg rounded-lg"
                style={{ borderLeft: `3px solid ${metricColors[metric]}` }}
              >
                <span className="text-xs text-opsgrid-text-secondary block">
                  {formatMetricName(metric)}
                </span>
                <span className="text-sm font-medium">
                  {stat.latest.toFixed(1)}
                </span>
                <span className="text-xs text-opsgrid-text-secondary ml-1">
                  (avg: {stat.avg.toFixed(1)})
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Chart */}
      {data.length > 1 ? (
        <ResponsiveContainer width="100%" height={height - 80}>
          <LineChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="timestamp"
              tickFormatter={formatXAxis}
              type="number"
              domain={['dataMin', 'dataMax']}
              scale="time"
              stroke="#94a3b8"
              tick={{ fill: '#94a3b8', fontSize: 11 }}
            />
            <YAxis
              stroke="#94a3b8"
              tick={{ fill: '#94a3b8', fontSize: 11 }}
            />
            <Tooltip content={<CustomTooltip />} />
            {showLegend && (
              <Legend
                wrapperStyle={{ paddingTop: '10px' }}
                formatter={(value) => (
                  <span style={{ color: '#94a3b8', fontSize: '12px' }}>
                    {formatMetricName(value)}
                  </span>
                )}
              />
            )}
            {metrics.map((metric) => (
              <Line
                key={metric}
                type="monotone"
                dataKey={metric}
                stroke={metricColors[metric]}
                strokeWidth={2}
                dot={false}
                name={metric}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex items-center justify-center h-full text-opsgrid-text-secondary">
          <Activity className="w-8 h-8 mr-2 opacity-50" />
          <span>Waiting for telemetry data...</span>
        </div>
      )}
    </ChartContainer>
  );
};

export default RealtimeTelemetryChart;
