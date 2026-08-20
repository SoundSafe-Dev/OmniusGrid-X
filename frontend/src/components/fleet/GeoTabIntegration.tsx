import { FC, useEffect, useState, useCallback } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, Circle } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { 
  Truck, 
  Navigation, 
  AlertTriangle, 
  Clock, 
  Fuel,
  MapPin,
  Activity,
  Route,
  Shield
} from 'lucide-react';
import { Card, Badge } from '../ui';
import { websocketManager } from '../../api';
import { fleetTrackerApi } from '../../api/fleetTracker';
import type { FleetVehiclePosition, GeofenceZone } from '../../types';

// GeoTab Vehicle Data Interface
interface GeoTabVehicle {
  id: string;
  name: string;
  deviceId: string;
  licensePlate: string;
  vin: string;
  currentPosition: {
    latitude: number;
    longitude: number;
    heading: number;
    speed: number;
    timestamp: string;
  };
  status: 'moving' | 'stopped' | 'idle' | 'offline' | 'warning';
  driver?: {
    name: string;
    id: string;
    hosStatus: 'on_duty' | 'driving' | 'off_duty' | 'sleeper';
    hoursRemaining: number;
  };
  tripInfo?: {
    destination: string;
    eta: string;
    distanceRemaining: number;
  };
  alerts: string[];
  fuelLevel?: number;
  odometer: number;
}

// GeoTab Geofence Interface
interface GeoTabGeofence {
  id: string;
  name: string;
  type: 'yard' | 'customer' | 'restricted' | 'corridor';
  coordinates: [number, number][];
  center: [number, number];
  radius?: number;
}

interface GeoTabIntegrationProps {
  organizationId: string;
  height?: number;
  showGeofences?: boolean;
  showTrail?: boolean;
  selectedVehicleId?: string;
}

// Custom vehicle marker icon
const createVehicleIcon = (status: string, heading: number) => {
  const colorMap: Record<string, string> = {
    moving: '#22c55e',
    stopped: '#ef4444',
    idle: '#eab308',
    offline: '#6b7280',
    warning: '#f97316',
  };
  
  const color = colorMap[status] || '#6b7280';
  
  return L.divIcon({
    className: 'vehicle-marker',
    html: `
      <div style="
        width: 40px;
        height: 40px;
        background: ${color};
        border: 3px solid white;
        border-radius: 50%;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        transform: rotate(${heading}deg);
        display: flex;
        align-items: center;
        justify-content: center;
      ">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
          <path d="M12 2L12 12M12 2L8 6M12 2L16 6"/>
        </svg>
      </div>
    `,
    iconSize: [40, 40],
    iconAnchor: [20, 20],
  });
};

// Status badge component
const VehicleStatusBadge: FC<{ status: string }> = ({ status }) => {
  const variantMap: Record<string, any> = {
    moving: 'success',
    stopped: 'error',
    idle: 'warning',
    offline: 'neutral',
    warning: 'warning',
  };
  
  return (
    <Badge variant={variantMap[status] || 'neutral'} dot>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </Badge>
  );
};

