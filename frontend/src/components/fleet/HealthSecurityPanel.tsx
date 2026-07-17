import { FC, useState, useEffect } from 'react';
import {
  Activity, AlertTriangle, Shield, User, Truck,
  Wrench, CheckCircle
} from 'lucide-react';
import { fleetHealthApi } from '../../api';
import type { VehicleHealthStatus, DiagnosticTroubleCode, SecurityEvent, DriverSafetyMetrics } from '../../types';

const getStatusColor = (status: string) => {
  switch (status) {
    case 'online': return 'bg-green-100 text-green-700 border-green-300';
    case 'offline': return 'bg-red-100 text-red-700 border-red-300';
    case 'warning': return 'bg-yellow-100 text-yellow-700 border-yellow-300';
    case 'maintenance': return 'bg-blue-100 text-blue-700 border-blue-300';
    default: return 'bg-gray-100 text-gray-700 border-gray-300';
  }
};

const getDtcSeverityColor = (severity: string) => {
  switch (severity) {
    case 'critical': return 'bg-red-500';
    case 'high': return 'bg-orange-500';
    case 'medium': return 'bg-yellow-500';
    default: return 'bg-blue-500';
  }
};

const getSecuritySeverityColor = (severity: string) => {
  switch (severity) {
    case 'critical': return 'text-red-600 bg-red-50';
    case 'high': return 'text-orange-600 bg-orange-50';
    case 'medium': return 'text-yellow-600 bg-yellow-50';
    default: return 'text-blue-600 bg-blue-50';
  }
};

