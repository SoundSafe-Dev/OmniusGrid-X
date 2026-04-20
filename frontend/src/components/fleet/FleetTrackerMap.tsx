import { FC, useEffect, useState, useRef, useCallback } from 'react';
import { MapContainer, TileLayer, useMap, Marker, Popup, Polyline, Circle, Polygon } from 'react-leaflet';
import { Map as MapIcon, Truck, Navigation, AlertTriangle, Shield, X } from 'lucide-react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { fleetTrackerApi, simulateVehicleMovement } from '../../api/fleetTracker';
import type { 
  FleetVehiclePosition, 
  ShipmentRoute, 
  GeofenceZone, 
  MapFilterType,
  FleetUpdate 
} from '../../types';

// Fix Leaflet default icon issue in React
import icon from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';

let DefaultIcon = L.icon({
  iconUrl: icon,
  shadowUrl: iconShadow,
  iconSize: [25, 41],
  iconAnchor: [12, 41]
});

L.Marker.prototype.options.icon = DefaultIcon;

// Close all popups when clicking map background
const MapClickHandler: FC = () => {
  const map = useMap();
  useEffect(() => {
    const handleClick = () => {
      map.closePopup();
    };
    map.on('click', handleClick);
    return () => { map.off('click', handleClick); };
  }, [map]);
  return null;
};

// Vehicle marker colors by status
const getStatusColor = (status: FleetVehiclePosition['status']) => {
  switch (status) {
    case 'moving': return '#22c55e'; // green
    case 'idle': return '#eab308'; // yellow
    case 'stopped': return '#ef4444'; // red
    case 'offline': return '#6b7280'; // gray
    default: return '#6b7280';
  }
};

// Create custom vehicle marker icon
const createVehicleIcon = (status: FleetVehiclePosition['status'], heading: number) => {
  const color = getStatusColor(status);
  
  return L.divIcon({
    className: 'custom-vehicle-marker',
    html: `
      <div style="
        width: 36px;
        height: 36px;
        background: ${color};
        border: 3px solid white;
        border-radius: 50%;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        display: flex;
        align-items: center;
        justify-content: center;
        transform: rotate(${heading}deg);
      ">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
          <path d="M5 17a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2M5 17v2a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-2"/>
          <circle cx="7" cy="17" r="1.5"/>
          <circle cx="17" cy="17" r="1.5"/>
        </svg>
      </div>
    `,
    iconSize: [36, 36],
    iconAnchor: [18, 18],
  });
};

// Map bounds fitter component
const MapBoundsFitter: FC<{ vehicles: FleetVehiclePosition[] }> = ({ vehicles }) => {
  const map = useMap();
  
  useEffect(() => {
    if (vehicles.length > 0) {
      const bounds = L.latLngBounds(
        vehicles.map(v => [v.position.latitude, v.position.longitude])
      );
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
    }
  }, [map, vehicles]);
  
  return null;
};

interface FleetTrackerMapProps {
  filter?: MapFilterType;
  selectedVehicleId?: string | null;
  selectedShipmentId?: string | null;
  onVehicleClick?: (vehicle: FleetVehiclePosition) => void;
  onShipmentClick?: (shipment: ShipmentRoute) => void;
  height?: string;
  className?: string;
}