export const GeoTabIntegration: FC<GeoTabIntegrationProps> = ({
  organizationId,
  height = 600,
  showGeofences = true,
  showTrail = true,
  selectedVehicleId,
}) => {
  const [vehicles, setVehicles] = useState<GeoTabVehicle[]>([]);
  const [geofences, setGeofences] = useState<GeoTabGeofence[]>([]);
  const [selectedVehicle, setSelectedVehicle] = useState<GeoTabVehicle | null>(null);
  const [vehicleTrails, setVehicleTrails] = useState<Record<string, Array<[number, number]>>>({});
  const [mapCenter, setMapCenter] = useState<[number, number]>([39.8283, -98.5795]); // Center of US
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'disconnected'>('disconnected');
  // FS-548. Both fetches caught their failure into `console.error` and nothing else, so a
  // failed vehicle load left `vehicles` at `[]` and the header rendered **"0 Vehicles"** —
  // a count, presented as a measurement of the fleet. `failureIsNotEmptiness` could not see
  // it: there is no "No vehicles" sentence to match, and a number is not a phrase.
  //
  // "0 Vehicles" is the same lie as "No vehicles found" and reads as more authoritative,
  // because a figure looks computed. A dispatcher sees an empty map and a zero and concludes
  // the fleet is not reporting.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Subscribe to GeoTab WebSocket updates
  useEffect(() => {
    const unsubscribeStatus = websocketManager.subscribe<{ connected: boolean }>(
      'connection_status',
      ({ connected }) => {
        setConnectionStatus(connected ? 'connected' : 'disconnected');
      }
    );

    const unsubscribeGeoTab = websocketManager.subscribe<{
      type: 'vehicle_position' | 'geofence_event' | 'hos_alert' | 'diagnostic';
      vehicleId: string;
      data: any;
    }>('geotab', (message) => {
      if (message.type === 'vehicle_position') {
        setVehicles((prev) => {
          const existing = prev.find((v) => v.id === message.vehicleId);
          if (existing) {
            // Update existing vehicle
            return prev.map((v) =>
              v.id === message.vehicleId
                ? { ...v, currentPosition: message.data.position, status: message.data.status }
                : v
            );
          }
          // Add new vehicle
          return [...prev, message.data.vehicle];
        });

        // Update trail
        if (showTrail) {
          const newPoint: [number, number] = [
            message.data.position.latitude,
            message.data.position.longitude,
          ];
          setVehicleTrails((prev) => ({
            ...prev,
            [message.vehicleId]: [
              ...(prev[message.vehicleId] || []),
              newPoint,
            ].slice(-50) as [number, number][], // Keep last 50 points
          }));
        }
      }
    });

    // Fetch initial data
    fetchVehicles();
    fetchGeofences();

    return () => {
      unsubscribeStatus();
      unsubscribeGeoTab();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing; adding deps changes retrigger behavior (FS-54)
  }, [organizationId, showTrail]);

  // Initial loads go through the shared authenticated api client (the old raw
  // fetch() calls sent no Authorization header and targeted a non-existent
  // /api/v1/fleet/vehicles route). The backend scopes both endpoints to the
  // caller's organization via the auth token, so organizationId is not sent.
  const fetchVehicles = useCallback(async () => {
    try {
      const positions = await fleetTrackerApi.getAllVehiclePositions();
      const mapped: GeoTabVehicle[] = positions
        .filter((p: FleetVehiclePosition) => p.position?.latitude != null && p.position?.longitude != null)
        .map((p: FleetVehiclePosition) => ({
          id: p.deviceId,
          name: p.vehicleId || p.deviceId,
          deviceId: p.deviceId,
          licensePlate: '',
          vin: '',
          currentPosition: {
            latitude: p.position.latitude,
            longitude: p.position.longitude,
            heading: p.heading ?? 0,
            speed: p.speed ?? 0,
            timestamp: p.position.timestamp || p.lastUpdate,
          },
          status: p.status ?? 'offline',
          alerts: [],
          odometer: 0,
        }));
      setVehicles(mapped);

      // Center map on first vehicle if exists
      if (mapped.length > 0) {
        setMapCenter([mapped[0].currentPosition.latitude, mapped[0].currentPosition.longitude]);
      }
      setLoadError(null);
    } catch (error) {
      console.error('Failed to fetch vehicles:', error);
      setLoadError(error instanceof Error ? error.message : 'Could not load vehicles');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const fetchGeofences = useCallback(async () => {
    try {
      const zones = await fleetTrackerApi.getGeofenceZones();
      const mapped: GeoTabGeofence[] = zones
        .filter((z: GeofenceZone) => z.center || (z.coordinates && z.coordinates.length > 0))
        .map((z: GeofenceZone) => {
          const coordinates: [number, number][] = (z.coordinates ?? []).map(
            (c) => [c.latitude, c.longitude] as [number, number]
          );
          const center: [number, number] = z.center
            ? [z.center.latitude, z.center.longitude]
            : coordinates[0];
          return {
            id: z.id,
            name: z.name,
            // Backend severity color -> local zone semantics (red = restricted).
            type: z.color === 'red' ? 'restricted' as const : 'customer' as const,
            coordinates,
            center,
            radius: z.radius,
          };
        });
      setGeofences(mapped);
    } catch (error) {
      // Geofences are supplementary — a failure here leaves the map usable, so it does not
      // set `loadError`, which is reserved for "the vehicle list did not arrive".
      console.error('Failed to fetch geofences:', error);
    }
  }, []);

  // Filter visible vehicles
  const visibleVehicles = selectedVehicleId
    ? vehicles.filter((v) => v.id === selectedVehicleId)
    : vehicles;

  return (
    <Card className="w-full">
      {/* Header */}
      <div className="p-4 border-b border-opsgrid-border">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MapPin className="w-5 h-5 text-opsgrid-primary" />
            <h3 className="text-lg font-semibold text-opsgrid-text">GeoTab Fleet Tracking</h3>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 text-sm text-opsgrid-text-secondary">
              <div className={`w-2 h-2 rounded-full ${connectionStatus === 'connected' ? 'bg-green-500' : 'bg-red-500'}`} />
              {connectionStatus === 'connected' ? 'Live' : 'Disconnected'}
            </div>
            {/* The count is only a count when the request succeeded. On failure this says
                so instead of reporting zero (FS-548). */}
            {loadError ? (
              // A badge, not a panel: this sits in a header row beside other status chips,
              // and a full ErrorState block here would push the map off screen. The retry
              // is a control next to the chip so the recovery is where the bad news is.
              <span className="inline-flex items-center gap-2">
                <Badge variant="error">Vehicles unavailable</Badge>
                <button
                  type="button"
                  onClick={() => void fetchVehicles()}
                  disabled={isLoading}
                  className="text-xs underline text-opsgrid-text-secondary hover:text-opsgrid-text disabled:opacity-60"
                >
                  {isLoading ? 'Retrying…' : 'Retry'}
                </button>
              </span>
            ) : isLoading ? (
              <Badge variant="info">Loading…</Badge>
            ) : (
              <Badge variant="info">{vehicles.length} Vehicles</Badge>
            )}
          </div>
        </div>
      </div>

      {/* Map */}
      <div className="relative" style={{ height }}>
        <MapContainer
          center={mapCenter}
          zoom={6}
          style={{ height: '100%', width: '100%' }}
          scrollWheelZoom={true}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          {/* Geofences */}
          {showGeofences && geofences.map((geofence) => (
            <div key={geofence.id}>
              {geofence.radius ? (
                <Circle
                  center={geofence.center}
                  radius={geofence.radius}
                  pathOptions={{
                    color: geofence.type === 'restricted' ? '#ef4444' : '#3b82f6',
                    fillColor: geofence.type === 'restricted' ? '#ef4444' : '#3b82f6',
                    fillOpacity: 0.1,
                    weight: 2,
                  }}
                />
              ) : (
                <Polyline
                  positions={geofence.coordinates}
                  pathOptions={{
                    color: '#3b82f6',
                    weight: 2,
                    fillOpacity: 0.1,
                  }}
                />
              )}
            </div>
          ))}

          {/* Vehicle Trails */}
          {showTrail && Object.entries(vehicleTrails).map(([vehicleId, trail]) => (
            <Polyline
              key={`trail-${vehicleId}`}
              positions={trail}
              pathOptions={{
                color: '#64748b',
                weight: 2,
                opacity: 0.5,
                dashArray: '5, 10',
              }}
            />
          ))}

          {/* Vehicle Markers */}
          {visibleVehicles.map((vehicle) => (
            <Marker
              key={vehicle.id}
              position={[
                vehicle.currentPosition.latitude,
                vehicle.currentPosition.longitude,
              ]}
              icon={createVehicleIcon(vehicle.status, vehicle.currentPosition.heading)}
              eventHandlers={{
                click: () => setSelectedVehicle(vehicle),
              }}
            >
              <Popup>
                <div className="p-2 min-w-[250px]">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="font-semibold text-opsgrid-text">{vehicle.name}</h4>
                    <VehicleStatusBadge status={vehicle.status} />
                  </div>
                  
                  <div className="space-y-2 text-sm">
                    <div className="flex items-center gap-2 text-opsgrid-text-secondary">
                      <Truck className="w-4 h-4" />
                      <span>{vehicle.licensePlate}</span>
                    </div>
                    
                    <div className="flex items-center gap-2 text-opsgrid-text-secondary">
                      <Navigation className="w-4 h-4" />
                      <span>{vehicle.currentPosition.speed.toFixed(1)} mph</span>
                    </div>
                    
                    {vehicle.driver && (
                      <div className="flex items-center gap-2 text-opsgrid-text-secondary">
                        <Shield className="w-4 h-4" />
                        <span>{vehicle.driver.name}</span>
                        <Badge size="sm" variant={vehicle.driver.hoursRemaining < 2 ? 'warning' : 'success'}>
                          {vehicle.driver.hoursRemaining.toFixed(1)}h left
                        </Badge>
                      </div>
                    )}
                    
                    {vehicle.tripInfo && (
                      <div className="flex items-center gap-2 text-opsgrid-text-secondary">
                        <Route className="w-4 h-4" />
                        <span>To: {vehicle.tripInfo.destination}</span>
                      </div>
                    )}
                    
                    {vehicle.fuelLevel !== undefined && (
                      <div className="flex items-center gap-2 text-opsgrid-text-secondary">
                        <Fuel className="w-4 h-4" />
                        <span>Fuel: {vehicle.fuelLevel}%</span>
                      </div>
                    )}
                    
                    {vehicle.alerts.length > 0 && (
                      <div className="mt-2 p-2 bg-red-500/10 rounded">
                        <div className="flex items-center gap-1 text-red-500">
                          <AlertTriangle className="w-4 h-4" />
                          <span className="font-medium">Alerts</span>
                        </div>
                        {vehicle.alerts.map((alert, idx) => (
                          <p key={idx} className="text-xs text-red-500 ml-5">{alert}</p>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </Popup>
            </Marker>
          ))}
        </MapContainer>

        {/* Vehicle List Overlay */}
        <div className="absolute top-4 right-4 w-64 max-h-[calc(100%-32px)] overflow-y-auto">
          <Card className="bg-opsgrid-panel/95 backdrop-blur">
            <div className="p-3">
              <h4 className="font-medium text-opsgrid-text mb-2 flex items-center gap-2">
                <Activity className="w-4 h-4" />
                Vehicles ({vehicles.length})
              </h4>
              <div className="space-y-1">
                {vehicles.map((vehicle) => (
                  <button
                    key={vehicle.id}
                    onClick={() => setSelectedVehicle(vehicle)}
                    className={`w-full p-2 rounded text-left text-sm transition-colors ${
                      selectedVehicle?.id === vehicle.id
                        ? 'bg-opsgrid-primary/20 border border-opsgrid-primary'
                        : 'hover:bg-opsgrid-bg'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-opsgrid-text">{vehicle.name}</span>
                      <div
                        className="w-2 h-2 rounded-full"
                        style={{
                          backgroundColor:
                            vehicle.status === 'moving'
                              ? '#22c55e'
                              : vehicle.status === 'stopped'
                              ? '#ef4444'
                              : '#eab308',
                        }}
                      />
                    </div>
                    <div className="flex items-center gap-2 text-xs text-opsgrid-text-secondary mt-1">
                      <span>{vehicle.currentPosition.speed.toFixed(0)} mph</span>
                      {vehicle.driver && (
                        <>
                          <span>•</span>
                          <span>{vehicle.driver.name}</span>
                        </>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </Card>
        </div>
      </div>

      {/* Selected Vehicle Details */}
      {selectedVehicle && (
        <div className="p-4 border-t border-opsgrid-border bg-opsgrid-bg">
          <div className="flex items-start justify-between">
            <div>
              <h4 className="font-semibold text-opsgrid-text">{selectedVehicle.name}</h4>
              <p className="text-sm text-opsgrid-text-secondary">
                {selectedVehicle.vin} • {selectedVehicle.licensePlate}
              </p>
            </div>
            <VehicleStatusBadge status={selectedVehicle.status} />
          </div>
          
          <div className="grid grid-cols-4 gap-4 mt-4">
            <div className="p-3 bg-opsgrid-panel rounded">
              <div className="flex items-center gap-2 text-opsgrid-text-secondary mb-1">
                <Navigation className="w-4 h-4" />
                <span className="text-xs">Speed</span>
              </div>
              <p className="text-lg font-semibold text-opsgrid-text">
                {selectedVehicle.currentPosition.speed.toFixed(1)} mph
              </p>
            </div>
            
            <div className="p-3 bg-opsgrid-panel rounded">
              <div className="flex items-center gap-2 text-opsgrid-text-secondary mb-1">
                <Clock className="w-4 h-4" />
                <span className="text-xs">Last Update</span>
              </div>
              <p className="text-sm font-semibold text-opsgrid-text">
                {new Date(selectedVehicle.currentPosition.timestamp).toLocaleTimeString()}
              </p>
            </div>
            
            {selectedVehicle.driver && (
              <div className="p-3 bg-opsgrid-panel rounded">
                <div className="flex items-center gap-2 text-opsgrid-text-secondary mb-1">
                  <Shield className="w-4 h-4" />
                  <span className="text-xs">HOS Remaining</span>
                </div>
                <p className={`text-lg font-semibold ${selectedVehicle.driver.hoursRemaining < 2 ? 'text-status-alarm' : 'text-opsgrid-text'}`}>
                  {selectedVehicle.driver.hoursRemaining.toFixed(1)}h
                </p>
              </div>
            )}
            
            {selectedVehicle.fuelLevel !== undefined && (
              <div className="p-3 bg-opsgrid-panel rounded">
                <div className="flex items-center gap-2 text-opsgrid-text-secondary mb-1">
                  <Fuel className="w-4 h-4" />
                  <span className="text-xs">Fuel Level</span>
                </div>
                <p className={`text-lg font-semibold ${selectedVehicle.fuelLevel < 20 ? 'text-status-alarm' : 'text-opsgrid-text'}`}>
                  {selectedVehicle.fuelLevel}%
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  );
};

export default GeoTabIntegration;