export const HealthSecurityPanel: FC = () => {
  const [vehicles, setVehicles] = useState<VehicleHealthStatus[]>([]);
  const [dtcs, setDtcs] = useState<DiagnosticTroubleCode[]>([]);
  const [securityEvents, setSecurityEvents] = useState<SecurityEvent[]>([]);
  const [driverMetrics, setDriverMetrics] = useState<DriverSafetyMetrics[]>([]);
  const [selectedVehicle, setSelectedVehicle] = useState<string | null>(null);
  const [stats, setStats] = useState({
    total: 0, online: 0, offline: 0, maintenance: 0, warning: 0,
    avgSafetyScore: 0, totalActiveDTCs: 0, criticalDTCs: 0,
  });

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    const [vehiclesData, dtcsData, securityData, metricsData, statsData] = await Promise.all([
      fleetHealthApi.getAllVehicleHealth(),
      fleetHealthApi.getAllDTCs(),
      fleetHealthApi.getSecurityEvents(),
      fleetHealthApi.getDriverSafetyMetrics(),
      fleetHealthApi.getHealthStatistics(),
    ]);
    setVehicles(vehiclesData);
    setDtcs(dtcsData);
    setSecurityEvents(securityData);
    setDriverMetrics(metricsData);
    setStats(statsData);
  };

  const handleAcknowledgeSecurity = async (eventId: string) => {
    await fleetHealthApi.acknowledgeSecurityEvent(eventId);
    setSecurityEvents(prev => prev.map(e => e.id === eventId ? { ...e, acknowledged: true } : e));
  };

  const unacknowledgedSecurity = securityEvents.filter(e => !e.acknowledged);
  const criticalSecurity = unacknowledgedSecurity.filter(e => e.severity === 'critical');

  return (
    <div className="space-y-4">
      {/* Critical Security Banner */}
      {criticalSecurity.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 flex items-center gap-3 animate-pulse">
          <Shield className="w-5 h-5 text-red-600" />
          <span className="font-semibold text-red-700">
            {criticalSecurity.length} Critical Security Event{criticalSecurity.length > 1 ? 's' : ''}!
          </span>
          <button 
            onClick={() => criticalSecurity.forEach(e => handleAcknowledgeSecurity(e.id))}
            className="ml-auto text-sm bg-red-600 text-white px-3 py-1 rounded hover:bg-red-700"
          >
            Acknowledge All
          </button>
        </div>
      )}

      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <Truck className="w-5 h-5 text-green-500" />
            <span className="text-sm text-gray-600">Online</span>
          </div>
          <p className="text-2xl font-bold text-green-600">{stats.online}</p>
        </div>
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-5 h-5 text-yellow-500" />
            <span className="text-sm text-gray-600">Warnings</span>
          </div>
          <p className="text-2xl font-bold text-yellow-600">{stats.warning}</p>
        </div>
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <Wrench className="w-5 h-5 text-blue-500" />
            <span className="text-sm text-gray-600">Active DTCs</span>
          </div>
          <p className="text-2xl font-bold text-blue-600">{stats.totalActiveDTCs}</p>
          {stats.criticalDTCs > 0 && (
            <p className="text-xs text-red-500">{stats.criticalDTCs} critical</p>
          )}
        </div>
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <User className="w-5 h-5 text-purple-500" />
            <span className="text-sm text-gray-600">Avg Safety Score</span>
          </div>
          <p className={`text-2xl font-bold ${stats.avgSafetyScore >= 85 ? 'text-green-600' : stats.avgSafetyScore >= 70 ? 'text-yellow-600' : 'text-red-600'}`}>
            {stats.avgSafetyScore}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Vehicle Health Grid */}
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg">
          <div className="p-3 border-b border-opsgrid-border">
            <h3 className="font-semibold flex items-center gap-2">
              <Activity className="w-5 h-5 text-opsgrid-primary" />
              Vehicle Health Status
            </h3>
          </div>
          <div className="p-3 grid grid-cols-1 gap-2 max-h-[400px] overflow-y-auto">
            {vehicles.map(vehicle => (
              <div 
                key={vehicle.vehicleId}
                className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                  selectedVehicle === vehicle.vehicleId ? 'bg-opsgrid-bg border-opsgrid-primary' : 'bg-white border-gray-200 hover:border-gray-300'
                }`}
                onClick={() => setSelectedVehicle(vehicle.vehicleId === selectedVehicle ? null : vehicle.vehicleId)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`w-3 h-3 rounded-full ${
                      vehicle.status === 'online' ? 'bg-green-500' :
                      vehicle.status === 'warning' ? 'bg-yellow-500' :
                      vehicle.status === 'maintenance' ? 'bg-blue-500' : 'bg-red-500'
                    }`} />
                    <div>
                      <p className="font-medium">{vehicle.vehicleNumber}</p>
                      <p className="text-xs text-gray-500">{vehicle.driverName || 'No Driver'}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <span className={`px-2 py-1 rounded text-xs font-medium ${getStatusColor(vehicle.status)}`}>
                      {vehicle.status}
                    </span>
                    <p className="text-xs text-gray-500 mt-1">
                      {vehicle.dtcs.length} DTC{vehicle.dtcs.length !== 1 ? 's' : ''}
                    </p>
                  </div>
                </div>
                {selectedVehicle === vehicle.vehicleId && (
                  <div className="mt-3 pt-3 border-t border-gray-200 text-sm">
                    <div className="grid grid-cols-2 gap-2">
                      <p><span className="text-gray-500">Safety Score:</span> {vehicle.safetyScore}</p>
                      <p><span className="text-gray-500">Odometer:</span> {vehicle.odometer.toLocaleString()} mi</p>
                      <p><span className="text-gray-500">Engine Hours:</span> {vehicle.engineHours}</p>
                      <p><span className="text-gray-500">Fuel:</span> {vehicle.fuelLevel}%</p>
                    </div>
                    <p className="text-gray-500 mt-2">
                      Last Communication: {new Date(vehicle.lastCommunication).toLocaleString()}
                    </p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Side Panel */}
        <div className="space-y-4">
          {/* Active DTCs */}
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg">
            <div className="p-3 border-b border-opsgrid-border">
              <h3 className="font-semibold flex items-center gap-2">
                <Wrench className="w-5 h-5 text-opsgrid-primary" />
                Active Diagnostic Codes
              </h3>
            </div>
            <div className="max-h-[200px] overflow-y-auto">
              {dtcs.slice(0, 10).map(dtc => (
                <div key={`${dtc.code}-${dtc.vehicleId}`} className="p-3 border-b border-opsgrid-border">
                  <div className="flex items-start gap-2">
                    <div className={`w-2 h-2 rounded-full mt-1.5 ${getDtcSeverityColor(dtc.severity)}`} />
                    <div className="flex-1">
                      <p className="font-medium text-sm">{dtc.code}</p>
                      <p className="text-xs text-gray-600">{dtc.description}</p>
                      <p className="text-xs text-gray-500 mt-1">{dtc.vehicleNumber} • {dtc.system}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Security Events */}
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg">
            <div className="p-3 border-b border-opsgrid-border">
              <h3 className="font-semibold flex items-center gap-2">
                <Shield className="w-5 h-5 text-opsgrid-primary" />
                Security Events
              </h3>
            </div>
            <div className="max-h-[200px] overflow-y-auto">
              {securityEvents.filter(e => !e.acknowledged).slice(0, 5).map(event => (
                <div key={event.id} className="p-3 border-b border-opsgrid-border">
                  <div className="flex items-start gap-2">
                    <div className={`p-1.5 rounded ${getSecuritySeverityColor(event.severity)}`}>
                      <AlertTriangle className="w-4 h-4" />
                    </div>
                    <div className="flex-1">
                      <p className="font-medium text-sm">{event.eventType.replace(/_/g, ' ')}</p>
                      <p className="text-xs text-gray-600">{event.description}</p>
                      <p className="text-xs text-gray-500 mt-1">{event.vehicleNumber} • {new Date(event.timestamp).toLocaleString()}</p>
                    </div>
                    <button 
                      onClick={() => handleAcknowledgeSecurity(event.id)}
                      className="p-1 text-green-600 hover:bg-green-50 rounded"
                    >
                      <CheckCircle className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Driver Safety Scoreboard */}
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg">
            <div className="p-3 border-b border-opsgrid-border">
              <h3 className="font-semibold flex items-center gap-2">
                <User className="w-5 h-5 text-opsgrid-primary" />
                Driver Safety Scores
              </h3>
            </div>
            <div className="max-h-[150px] overflow-y-auto">
              {driverMetrics.sort((a, b) => b.overallScore - a.overallScore).slice(0, 5).map(driver => (
                <div key={driver.driverId} className="p-3 border-b border-opsgrid-border flex items-center justify-between">
                  <div>
                    <p className="font-medium text-sm">{driver.driverName}</p>
                    <p className={`text-xs ${
                      driver.trend === 'improving' ? 'text-green-500' :
                      driver.trend === 'declining' ? 'text-red-500' : 'text-gray-500'
                    }`}>
                      {driver.trend}
                    </p>
                  </div>
                  <div className={`text-lg font-bold ${
                    driver.overallScore >= 90 ? 'text-green-600' :
                    driver.overallScore >= 70 ? 'text-yellow-600' : 'text-red-600'
                  }`}>
                    {driver.overallScore}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
