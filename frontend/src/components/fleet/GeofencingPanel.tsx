import { FC, useState, useEffect } from 'react';
import { MapContainer, TileLayer, Circle } from 'react-leaflet';
import { 
  AlertTriangle, Plus, Trash2, Edit2, Bell, Volume2, 
  MapPin, CheckCircle, XCircle, Clock, X
} from 'lucide-react';
import { geofencingApi } from '../../api';
import type { GeofenceZoneExtended, GeofenceAlertExtended } from '../../types';
import 'leaflet/dist/leaflet.css';

const getZoneColor = (color: string) => {
  switch (color) {
    case 'green': return '#22c55e';
    case 'yellow': return '#eab308';
    case 'red': return '#ef4444';
    default: return '#6b7280';
  }
};

const getSeverityColor = (severity: string) => {
  switch (severity) {
    case 'critical': return 'text-red-600 bg-red-50';
    case 'warning': return 'text-yellow-600 bg-yellow-50';
    default: return 'text-blue-600 bg-blue-50';
  }
};

// Sound notification component
const playAlertSound = () => {
  const audio = new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2/LDciUFLIHO8tiJNwgZaLvt559NEAxQp+PwtmMcBjiR1/LMeSwFJHfH8N2QQAoUXrTp66hVFApGn+DyvmwhBSuBzvLZiTYIG2m98OScTgwOUarm7blmFgU7k9n1unEiBC13yO/eizEIHWq+8+OWT');
  audio.play().catch(() => {});
};

interface GeofencingPanelProps {
  onAlert?: (alert: GeofenceAlertExtended) => void;
}