export const FleetTrackerMap: FC<FleetTrackerMapProps> = ({
  filter = 'all',
  selectedVehicleId,
  selectedShipmentId,
  onVehicleClick,
  onShipmentClick,
  height = '400px',
  className = '',
}) => {
  const [vehicles, setVehicles] = useState<FleetVehiclePosition[]>([]);
  const [shipments, setShipments] = useState<ShipmentRoute[]>([]);
  const [geofences, setGeofences] = useState<GeofenceZone[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showLegend, setShowLegend] = useState(true);
  const unsubscribeRef = useRef<(() => void) | null>(null);

  // Initial data fetch
  useEffect(() => {
    const fetchData = async () => {
      try {
        setIsLoading(true);
        const [vehicleData, shipmentData, geofenceData] = await Promise.all([
          fleetTrackerApi.getAllVehiclePositions(),
          fleetTrackerApi.getActiveShipmentRoutes(),
          fleetTrackerApi.getGeofenceZones(),
        ]);
        setVehicles(vehicleData);
        setShipments(shipmentData);
        setGeofences(geofenceData);
      } catch (error) {
        console.error('Failed to fetch fleet data:', error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, []);

  // Subscribe to real-time updates
  useEffect(() => {
    unsubscribeRef.current = fleetTrackerApi.subscribeToUpdates((update: FleetUpdate) => {
      if (update.type === 'vehicle_position') {
        const vehicleData = update.data as FleetVehiclePosition;
        setVehicles(prev => 
          prev.map(v => v.deviceId === vehicleData.deviceId ? vehicleData : v)
        );
      }
    });

    return () => {
      if (unsubscribeRef.current) {
        unsubscribeRef.current();
      }
    };
  }, []);

  // Filter vehicles based on current filter
  const filteredVehicles = useCallback(() => {
    switch (filter) {
      case 'fleet':
        return vehicles;
      case 'shipments':
        const activeVehicleIds = new Set(shipments.map(s => s.vehicleId));
        return vehicles.filter(v => activeVehicleIds.has(v.vehicleId));
      case 'carriers':
        return vehicles; // Would filter by carrier in real implementation
      case 'compliance':
        return vehicles.filter(v => v.status === 'stopped' || v.status === 'offline');
      default:
        return vehicles;
    }
  }, [vehicles, shipments, filter]);

  // Filter shipments based on current filter
  const filteredShipments = useCallback(() => {
    switch (filter) {
      case 'shipments':
        return shipments;
      default:
        return shipments.slice(0, 3); // Show limited routes in other tabs
    }
  }, [shipments, filter]);

  // Filter geofences based on current filter
  const filteredGeofences = useCallback(() => {
    switch (filter) {
      case 'compliance':
        return geofences;
      default:
        return []; // Only show geofences in compliance tab
    }
  }, [geofences, filter]);

  const displayedVehicles = filteredVehicles();
  const displayedShipments = filteredShipments();
  const displayedGeofences = filteredGeofences();

  // Default center (US center)
  const defaultCenter: [number, number] = [39.8283, -98.5795];

  return (
    <div className={`relative bg-opsgrid-panel border border-opsgrid-border rounded-lg ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-opsgrid-bg border-b border-opsgrid-border">
        <div className="flex items-center gap-2">
          <MapIcon className="w-5 h-5 text-opsgrid-primary" />
          <h3 className="font-semibold">Fleet Tracker</h3>
          <span className="text-xs text-opsgrid-text-secondary">
            ({displayedVehicles.length} vehicles visible)
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowLegend(!showLegend)}
            className="text-xs px-2 py-1 bg-opsgrid-panel hover:bg-opsgrid-border rounded transition-colors"
          >
            {showLegend ? 'Hide Legend' : 'Show Legend'}
          </button>
        </div>
      </div>

      {/* Map and Legend Container */}
      <div className="flex flex-col lg:flex-row">
        {/* Map Container */}
        <div style={{ height }} className="relative flex-1">
          <MapContainer
          center={defaultCenter}
          zoom={4}
          style={{ height: '100%', width: '100%' }}
          scrollWheelZoom={true}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          {/* Close popups when clicking map background */}
          <MapClickHandler />

          {/* Fit bounds to vehicles */}
          <MapBoundsFitter vehicles={displayedVehicles} />

          {/* Geofence Zones */}
          {displayedGeofences.map(geofence => {
            const color = geofence.color === 'green' ? '#22c55e' : 
                         geofence.color === 'yellow' ? '#eab308' : '#ef4444';
            
            if (geofence.type === 'circle' && geofence.center && geofence.radius) {
              return (
                <Circle
                  key={geofence.id}
                  center={[geofence.center.latitude, geofence.center.longitude]}
                  radius={geofence.radius}
                  pathOptions={{ 
                    color, 
                    fillColor: color, 
                    fillOpacity: 0.1,
                    weight: 2,
                    dashArray: '5, 10'
                  }}
                >
                  <Popup autoClose={true} closeOnClick={true} autoPan={false}>
                    <div className="p-2">
                      <p className="font-semibold">{geofence.name}</p>
                      <p className="text-sm text-gray-600">{geofence.description}</p>
                      <p className="text-xs text-gray-500 mt-1">Radius: {(geofence.radius / 1000).toFixed(1)} km</p>
                    </div>
                  </Popup>
                </Circle>
              );
            }
            return null;
          })}

          {/* Shipment Routes */}
          {displayedShipments.map(shipment => (
            <Polyline
              key={shipment.shipmentId}
              positions={shipment.waypoints.map(wp => [wp.latitude, wp.longitude])}
              pathOptions={{
                color: shipment.color,
                weight: 4,
                opacity: selectedShipmentId === shipment.shipmentId ? 1 : 0.6,
                dashArray: shipment.status === 'in_transit' ? undefined : '10, 10',
              }}
              eventHandlers={{
                click: () => onShipmentClick?.(shipment),
              }}
            >
              <Popup autoClose={true} closeOnClick={true} autoPan={false}>
                <div className="p-2">
                  <p className="font-semibold">{shipment.shipmentNumber}</p>
                  <p className="text-sm text-gray-600 capitalize">{shipment.status.replace('_', ' ')}</p>
                  {shipment.driverName && (
                    <p className="text-xs text-gray-500 mt-1">Driver: {shipment.driverName}</p>
                  )}
                </div>
              </Popup>
            </Polyline>
          ))}

          {/* Vehicle Markers */}
          {displayedVehicles.map(vehicle => (
            <Marker
              key={vehicle.deviceId}
              position={[vehicle.position.latitude, vehicle.position.longitude]}
              icon={createVehicleIcon(vehicle.status, vehicle.heading)}
              eventHandlers={{
                click: () => onVehicleClick?.(vehicle),
              }}
              opacity={selectedVehicleId === vehicle.vehicleId ? 1 : 0.9}
            >
              <Popup autoClose={true} closeOnClick={true} autoPan={false}>
                <div className="p-2 min-w-[200px]">
                  <div className="flex items-center gap-2 mb-2">
                    <Truck className="w-5 h-5 text-opsgrid-primary" />
                    <span className="font-semibold">{vehicle.vehicleId}</span>
                  </div>
                  {vehicle.driverName && (
                    <p className="text-sm text-gray-600 mb-1">
                      <span className="font-medium">Driver:</span> {vehicle.driverName}
                    </p>
                  )}
                  <div className="flex items-center gap-2 mb-1">
                    <span 
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: getStatusColor(vehicle.status) }}
                    />
                    <span className="text-sm capitalize">{vehicle.status}</span>
                  </div>
                  <p className="text-sm text-gray-600">
                    <span className="font-medium">Speed:</span> {vehicle.speed.toFixed(0)} mph
                  </p>
                  <p className="text-sm text-gray-600">
                    <span className="font-medium">Heading:</span> {vehicle.heading.toFixed(0)}°
                  </p>
                  <p className="text-xs text-gray-400 mt-2">
                    Updated: {new Date(vehicle.lastUpdate).toLocaleTimeString()}
                  </p>
                </div>
              </Popup>
            </Marker>
          ))}
        </MapContainer>

        {/* Loading Overlay */}
        {isLoading && (
          <div className="absolute inset-0 bg-opsgrid-bg/80 flex items-center justify-center">
            <div className="text-opsgrid-text-secondary">Loading fleet data...</div>
          </div>
        )}
        </div>

        {/* Legend - Outside of Map */}
        {showLegend && (
          <div className="lg:w-[200px] bg-opsgrid-panel border-t lg:border-t-0 lg:border-l border-opsgrid-border p-3 relative z-10">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold">Legend</span>
              <button 
                onClick={() => setShowLegend(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
            <div className="space-y-2 text-xs">
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-green-500" />
                <span>Moving (&gt;5 mph)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-yellow-500" />
                <span>Idle (0-5 mph)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-red-500" />
                <span>Stopped (&gt;5 min)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-gray-500" />
                <span>Offline</span>
              </div>
              <hr className="border-gray-200 my-1" />
              <div className="flex items-center gap-2">
                <Navigation className="w-3 h-3 text-blue-500" />
                <span>Active Route</span>
              </div>
              <div className="flex items-center gap-2">
                <Shield className="w-3 h-3 text-green-600" />
                <span>Safe Zone</span>
              </div>
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-3 h-3 text-yellow-500" />
                <span>Warning Zone</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
