import { FC, useState } from 'react';
import { AlertTriangle, Wrench } from 'lucide-react';
import { Card, Badge } from '../../components';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  Legend,
  ResponsiveContainer
} from 'recharts';

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

  // Mock data for development - will be replaced with API calls
  const mockTemperatureData = [
    { time: '00:00', nozzle: 210, bed: 60 },
    { time: '04:00', nozzle: 215, bed: 62 },
    { time: '08:00', nozzle: 220, bed: 65 },
    { time: '12:00', nozzle: 225, bed: 68 },
    { time: '16:00', nozzle: 230, bed: 70 },
    { time: '20:00', nozzle: 228, bed: 67 },
    { time: '24:00', nozzle: 222, bed: 64 },
  ];

  const mockVibrationData = [
    { time: '00:00', vibration: 2.1 },
    { time: '04:00', vibration: 2.3 },
    { time: '08:00', vibration: 3.5 },
    { time: '12:00', vibration: 4.2 },
    { time: '16:00', vibration: 3.8 },
    { time: '20:00', vibration: 2.9 },
    { time: '24:00', vibration: 2.4 },
  ];

  const mockOEEData = [
    { time: 'Mon', availability: 85, performance: 90, quality: 95 },
    { time: 'Tue', availability: 88, performance: 92, quality: 94 },
    { time: 'Wed', availability: 82, performance: 88, quality: 93 },
    { time: 'Thu', availability: 90, performance: 94, quality: 96 },
    { time: 'Fri', availability: 87, performance: 91, quality: 95 },
    { time: 'Sat', availability: 75, performance: 85, quality: 92 },
    { time: 'Sun', availability: 70, performance: 80, quality: 90 },
  ];

  const mockHealthDistribution = [
    { status: 'Excellent', count: 12 },
    { status: 'Good', count: 8 },
    { status: 'Fair', count: 3 },
    { status: 'Poor', count: 1 },
  ];

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
          {/* Temperature Trend Chart */}
          <div>
            <h3 className="text-lg font-semibold mb-4 text-opsgrid-text-primary">Temperature Trends</h3>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={mockTemperatureData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="time" stroke="#9CA3AF" />
                  <YAxis stroke="#9CA3AF" />
                  <RechartsTooltip 
                    contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                    itemStyle={{ color: '#F3F4F6' }}
                  />
                  <Legend />
                  <Line 
                    type="monotone" 
                    dataKey="nozzle" 
                    stroke="#3B82F6" 
                    strokeWidth={2}
                    name="Nozzle Temp (°C)"
                  />
                  <Line 
                    type="monotone" 
                    dataKey="bed" 
                    stroke="#10B981" 
                    strokeWidth={2}
                    name="Bed Temp (°C)"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Vibration Analysis Chart */}
          <div>
            <h3 className="text-lg font-semibold mb-4 text-opsgrid-text-primary">Vibration Analysis</h3>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={mockVibrationData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="time" stroke="#9CA3AF" />
                  <YAxis stroke="#9CA3AF" />
                  <RechartsTooltip 
                    contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                    itemStyle={{ color: '#F3F4F6' }}
                  />
                  <Area 
                    type="monotone" 
                    dataKey="vibration" 
                    stroke="#F59E0B" 
                    fill="#F59E0B"
                    fillOpacity={0.3}
                    name="Vibration (g)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* OEE Over Time Chart */}
          <div>
            <h3 className="text-lg font-semibold mb-4 text-opsgrid-text-primary">OEE Metrics Over Time</h3>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={mockOEEData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="time" stroke="#9CA3AF" />
                  <YAxis stroke="#9CA3AF" domain={[0, 100]} />
                  <RechartsTooltip 
                    contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                    itemStyle={{ color: '#F3F4F6' }}
                  />
                  <Legend />
                  <Line 
                    type="monotone" 
                    dataKey="availability" 
                    stroke="#3B82F6" 
                    strokeWidth={2}
                    name="Availability (%)"
                  />
                  <Line 
                    type="monotone" 
                    dataKey="performance" 
                    stroke="#10B981" 
                    strokeWidth={2}
                    name="Performance (%)"
                  />
                  <Line 
                    type="monotone" 
                    dataKey="quality" 
                    stroke="#8B5CF6" 
                    strokeWidth={2}
                    name="Quality (%)"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Asset Health Distribution Chart */}
          <div>
            <h3 className="text-lg font-semibold mb-4 text-opsgrid-text-primary">Asset Health Distribution</h3>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={mockHealthDistribution}>
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
    </div>
  );
};