export const GeofencingPanel: FC<GeofencingPanelProps> = ({ onAlert }) => {
  const [zones, setZones] = useState<GeofenceZoneExtended[]>([]);
  const [alerts, setAlerts] = useState<GeofenceAlertExtended[]>([]);
  const [selectedZone, setSelectedZone] = useState<GeofenceZoneExtended | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [showAlertPanel, setShowAlertPanel] = useState(true);

  useEffect(() => {
    loadData();
    const unsubscribe = geofencingApi.subscribeToAlerts((alert) => {
      setAlerts(prev => [alert, ...prev]);
      if (soundEnabled && alert.severity === 'critical') {
        playAlertSound();
      }
      onAlert?.(alert);
    });
    return unsubscribe;
  }, [soundEnabled]);

  const loadData = async () => {
    setIsLoading(true);
    const [zonesData, alertsData] = await Promise.all([
      geofencingApi.getZones(),
      geofencingApi.getAlerts(),
    ]);
    setZones(zonesData);
    setAlerts(alertsData);
    setIsLoading(false);
  };

  const handleAcknowledge = async (alertId: string) => {
    await geofencingApi.acknowledgeAlert(alertId);
    setAlerts(prev => prev.map(a => a.id === alertId ? { ...a, acknowledged: true } : a));
  };

  const unacknowledgedAlerts = alerts.filter(a => !a.acknowledged);
  const criticalAlerts = unacknowledgedAlerts.filter(a => a.severity === 'critical');

  return (
    <div className="space-y-4">
      {/* Critical Alert Banner */}
      {criticalAlerts.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 flex items-center gap-3 animate-pulse">
          <AlertTriangle className="w-5 h-5 text-red-600" />
          <span className="font-semibold text-red-700">
            {criticalAlerts.length} Critical Geofence Alert{criticalAlerts.length > 1 ? 's' : ''}!
          </span>
          <button 
            onClick={() => criticalAlerts.forEach(a => handleAcknowledge(a.id))}
            className="ml-auto text-sm bg-red-600 text-white px-3 py-1 rounded hover:bg-red-700"
          >
            Acknowledge All
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Map */}
        <div className="lg:col-span-2 bg-opsgrid-panel border border-opsgrid-border rounded-lg overflow-hidden">
          <div className="h-[500px]">
            <MapContainer
              center={[39.8283, -98.5795]}
              zoom={4}
              style={{ height: '100%', width: '100%' }}
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              {zones.filter(z => z.isActive).map(zone => (
                <Circle
                  key={zone.id}
                  center={[zone.center!.latitude, zone.center!.longitude]}
                  radius={zone.radius}
                  pathOptions={{
                    color: getZoneColor(zone.color),
                    fillColor: getZoneColor(zone.color),
                    fillOpacity: selectedZone?.id === zone.id ? 0.4 : 0.2,
                    weight: selectedZone?.id === zone.id ? 3 : 2,
                    dashArray: zone.color === 'yellow' ? '5, 10' : undefined,
                  }}
                  eventHandlers={{
                    click: (e) => {
                      e.originalEvent.stopPropagation();
                      setSelectedZone(zone);
                    },
                  }}
                />
              ))}
            </MapContainer>
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-4 relative z-10">
          {/* Controls */}
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-3 flex items-center justify-between">
            <span className="font-semibold">Geofence Zones</span>
            <div className="flex gap-2">
              <button 
                onClick={() => setSoundEnabled(!soundEnabled)}
                className={`p-2 rounded ${soundEnabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}
                title="Toggle sound alerts"
              >
                <Volume2 className="w-4 h-4" />
              </button>
              <button className="p-2 bg-opsgrid-primary text-white rounded hover:bg-opsgrid-accent">
                <Plus className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Zone List */}
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg">
            <div className="max-h-[200px] overflow-y-auto">
              {zones.map(zone => (
                <div 
                  key={zone.id}
                  className={`p-3 border-b border-opsgrid-border cursor-pointer hover:bg-opsgrid-bg ${
                    selectedZone?.id === zone.id ? 'bg-opsgrid-bg' : ''
                  }`}
                  onClick={() => setSelectedZone(zone)}
                >
                  <div className="flex items-center gap-2">
                    <span 
                      className="w-3 h-3 rounded-full" 
                      style={{ backgroundColor: getZoneColor(zone.color) }}
                    />
                    <span className="font-medium text-sm">{zone.name}</span>
                    {!zone.isActive && (
                      <span className="text-xs bg-gray-200 px-2 py-0.5 rounded">Inactive</span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mt-1">{zone.vehiclesInside.length} vehicles inside</p>
                </div>
              ))}
            </div>
          </div>

          {/* Selected Zone Details */}
          {selectedZone && (
            <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="font-semibold">{selectedZone.name}</span>
                <div className="flex gap-1">
                  <button className="p-1 text-gray-600 hover:text-opsgrid-primary">
                    <Edit2 className="w-4 h-4" />
                  </button>
                  <button className="p-1 text-gray-600 hover:text-red-600">
                    <Trash2 className="w-4 h-4" />
                  </button>
                  <button 
                    onClick={() => setSelectedZone(null)}
                    className="p-1 text-gray-400 hover:text-gray-600"
                    title="Close"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              </div>
              <p className="text-sm text-gray-600 mb-2">{selectedZone.description}</p>
              <div className="text-xs space-y-1">
                <p>Type: {selectedZone.type}</p>
                <p>Radius: {(selectedZone.radius! / 1000).toFixed(1)} km</p>
                <p>Alert on Entry: {selectedZone.alertRules.onEntry ? 'Yes' : 'No'}</p>
                <p>Alert on Exit: {selectedZone.alertRules.onExit ? 'Yes' : 'No'}</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Alert Panel */}
      {showAlertPanel && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg">
          <div className="p-3 border-b border-opsgrid-border flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bell className="w-5 h-5 text-opsgrid-primary" />
              <span className="font-semibold">Alert History</span>
              {unacknowledgedAlerts.length > 0 && (
                <span className="bg-red-500 text-white text-xs px-2 py-0.5 rounded-full">
                  {unacknowledgedAlerts.length}
                </span>
              )}
            </div>
            <button onClick={() => setShowAlertPanel(false)}>
              <XCircle className="w-5 h-5 text-gray-400" />
            </button>
          </div>
          <div className="max-h-[250px] overflow-y-auto">
            {alerts.slice(0, 20).map(alert => (
              <div 
                key={alert.id}
                className={`p-3 border-b border-opsgrid-border flex items-start gap-3 ${
                  alert.acknowledged ? 'opacity-50' : ''
                }`}
              >
                <div className={`p-2 rounded ${getSeverityColor(alert.severity)}`}>
                  <MapPin className="w-4 h-4" />
                </div>
                <div className="flex-1">
                  <p className="text-sm font-medium">
                    {alert.vehicleNumber} - {alert.alertType === 'entry' ? 'Entered' : alert.alertType === 'exit' ? 'Exited' : 'Violation'}
                  </p>
                  <p className="text-xs text-gray-600">{alert.geofenceName}</p>
                  <p className="text-xs text-gray-500 flex items-center gap-1 mt-1">
                    <Clock className="w-3 h-3" />
                    {new Date(alert.timestamp).toLocaleString()}
                  </p>
                </div>
                {!alert.acknowledged ? (
                  <button 
                    onClick={() => handleAcknowledge(alert.id)}
                    className="p-1 text-green-600 hover:bg-green-50 rounded"
                  >
                    <CheckCircle className="w-5 h-5" />
                  </button>
                ) : (
                  <CheckCircle className="w-5 h-5 text-gray-300" />
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
