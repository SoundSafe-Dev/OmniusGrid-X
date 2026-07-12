import { FC, useEffect, useState } from 'react';
import Plot from 'react-plotly.js';
import type { Config, Layout, PlotData } from 'plotly.js';
import { Card } from '../ui';
import { websocketManager } from '../../api';

interface StreamDataPoint {
  timestamp: number;
  [key: string]: number | string;
}

interface RealtimeStreamChartProps {
  assetId: string;
  metrics?: string[];
  maxPoints?: number;
  updateInterval?: number;
  title?: string;
  height?: number;
}

export const RealtimeStreamChart: FC<RealtimeStreamChartProps> = ({
  assetId,
  metrics = ['value'],
  maxPoints = 100,
  updateInterval = 1000,
  title = 'Real-time Stream',
  height = 400
}) => {
  const [data, setData] = useState<StreamDataPoint[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  
  const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899'];
  
  // Initialize with empty data
  useEffect(() => {
    const now = Date.now();
    const initialData: StreamDataPoint[] = [];
    for (let i = maxPoints; i >= 0; i--) {
      initialData.push({
        timestamp: now - i * updateInterval,
        ...metrics.reduce((acc, metric) => ({ ...acc, [metric]: 0 }), {})
      });
    }
    setData(initialData);
  }, [maxPoints, updateInterval, metrics]);
  
  // Subscribe to WebSocket
  useEffect(() => {
    const unsubscribe = websocketManager.subscribe<{
      asset_id: string;
      telemetry: Record<string, number | string>;
    }>('telemetry', (message) => {
      if (message.asset_id !== assetId) return;
      
      const newPoint: StreamDataPoint = {
        timestamp: Date.now(),
        ...metrics.reduce((acc, metric) => {
          const value = message.telemetry[metric];
          return { ...acc, [metric]: typeof value === 'number' ? value : parseFloat(value as string) || 0 };
        }, {})
      };
      
      setData(prev => {
        const updated = [...prev, newPoint];
        if (updated.length > maxPoints) {
          return updated.slice(-maxPoints);
        }
        return updated;
      });
      
      setIsConnected(true);
    });
    
    // Connection status
    const unsubscribeStatus = websocketManager.subscribe<{ connected: boolean }>(
      'connection_status',
      ({ connected }) => setIsConnected(connected)
    );
    
    return () => {
      unsubscribe();
      unsubscribeStatus();
    };
  }, [assetId, metrics, maxPoints]);
  
  // Prepare Plotly data
  const plotData = metrics.map((metric, index): Partial<PlotData> => ({
    type: 'scattergl',
    mode: 'lines',
    name: metric,
    x: data.map(d => d.timestamp),
    y: data.map(d => d[metric] as number),
    line: { color: COLORS[index % COLORS.length], width: 2 }
  }));

  const layout: Partial<Layout> = {
    title: {
      text: title,
      font: { size: 18, color: '#94a3b8' }
    },
    xaxis: {
      title: { text: 'Time' },
      type: 'date',
      color: '#94a3b8',
      gridcolor: '#334155'
    },
    yaxis: {
      title: { text: 'Value' },
      color: '#94a3b8',
      gridcolor: '#334155'
    },
    plot_bgcolor: '#1e293b',
    paper_bgcolor: '#0f172a',
    font: { color: '#94a3b8' },
    margin: { l: 60, r: 40, t: 60, b: 60 },
    showlegend: true
  };

  const config: Partial<Config> = {
    responsive: true,
    displayModeBar: true,
    displaylogo: false
  };
  
  return (
    <Card title={title} className="w-full">
      <div className="mb-4 flex items-center gap-4">
        <div className={`flex items-center gap-2 ${isConnected ? 'text-green-500' : 'text-red-500'}`}>
          <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-sm">{isConnected ? 'Live' : 'Disconnected'}</span>
        </div>
        <span className="text-sm text-opsgrid-text-secondary">
          Points: {data.length}
        </span>
      </div>
      
      <Plot
        data={plotData}
        layout={layout}
        config={config}
        style={{ width: '100%', height: `${height}px` }}
        useResizeHandler={true}
      />
    </Card>
  );
};

export default RealtimeStreamChart;
