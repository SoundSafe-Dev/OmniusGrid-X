import { FC, useState, useEffect } from 'react';
import {
  Fuel, Clock, Calendar, Activity, DollarSign,
  Wrench, TrendingUp, Truck
} from 'lucide-react';
import { kpiApi } from '../../api';
import type {
  FuelEfficiencyData, IdleTimeData, OnTimePerformanceData,
  VehicleHealthScoreData, CostPerMileData, DTCCountData
} from '../../types';
// TimeRange is ambiguously re-exported from '../../types' (common.ts and logistics.ts
// both export a TimeRange), so import the string-union declaration directly.
import type { TimeRange } from '../../types/logistics';

const TimeRangeSelector: FC<{ value: TimeRange; onChange: (r: TimeRange) => void }> = ({ value, onChange }) => (
  <select 
    value={value} 
    onChange={(e) => onChange(e.target.value as TimeRange)}
    className="px-3 py-1 bg-opsgrid-panel border border-opsgrid-border rounded text-sm"
  >
    <option value="today">Today</option>
    <option value="week">This Week</option>
    <option value="month">This Month</option>
    <option value="quarter">This Quarter</option>
    <option value="year">This Year</option>
  </select>
);

const Widget: FC<{ title: string; icon: React.ReactNode; children: React.ReactNode; className?: string }> = 
({ title, icon, children, className = '' }) => (
  <div className={`bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4 ${className}`}>
    <div className="flex items-center justify-between mb-4">
      <h3 className="font-semibold flex items-center gap-2">
        {icon}
        {title}
      </h3>
    </div>
    {children}
  </div>
);

export const PerformancePanel: FC = () => {
  const [timeRange, setTimeRange] = useState<TimeRange>('month');
  const [fuelData, setFuelData] = useState<FuelEfficiencyData | null>(null);
  const [idleData, setIdleData] = useState<IdleTimeData | null>(null);
  const [performanceData, setPerformanceData] = useState<OnTimePerformanceData | null>(null);
  const [healthData, setHealthData] = useState<VehicleHealthScoreData | null>(null);
  const [costData, setCostData] = useState<CostPerMileData | null>(null);
  const [dtcData, setDtcData] = useState<DTCCountData | null>(null);

  useEffect(() => {
    loadData();
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing; adding deps changes retrigger behavior (FS-54)
  }, [timeRange]);

  const loadData = async () => {
    // kpiApi's TimeRange parameter currently resolves through the ambiguous
    // '../../types' barrel; bridge until that re-export is disambiguated. This
    // cast stays valid (and becomes a no-op) once the barrel exports the union.
    const range = timeRange as unknown as Parameters<typeof kpiApi.getFuelEfficiency>[0];
    const [fuel, idle, performance, health, cost, dtc] = await Promise.all([
      kpiApi.getFuelEfficiency(range),
      kpiApi.getIdleTime(range),
      kpiApi.getOnTimePerformance(range),
      kpiApi.getVehicleHealthScore(),
      kpiApi.getCostPerMile(range),
      kpiApi.getDTCCount(),
    ]);
    setFuelData(fuel);
    setIdleData(idle);
    setPerformanceData(performance);
    setHealthData(health);
    setCostData(cost);
    setDtcData(dtc);
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">Fleet Performance Dashboard</h2>
        <TimeRangeSelector value={timeRange} onChange={setTimeRange} />
      </div>

      {/* KPI Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Fuel Efficiency */}
        <Widget title="Fuel Efficiency" icon={<Fuel className="w-5 h-5 text-green-500" />}>
          {fuelData && (
            <>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-bold">{fuelData.fleetAverage.toFixed(1)}</span>
                <span className="text-gray-500">{fuelData.unit === 'mpg' ? 'MPG' : 'L/100km'}</span>
              </div>
              <p className="text-sm text-gray-600 mt-2">
                {fuelData.totalFuelConsumed.toLocaleString()} gal consumed • {fuelData.totalDistance.toLocaleString()} mi
              </p>
              <div className="mt-4 space-y-2">
                <p className="text-xs text-gray-500 font-medium">Top Performers</p>
                {fuelData.bestPerformers.slice(0, 3).map(v => (
                  <div key={v.vehicleId} className="flex justify-between text-sm">
                    <span className="flex items-center gap-1">
                      <Truck className="w-3 h-3" />
                      {v.vehicleNumber}
                    </span>
                    <span className="font-medium text-green-600">{v.efficiency.toFixed(1)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </Widget>

        {/* Idle Time */}
        <Widget title="Idle Time" icon={<Clock className="w-5 h-5 text-yellow-500" />}>
          {idleData && (
            <>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-bold">{idleData.totalHours.toFixed(1)}</span>
                <span className="text-gray-500">hours</span>
              </div>
              <p className="text-sm text-gray-600 mt-2">
                {idleData.percentageOfRuntime.toFixed(1)}% of runtime • ${idleData.costImpact.toLocaleString()} cost
              </p>
              <div className="mt-4">
                <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-yellow-500 rounded-full"
                    style={{ width: `${Math.min(idleData.percentageOfRuntime * 2, 100)}%` }}
                  />
                </div>
                <p className="text-xs text-gray-500 mt-1">Fleet idle percentage</p>
              </div>
            </>
          )}
        </Widget>

        {/* On-Time Performance */}
        <Widget title="On-Time Performance" icon={<Calendar className="w-5 h-5 text-blue-500" />}>
          {performanceData && (
            <>
              <div className="flex items-baseline gap-2">
                <span className={`text-3xl font-bold ${
                  performanceData.overallPercentage >= 90 ? 'text-green-600' : 
                  performanceData.overallPercentage >= 75 ? 'text-yellow-600' : 'text-red-600'
                }`}>
                  {performanceData.overallPercentage.toFixed(1)}%
                </span>
              </div>
              <p className="text-sm text-gray-600 mt-2">
                {performanceData.onTimeCount} on-time • {performanceData.lateCount} late deliveries
              </p>
              <div className="mt-4 grid grid-cols-2 gap-2">
                <div className="bg-green-50 rounded p-2 text-center">
                  <p className="text-lg font-bold text-green-600">{performanceData.onTimeCount}</p>
                  <p className="text-xs text-gray-600">On Time</p>
                </div>
                <div className="bg-red-50 rounded p-2 text-center">
                  <p className="text-lg font-bold text-red-600">{performanceData.lateCount}</p>
                  <p className="text-xs text-gray-600">Late</p>
                </div>
              </div>
            </>
          )}
        </Widget>

        {/* Vehicle Health Score */}
        <Widget title="Vehicle Health Score" icon={<Activity className="w-5 h-5 text-purple-500" />}>
          {healthData && (
            <>
              <div className="flex items-baseline gap-2">
                <span className={`text-3xl font-bold ${
                  healthData.fleetAverage >= 85 ? 'text-green-600' : 
                  healthData.fleetAverage >= 70 ? 'text-yellow-600' : 'text-red-600'
                }`}>
                  {healthData.fleetAverage.toFixed(0)}
                </span>
                <span className="text-gray-500">/100</span>
              </div>
              <div className="mt-4 space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="flex items-center gap-1 text-green-600">
                    <div className="w-2 h-2 rounded-full bg-green-500" />
                    Healthy ({healthData.healthyCount})
                  </span>
                  <span className="flex items-center gap-1 text-yellow-600">
                    <div className="w-2 h-2 rounded-full bg-yellow-500" />
                    Warning ({healthData.warningCount})
                  </span>
                  <span className="flex items-center gap-1 text-red-600">
                    <div className="w-2 h-2 rounded-full bg-red-500" />
                    Critical ({healthData.criticalCount})
                  </span>
                </div>
              </div>
            </>
          )}
        </Widget>

        {/* Cost Per Mile */}
        <Widget title="Cost Per Mile" icon={<DollarSign className="w-5 h-5 text-green-600" />}>
          {costData && (
            <>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-bold">${costData.averageCostPerMile.toFixed(2)}</span>
                <span className="text-gray-500">/mile</span>
              </div>
              <p className="text-sm text-gray-600 mt-2">
                ${costData.totalCost.toLocaleString()} total • {costData.totalMiles.toLocaleString()} miles
              </p>
              <div className="mt-4 space-y-1">
                {Object.entries(costData.breakdown).map(([category, amount]) => (
                  <div key={category} className="flex justify-between text-sm">
                    <span className="capitalize text-gray-600">{category}</span>
                    <span className="font-medium">${amount.toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </Widget>

        {/* DTC Count */}
        <Widget title="Active Diagnostic Codes" icon={<Wrench className="w-5 h-5 text-orange-500" />}>
          {dtcData && (
            <>
              <div className="flex items-baseline gap-2">
                <span className={`text-3xl font-bold ${
                  dtcData.totalActive === 0 ? 'text-green-600' : 
                  dtcData.criticalCount === 0 ? 'text-yellow-600' : 'text-red-600'
                }`}>
                  {dtcData.totalActive}
                </span>
                <span className="text-gray-500">active codes</span>
              </div>
              {dtcData.criticalCount > 0 && (
                <p className="text-sm text-red-600 mt-2 flex items-center gap-1">
                  <TrendingUp className="w-4 h-4" />
                  {dtcData.criticalCount} critical codes require immediate attention
                </p>
              )}
              <div className="mt-4">
                <p className="text-xs text-gray-500 font-medium mb-2">By System</p>
                <div className="space-y-1">
                  {Object.entries(dtcData.bySystem)
                    .filter(([_, count]) => count > 0)
                    .slice(0, 4)
                    .map(([system, count]) => (
                      <div key={system} className="flex justify-between text-sm">
                        <span className="capitalize text-gray-600">{system}</span>
                        <span className="font-medium">{count}</span>
                      </div>
                    ))}
                </div>
              </div>
            </>
          )}
        </Widget>
      </div>

      {/* Trend Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Fuel Efficiency Trend */}
        {fuelData && fuelData.trend.length > 0 && (
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
            <h3 className="font-semibold mb-4 flex items-center gap-2">
              <Fuel className="w-5 h-5 text-green-500" />
              Fuel Efficiency Trend
            </h3>
            <div className="h-48 flex items-end gap-2">
              {fuelData.trend.map((point, i) => {
                const maxVal = Math.max(...fuelData.trend.map(p => p.value));
                const height = maxVal > 0 ? (point.value / maxVal) * 100 : 0;
                return (
                  <div key={i} className="flex-1 flex flex-col items-center gap-1">
                    <div 
                      className="w-full bg-green-500 rounded-t hover:bg-green-600 transition-all relative group"
                      style={{ height: `${Math.max(height, 5)}%` }}
                    >
                      <div className="absolute -top-8 left-1/2 -translate-x-1/2 bg-gray-800 text-white text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 whitespace-nowrap">
                        {point.value.toFixed(1)} MPG
                      </div>
                    </div>
                    <span className="text-xs text-gray-500 transform -rotate-45 origin-top-left translate-y-2">
                      {new Date(point.date).toLocaleDateString(undefined, { month: 'short' })}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* On-Time Performance Trend */}
        {performanceData && performanceData.trend.length > 0 && (
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
            <h3 className="font-semibold mb-4 flex items-center gap-2">
              <Calendar className="w-5 h-5 text-blue-500" />
              On-Time Performance Trend
            </h3>
            <div className="h-48 flex items-end gap-2">
              {performanceData.trend.map((point, i) => {
                const height = point.percentage;
                return (
                  <div key={i} className="flex-1 flex flex-col items-center gap-1">
                    <div 
                      className={`w-full rounded-t transition-all relative group ${
                        point.percentage >= 90 ? 'bg-green-500' : 
                        point.percentage >= 75 ? 'bg-yellow-500' : 'bg-red-500'
                      }`}
                      style={{ height: `${Math.max(height, 5)}%` }}
                    >
                      <div className="absolute -top-8 left-1/2 -translate-x-1/2 bg-gray-800 text-white text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 whitespace-nowrap">
                        {point.percentage.toFixed(1)}%
                      </div>
                    </div>
                    <span className="text-xs text-gray-500 transform -rotate-45 origin-top-left translate-y-2">
                      {new Date(point.date).toLocaleDateString(undefined, { month: 'short' })}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
