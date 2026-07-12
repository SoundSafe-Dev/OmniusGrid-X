import { FC, useState, useEffect } from 'react';
import { useQuery } from 'react-query';
import {
  Truck,
  MapPin,
  User,
  Building2,
  Clock,
  AlertTriangle,
  CheckCircle2,
  Navigation,
  Fuel,
  Gauge,
  Calendar,
  Filter,
  Search,
  RefreshCw,
  Shield,
  Activity,
  Thermometer,
  Package,
  Wrench
} from 'lucide-react';
import { transportationApi, geoTabApi } from '../../api';
import {
  FleetTrackerMap,
  GeofencingPanel,
  HealthSecurityPanel,
  MaintenancePanel,
  PerformancePanel
} from '../../components';
import type {
  Driver,
  Shipment,
  Vehicle,
  ShipmentFilters,
  GeoLocation,
  MapFilterType
} from '../../types';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';

const TRANSPORT_QUERY_KEY = 'transportation';

export const TransportationManagement: FC = () => {
  const [selectedShipment, setSelectedShipment] = useState<Shipment | null>(null);
  const [selectedDriver, setSelectedDriver] = useState<Driver | null>(null);
  const [, setSelectedVehicle] = useState<Vehicle | null>(null);
  const [filters, setFilters] = useState<ShipmentFilters>({});
  const [activeTab, setActiveTab] = useState<'shipments' | 'fleet' | 'carriers' | 'compliance' | 'geofencing' | 'health' | 'maintenance' | 'performance'>('shipments');
  const [fleetLocation, setFleetLocation] = useState<GeoLocation | null>(null);
  const [selectedMapVehicle, setSelectedMapVehicle] = useState<string | null>(null);
  const [selectedMapShipment, setSelectedMapShipment] = useState<string | null>(null);

  const { data: shipmentsData, isLoading: shipmentsLoading, refetch: refetchShipments } = useQuery(
    [TRANSPORT_QUERY_KEY, 'shipments', filters],
    () => transportationApi.getShipments(filters)
  );

  const { data: carriersData, isLoading: carriersLoading } = useQuery(
    [TRANSPORT_QUERY_KEY, 'carriers'],
    () => transportationApi.getCarriers()
  );

  const { data: driversData, isLoading: driversLoading } = useQuery(
    [TRANSPORT_QUERY_KEY, 'drivers'],
    () => transportationApi.getDrivers()
  );

  const { data: vehiclesData, isLoading: vehiclesLoading } = useQuery(
    [TRANSPORT_QUERY_KEY, 'vehicles'],
    () => transportationApi.getVehicles()
  );

  const { data: fleetSummary } = useQuery(
    [TRANSPORT_QUERY_KEY, 'fleet-summary'],
    () => geoTabApi.getFleetSummary()
  );

  const { data: deliveryEfficiency } = useQuery(
    [TRANSPORT_QUERY_KEY, 'efficiency'],
    () => transportationApi.getDeliveryEfficiency()
  );

  const { data: complianceSummary } = useQuery(
    [TRANSPORT_QUERY_KEY, 'compliance'],
    () => transportationApi.getComplianceSummary()
  );

  const shipments = shipmentsData?.items || [];
  const carriers = carriersData?.items || [];
  const drivers = driversData?.items || [];
  const vehicles = vehiclesData?.items || [];

  const stats = {
    totalShipments: shipments.length,
    inTransit: shipments.filter(s => s.status === 'in_transit').length,
    delivered: shipments.filter(s => s.status === 'delivered').length,
    planned: shipments.filter(s => s.status === 'planned').length,
    activeDrivers: drivers.filter(d => d.currentHosStatus === 'driving' || d.currentHosStatus === 'on_duty').length,
    offDutyDrivers: drivers.filter(d => d.currentHosStatus === 'off_duty').length,
    hosViolations: drivers.filter(d => d.hosDriveHoursRemaining === 0).length,
    totalCarriers: carriers.length,
    ctpatCertified: carriers.filter(c => c.ctpatCertified).length,
  };

  const getStatusColor = (status: Shipment['status']) => {
    switch (status) {
      case 'in_transit': return 'bg-blue-500';
      case 'delivered': return 'bg-green-500';
      case 'picked_up': return 'bg-yellow-500';
      case 'planned': return 'bg-gray-400';
      case 'dispatched': return 'bg-purple-500';
      case 'cancelled': return 'bg-red-500';
      default: return 'bg-gray-400';
    }
  };

  const getHosColor = (hoursRemaining: number) => {
    if (hoursRemaining === 0) return 'text-red-500';
    if (hoursRemaining < 2) return 'text-yellow-500';
    return 'text-green-500';
  };

  const formatDuration = (hours?: number) => {
    if (hours === undefined) return 'N/A';
    return `${hours.toFixed(1)}h`;
  };

  // Simulate fetching real-time fleet location
  useEffect(() => {
    const fetchLocation = async () => {
      try {
        const loc = await geoTabApi.getDeviceLocation('gt-device-002');
        setFleetLocation(loc);
      } catch (error) {
        console.error('Failed to fetch location:', error);
      }
    };
    
    if (activeTab === 'fleet') {
      fetchLocation();
      const interval = setInterval(fetchLocation, 30000); // Update every 30s
      return () => clearInterval(interval);
    }
  }, [activeTab]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <Tooltip>
          <TooltipTrigger asChild>
            <div>
              <h1 className="text-2xl font-bold flex items-center gap-2">
                <Truck className="w-6 h-6 text-opsgrid-primary" />
                Transportation Management System (TMS)
              </h1>
              <p className="text-opsgrid-text-secondary mt-1">
                Fleet tracking, shipment management, and GeoTab telematics integration
              </p>
            </div>
          </TooltipTrigger>
          <TooltipContent>Transportation management system overview</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              onClick={() => refetchShipments()}
              className="flex items-center gap-2 px-4 py-2 bg-opsgrid-panel border border-opsgrid-border rounded-lg hover:bg-opsgrid-border transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              Refresh
            </button>
          </TooltipTrigger>
          <TooltipContent>Refresh transportation data</TooltipContent>
        </Tooltip>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4">
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard label="Total Shipments" value={stats.totalShipments} icon={Package} />
          </TooltipTrigger>
          <TooltipContent>Total shipments in the system</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard label="In Transit" value={stats.inTransit} icon={Navigation} color="text-blue-500" />
          </TooltipTrigger>
          <TooltipContent>Shipments currently in transit</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard label="Delivered" value={stats.delivered} icon={CheckCircle2} color="text-green-500" />
          </TooltipTrigger>
          <TooltipContent>Successfully delivered shipments</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard label="Planned" value={stats.planned} icon={Calendar} color="text-gray-400" />
          </TooltipTrigger>
          <TooltipContent>Planned shipments awaiting dispatch</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard label="Active Drivers" value={stats.activeDrivers} icon={User} color="text-blue-500" />
          </TooltipTrigger>
          <TooltipContent>Currently active drivers</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard
              label="HOS Violations"
              value={stats.hosViolations}
              icon={AlertTriangle}
              color={stats.hosViolations > 0 ? 'text-red-500' : 'text-green-500'}
            />
          </TooltipTrigger>
          <TooltipContent>Hours of Service violations</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard label="Carriers" value={stats.totalCarriers} icon={Building2} />
          </TooltipTrigger>
          <TooltipContent>Total carriers in the network</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard label="CT-PAT Cert" value={stats.ctpatCertified} icon={Shield} color="text-green-500" />
          </TooltipTrigger>
          <TooltipContent>CT-PAT certified carriers</TooltipContent>
        </Tooltip>
      </div>

      {/* Fleet Tracker Map - Persistent across all tabs */}
      <FleetTrackerMap
        filter={activeTab as MapFilterType}
        selectedVehicleId={selectedMapVehicle}
        selectedShipmentId={selectedMapShipment}
        onVehicleClick={(vehicle) => {
          setSelectedMapVehicle(vehicle.vehicleId);
          // Find and select the driver if available
          const driver = drivers.find(d => d.id === vehicle.driverId);
          if (driver) setSelectedDriver(driver);
        }}
        onShipmentClick={(shipmentRoute) => {
          setSelectedMapShipment(shipmentRoute.shipmentId);
          // Find and select the shipment
          const shipment = shipments.find(s => s.id === shipmentRoute.shipmentId);
          if (shipment) setSelectedShipment(shipment);
        }}
        height="400px"
      />

      {/* Fleet Summary from GeoTab */}
      {fleetSummary && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <h3 className="font-semibold mb-4 flex items-center gap-2">
            <Activity className="w-5 h-5 text-opsgrid-primary" />
            Fleet Status (GeoTab Live)
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
            <div className="bg-opsgrid-bg rounded-lg p-3">
              <p className="text-xs text-opsgrid-text-secondary">Total Vehicles</p>
              <p className="text-xl font-bold">{fleetSummary.totalVehicles}</p>
            </div>
            <div className="bg-opsgrid-bg rounded-lg p-3">
              <p className="text-xs text-opsgrid-text-secondary">Moving</p>
              <p className="text-xl font-bold text-green-500">{fleetSummary.vehiclesMoving}</p>
            </div>
            <div className="bg-opsgrid-bg rounded-lg p-3">
              <p className="text-xs text-opsgrid-text-secondary">Idle</p>
              <p className="text-xl font-bold text-yellow-500">{fleetSummary.vehiclesIdle}</p>
            </div>
            <div className="bg-opsgrid-bg rounded-lg p-3">
              <p className="text-xs text-opsgrid-text-secondary">Avg Speed</p>
              <p className="text-xl font-bold">{fleetSummary.avgSpeed} mph</p>
            </div>
            <div className="bg-opsgrid-bg rounded-lg p-3">
              <p className="text-xs text-opsgrid-text-secondary">Distance Today</p>
              <p className="text-xl font-bold">{fleetSummary.totalDistanceToday} mi</p>
            </div>
            <div className="bg-opsgrid-bg rounded-lg p-3">
              <p className="text-xs text-opsgrid-text-secondary">Fuel Today</p>
              <p className="text-xl font-bold">{fleetSummary.fuelConsumedToday} gal</p>
            </div>
          </div>
        </div>
      )}

      {/* Delivery Efficiency */}
      {deliveryEfficiency && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
            <p className="text-sm text-opsgrid-text-secondary">On-Time Delivery Rate</p>
            <div className="flex items-end gap-2">
              <p className={`text-2xl font-bold ${deliveryEfficiency.onTimeRate >= 90 ? 'text-green-500' : 'text-yellow-500'}`}>
                {deliveryEfficiency.onTimeRate.toFixed(1)}%
              </p>
            </div>
          </div>
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
            <p className="text-sm text-opsgrid-text-secondary">Average Transit Time</p>
            <p className="text-2xl font-bold">{deliveryEfficiency.avgTransitTime}h</p>
          </div>
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
            <p className="text-sm text-opsgrid-text-secondary">Deliveries Today</p>
            <p className="text-2xl font-bold">{deliveryEfficiency.totalDeliveries}</p>
            {deliveryEfficiency.lateDeliveries > 0 && (
              <p className="text-sm text-red-500">{deliveryEfficiency.lateDeliveries} late</p>
            )}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-opsgrid-border">
        <div className="flex gap-1 flex-wrap">
          {[
            { id: 'shipments', label: 'Shipments', icon: Package, tooltip: 'View and manage all shipments' },
            { id: 'fleet', label: 'Fleet & Drivers', icon: Truck, tooltip: 'Monitor fleet vehicles and driver HOS compliance' },
            { id: 'carriers', label: 'Carriers', icon: Building2, tooltip: 'Manage carrier information and certifications' },
            { id: 'compliance', label: 'Compliance', icon: Shield, tooltip: 'View compliance status and violations' },
            { id: 'geofencing', label: 'Geofencing', icon: MapPin, tooltip: 'Configure and monitor geofence zones' },
            { id: 'health', label: 'Health & Security', icon: Activity, tooltip: 'Monitor vehicle health and security status' },
            { id: 'maintenance', label: 'Maintenance', icon: Wrench, tooltip: 'Track vehicle maintenance schedules' },
            { id: 'performance', label: 'Performance', icon: Gauge, tooltip: 'View fleet performance metrics' },
          ].map(tab => (
            <Tooltip key={tab.id}>
              <TooltipTrigger asChild>
                <button
                  onClick={() => setActiveTab(tab.id as typeof activeTab)}
                  className={`flex items-center gap-2 px-3 py-2 border-b-2 transition-colors text-sm ${
                    activeTab === tab.id
                      ? 'border-opsgrid-primary text-opsgrid-primary'
                      : 'border-transparent text-opsgrid-text-secondary hover:text-opsgrid-text'
                  }`}
                >
                  <tab.icon className="w-4 h-4" />
                  {tab.label}
                </button>
              </TooltipTrigger>
              <TooltipContent>{tab.tooltip}</TooltipContent>
            </Tooltip>
          ))}
        </div>
      </div>

      {/* Filters */}
      {activeTab === 'shipments' && (
        <div className="flex flex-wrap gap-3 items-center">
          <div className="flex items-center gap-2 px-3 py-2 bg-opsgrid-panel border border-opsgrid-border rounded-lg">
            <Filter className="w-4 h-4 text-opsgrid-text-secondary" />
            <select
              value={filters.status || ''}
              onChange={(e) => setFilters({ ...filters, status: e.target.value as any })}
              className="bg-transparent text-sm focus:outline-none"
            >
              <option value="">All Statuses</option>
              <option value="planned">Planned</option>
              <option value="dispatched">Dispatched</option>
              <option value="in_transit">In Transit</option>
              <option value="delivered">Delivered</option>
            </select>
          </div>
          <div className="flex items-center gap-2 px-3 py-2 bg-opsgrid-panel border border-opsgrid-border rounded-lg">
            <Search className="w-4 h-4 text-opsgrid-text-secondary" />
            <input
              type="text"
              placeholder="Search shipment..."
              className="bg-transparent text-sm focus:outline-none w-40"
            />
          </div>
        </div>
      )}

      {/* Content */}
      {activeTab === 'shipments' && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg overflow-hidden">
          {shipmentsLoading ? (
            <div className="p-8 text-center text-opsgrid-text-secondary">Loading shipments...</div>
          ) : shipments.length === 0 ? (
            <div className="p-8 text-center text-opsgrid-text-secondary">No shipments found</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-opsgrid-bg/50">
                  <tr>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Shipment</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Status</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Carrier</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Route</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">ETA</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Freight</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-opsgrid-border">
                  {shipments.map(shipment => (
                    <tr 
                      key={shipment.id} 
                      className="hover:bg-opsgrid-bg/50 cursor-pointer"
                      onClick={() => setSelectedShipment(shipment)}
                    >
                      <td className="px-4 py-3">
                        <div>
                          <p className="font-medium">{shipment.shipmentNumber}</p>
                          <p className="text-sm text-opsgrid-text-secondary">{shipment.poNumber}</p>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${getStatusColor(shipment.status)}`} />
                          <span className="capitalize">{shipment.status.replace('_', ' ')}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-sm">{shipment.carrierName}</td>
                      <td className="px-4 py-3 text-sm">
                        <div>
                          <p>{shipment.origin.city} → {shipment.destination.city}</p>
                          {shipment.currentLocation && (
                            <p className="text-xs text-opsgrid-text-secondary flex items-center gap-1">
                              <MapPin className="w-3 h-3" />
                              {shipment.currentLocation.latitude.toFixed(2)}, {shipment.currentLocation.longitude.toFixed(2)}
                            </p>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {shipment.estimatedDelivery ? (
                          <span className={new Date(shipment.estimatedDelivery) > new Date(shipment.scheduledDelivery) ? 'text-yellow-500' : 'text-green-500'}>
                            {new Date(shipment.estimatedDelivery).toLocaleDateString()}
                          </span>
                        ) : shipment.scheduledDelivery ? (
                          new Date(shipment.scheduledDelivery).toLocaleDateString()
                        ) : '-'}
                      </td>
                      <td className="px-4 py-3 text-sm">${shipment.freightCharge?.toFixed(2) || '0.00'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === 'fleet' && (
        <div className="space-y-6">
          {/* Real-time Map View (Placeholder) */}
          {fleetLocation && (
            <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
              <h3 className="font-semibold mb-4 flex items-center gap-2">
                <MapPin className="w-5 h-5 text-opsgrid-primary" />
                Live Fleet Location (GeoTab)
              </h3>
              <div className="bg-opsgrid-bg rounded-lg p-4">
                <div className="grid grid-cols-4 gap-4 text-sm">
                  <div>
                    <p className="text-opsgrid-text-secondary">Latitude</p>
                    <p className="font-medium">{fleetLocation.latitude.toFixed(6)}</p>
                  </div>
                  <div>
                    <p className="text-opsgrid-text-secondary">Longitude</p>
                    <p className="font-medium">{fleetLocation.longitude.toFixed(6)}</p>
                  </div>
                  <div>
                    <p className="text-opsgrid-text-secondary">Speed</p>
                    <p className="font-medium">{fleetLocation.speed?.toFixed(1) || 0} mph</p>
                  </div>
                  <div>
                    <p className="text-opsgrid-text-secondary">Heading</p>
                    <p className="font-medium">{fleetLocation.heading?.toFixed(0) || 0}°</p>
                  </div>
                </div>
                <p className="text-xs text-opsgrid-text-secondary mt-3">
                  Last updated: {new Date(fleetLocation.timestamp).toLocaleString()} (Auto-refresh every 30s)
                </p>
              </div>
            </div>
          )}

          {/* Vehicles */}
          <div>
            <h3 className="font-semibold mb-3">Vehicles</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {vehiclesLoading ? (
                <div className="col-span-full p-8 text-center text-opsgrid-text-secondary">Loading vehicles...</div>
              ) : vehicles.map(vehicle => (
                <div 
                  key={vehicle.id}
                  className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4 cursor-pointer hover:border-opsgrid-primary transition-all"
                  onClick={() => setSelectedVehicle(vehicle)}
                >
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="font-semibold">{vehicle.vehicleNumber}</h4>
                    <span className={`px-2 py-1 rounded text-xs ${
                      vehicle.currentDriverId ? 'bg-green-500/20 text-green-500' : 'bg-gray-500/20 text-gray-500'
                    }`}>
                      {vehicle.currentDriverId ? 'Active' : 'Idle'}
                    </span>
                  </div>
                  <p className="text-sm text-opsgrid-text-secondary mb-2">
                    {vehicle.year} {vehicle.make} {vehicle.model}
                  </p>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="flex items-center gap-1">
                      <Fuel className="w-3 h-3 text-opsgrid-text-secondary" />
                      <span>{vehicle.fuelLevel}%</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <Gauge className="w-3 h-3 text-opsgrid-text-secondary" />
                      <span>{vehicle.odometer?.toLocaleString()} mi</span>
                    </div>
                  </div>
                  {vehicle.currentLocation && (
                    <div className="mt-3 pt-3 border-t border-opsgrid-border">
                      <p className="text-xs text-opsgrid-text-secondary flex items-center gap-1">
                        <MapPin className="w-3 h-3" />
                        {vehicle.currentLocation.latitude.toFixed(4)}, {vehicle.currentLocation.longitude.toFixed(4)}
                      </p>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Drivers */}
          <div>
            <h3 className="font-semibold mb-3">Drivers & HOS Compliance</h3>
            <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg overflow-hidden">
              {driversLoading ? (
                <div className="p-8 text-center text-opsgrid-text-secondary">Loading drivers...</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-opsgrid-bg/50">
                      <tr>
                        <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Driver</th>
                        <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Carrier</th>
                        <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Status</th>
                        <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Drive Remaining</th>
                        <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Duty Remaining</th>
                        <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Cycle Used</th>
                        <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Location</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-opsgrid-border">
                      {drivers.map(driver => (
                        <tr 
                          key={driver.id} 
                          className="hover:bg-opsgrid-bg/50 cursor-pointer"
                          onClick={() => setSelectedDriver(driver)}
                        >
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <User className="w-4 h-4 text-opsgrid-text-secondary" />
                              <div>
                                <p className="font-medium">{driver.firstName} {driver.lastName}</p>
                                <p className="text-xs text-opsgrid-text-secondary">CDL-{driver.cdlClass}</p>
                              </div>
                            </div>
                          </td>
                          <td className="px-4 py-3 text-sm">{driver.carrierName}</td>
                          <td className="px-4 py-3">
                            <span className={`px-2 py-1 rounded text-xs capitalize ${
                              driver.currentHosStatus === 'driving' ? 'bg-green-500/20 text-green-500' :
                              driver.currentHosStatus === 'on_duty' ? 'bg-blue-500/20 text-blue-500' :
                              'bg-gray-500/20 text-gray-500'
                            }`}>
                              {driver.currentHosStatus.replace('_', ' ')}
                            </span>
                          </td>
                          <td className={`px-4 py-3 font-medium ${getHosColor(driver.hosDriveHoursRemaining)}`}>
                            {formatDuration(driver.hosDriveHoursRemaining)}
                          </td>
                          <td className={`px-4 py-3 font-medium ${getHosColor(driver.hosDutyHoursRemaining)}`}>
                            {formatDuration(driver.hosDutyHoursRemaining)}
                          </td>
                          <td className="px-4 py-3 text-sm">{driver.hosCycleHoursUsed.toFixed(1)}h / 70h</td>
                          <td className="px-4 py-3 text-sm">
                            {driver.lastLocation ? (
                              <span className="flex items-center gap-1">
                                <MapPin className="w-3 h-3" />
                                {driver.lastLocation.latitude.toFixed(2)}, {driver.lastLocation.longitude.toFixed(2)}
                              </span>
                            ) : '-'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {activeTab === 'carriers' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {carriersLoading ? (
            <div className="col-span-full p-8 text-center text-opsgrid-text-secondary">Loading carriers...</div>
          ) : carriers.map(carrier => (
            <div key={carrier.id} className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h3 className="font-semibold">{carrier.name}</h3>
                  <p className="text-sm text-opsgrid-text-secondary">SCAC: {carrier.scac || 'N/A'}</p>
                </div>
                <span className={`px-2 py-1 rounded text-xs ${
                  carrier.ctpatCertified ? 'bg-green-500/20 text-green-500' : 'bg-gray-500/20 text-gray-500'
                }`}>
                  {carrier.ctpatCertified ? 'CT-PAT' : 'Non CT-PAT'}
                </span>
              </div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-opsgrid-text-secondary">Safety Rating:</span>
                  <span className={`capitalize ${
                    carrier.safetyRating === 'satisfactory' ? 'text-green-500' :
                    carrier.safetyRating === 'conditional' ? 'text-yellow-500' :
                    'text-red-500'
                  }`}>{carrier.safetyRating || 'Unknown'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-opsgrid-text-secondary">Compliance Score:</span>
                  <span className={carrier.complianceScore >= 90 ? 'text-green-500' : carrier.complianceScore >= 80 ? 'text-yellow-500' : 'text-red-500'}>
                    {carrier.complianceScore}%
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-opsgrid-text-secondary">On-Time Performance:</span>
                  <span className={carrier.onTimePerformance >= 90 ? 'text-green-500' : 'text-yellow-500'}>
                    {carrier.onTimePerformance}%
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-opsgrid-text-secondary">Authority:</span>
                  <span className="capitalize">{carrier.operatingAuthority.replace('_', ' ')}</span>
                </div>
              </div>
              <div className="mt-4 pt-3 border-t border-opsgrid-border">
                <p className="text-xs text-opsgrid-text-secondary">Contact</p>
                <p className="text-sm">{carrier.contactPhone}</p>
                <p className="text-sm text-opsgrid-text-secondary">{carrier.contactEmail}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'compliance' && (
        <div className="space-y-6">
          {complianceSummary && (
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
                <p className="text-sm text-opsgrid-text-secondary">Total Carriers</p>
                <p className="text-2xl font-bold">{complianceSummary.totalCarriers}</p>
              </div>
              <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
                <p className="text-sm text-opsgrid-text-secondary">CT-PAT Certified</p>
                <p className="text-2xl font-bold text-green-500">{complianceSummary.ctpatCertified}</p>
              </div>
              <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
                <p className="text-sm text-opsgrid-text-secondary">Active Violations</p>
                <p className={`text-2xl font-bold ${complianceSummary.activeViolations > 0 ? 'text-red-500' : 'text-green-500'}`}>
                  {complianceSummary.activeViolations}
                </p>
              </div>
              <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
                <p className="text-sm text-opsgrid-text-secondary">Safety Alerts</p>
                <p className={`text-2xl font-bold ${complianceSummary.safetyAlerts > 0 ? 'text-yellow-500' : 'text-green-500'}`}>
                  {complianceSummary.safetyAlerts}
                </p>
              </div>
            </div>
          )}

          {/* HOS Violations */}
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
            <h3 className="font-semibold mb-4 flex items-center gap-2">
              <Clock className="w-5 h-5 text-opsgrid-primary" />
              Hours of Service (HOS) Violations
            </h3>
            {drivers.filter(d => d.hosDriveHoursRemaining === 0).length === 0 ? (
              <div className="bg-green-500/10 border border-green-500/50 rounded-lg p-4 text-center">
                <CheckCircle2 className="w-8 h-8 text-green-500 mx-auto mb-2" />
                <p className="text-green-500 font-medium">No HOS violations detected</p>
                <p className="text-sm text-opsgrid-text-secondary">All drivers are within legal driving limits</p>
              </div>
            ) : (
              <div className="space-y-2">
                {drivers.filter(d => d.hosDriveHoursRemaining === 0).map(driver => (
                  <div key={driver.id} className="bg-red-500/10 border border-red-500/50 rounded-lg p-3 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <AlertTriangle className="w-5 h-5 text-red-500" />
                      <div>
                        <p className="font-medium">{driver.firstName} {driver.lastName}</p>
                        <p className="text-sm text-opsgrid-text-secondary">{driver.carrierName}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="font-medium text-red-500">Drive Limit Exceeded</p>
                      <p className="text-sm text-opsgrid-text-secondary">Cycle: {driver.hosCycleHoursUsed}h / 70h</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Insurance & Registration Alerts */}
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
            <h3 className="font-semibold mb-4">Expiration Alerts</h3>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-opsgrid-bg/50">
                  <tr>
                    <th className="px-4 py-2 text-left text-sm font-medium text-opsgrid-text-secondary">Type</th>
                    <th className="px-4 py-2 text-left text-sm font-medium text-opsgrid-text-secondary">Entity</th>
                    <th className="px-4 py-2 text-left text-sm font-medium text-opsgrid-text-secondary">Expires</th>
                    <th className="px-4 py-2 text-left text-sm font-medium text-opsgrid-text-secondary">Days Left</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-opsgrid-border">
                  {carriers.filter(c => c.insuranceExpiry && new Date(c.insuranceExpiry).getTime() - Date.now() < 30 * 86400000).map(carrier => {
                    const daysLeft = Math.floor((new Date(carrier.insuranceExpiry!).getTime() - Date.now()) / 86400000);
                    return (
                      <tr key={`ins-${carrier.id}`}>
                        <td className="px-4 py-2 text-sm">Insurance</td>
                        <td className="px-4 py-2 text-sm">{carrier.name}</td>
                        <td className="px-4 py-2 text-sm">{new Date(carrier.insuranceExpiry!).toLocaleDateString()}</td>
                        <td className={`px-4 py-2 text-sm font-medium ${daysLeft < 7 ? 'text-red-500' : 'text-yellow-500'}`}>
                          {daysLeft} days
                        </td>
                      </tr>
                    );
                  })}
                  {vehicles.filter(v => v.registrationExpiry && new Date(v.registrationExpiry).getTime() - Date.now() < 30 * 86400000).map(vehicle => {
                    const daysLeft = Math.floor((new Date(vehicle.registrationExpiry!).getTime() - Date.now()) / 86400000);
                    return (
                      <tr key={`reg-${vehicle.id}`}>
                        <td className="px-4 py-2 text-sm">Registration</td>
                        <td className="px-4 py-2 text-sm">{vehicle.vehicleNumber}</td>
                        <td className="px-4 py-2 text-sm">{new Date(vehicle.registrationExpiry!).toLocaleDateString()}</td>
                        <td className={`px-4 py-2 text-sm font-medium ${daysLeft < 7 ? 'text-red-500' : 'text-yellow-500'}`}>
                          {daysLeft} days
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Geofencing Tab */}
      {activeTab === 'geofencing' && (
        <GeofencingPanel />
      )}

      {/* Health & Security Tab */}
      {activeTab === 'health' && (
        <HealthSecurityPanel />
      )}

      {/* Maintenance Tab */}
      {activeTab === 'maintenance' && (
        <MaintenancePanel />
      )}

      {/* Performance Tab */}
      {activeTab === 'performance' && (
        <PerformancePanel />
      )}

      {/* Shipment Detail Modal */}
      {selectedShipment && (
        <ShipmentDetailModal
          shipment={selectedShipment}
          drivers={drivers}
          vehicles={vehicles}
          onClose={() => setSelectedShipment(null)}
          onChanged={() => {
            setSelectedShipment(null);
            refetchShipments();
          }}
        />
      )}

      {/* Driver Detail Modal */}
      {selectedDriver && (
        <DriverDetailModal 
          driver={selectedDriver} 
          onClose={() => setSelectedDriver(null)} 
        />
      )}
    </div>
  );
};

// Components
const StatCard: FC<{ label: string; value: string | number; icon: any; color?: string }> = ({ 
  label, 
  value, 
  icon: Icon, 
  color = 'text-opsgrid-text' 
}) => (
  <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-3">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-xs text-opsgrid-text-secondary">{label}</p>
        <p className={`text-lg font-bold ${color}`}>{value}</p>
      </div>
      <Icon className={`w-5 h-5 ${color}`} />
    </div>
  </div>
);

const ShipmentDetailModal: FC<{
  shipment: Shipment;
  drivers: Driver[];
  vehicles: Vehicle[];
  onClose: () => void;
  onChanged: () => void;
}> = ({ shipment, drivers, vehicles, onClose, onChanged }) => {
  const [costs, setCosts] = useState<any>(null);
  const [dispatchDriverId, setDispatchDriverId] = useState('');
  const [dispatchVehicleId, setDispatchVehicleId] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const runAction = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name);
    setActionError(null);
    try {
      await fn();
      onChanged();
    } catch (e: any) {
      setActionError(e?.response?.data?.detail || `${name} failed`);
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => {
    transportationApi.getShipmentCosts(shipment.id).then(setCosts);
  }, [shipment.id]);

  return (
    <div 
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-[100] p-4"
      onClick={onClose}
    >
      <div 
        className="bg-opsgrid-panel border border-opsgrid-border rounded-lg max-w-2xl w-full max-h-[90vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-6 border-b border-opsgrid-border flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Package className="w-6 h-6 text-opsgrid-primary" />
            <div>
              <h2 className="text-xl font-bold">{shipment.shipmentNumber}</h2>
              <p className="text-sm text-opsgrid-text-secondary">{shipment.poNumber}</p>
            </div>
          </div>
          <button onClick={onClose} className="text-opsgrid-text-secondary hover:text-opsgrid-text">
            ✕
          </button>
        </div>
        <div className="p-6 space-y-6">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Status</p>
              <p className="font-medium capitalize">{shipment.status.replace('_', ' ')}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Carrier</p>
              <p className="font-medium">{shipment.carrierName}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Driver</p>
              <p className="font-medium">{shipment.driverName || 'Not assigned'}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Vehicle</p>
              <p className="font-medium">{shipment.vehicleId || 'Not assigned'}</p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="bg-opsgrid-bg rounded-lg p-4">
              <p className="text-sm text-opsgrid-text-secondary mb-2">Origin</p>
              <p className="font-medium">{shipment.origin.name}</p>
              <p className="text-sm text-opsgrid-text-secondary">{shipment.origin.city}, {shipment.origin.state}</p>
              <p className="text-xs text-opsgrid-text-secondary mt-2">
                Scheduled: {new Date(shipment.scheduledPickup).toLocaleString()}
              </p>
            </div>
            <div className="bg-opsgrid-bg rounded-lg p-4">
              <p className="text-sm text-opsgrid-text-secondary mb-2">Destination</p>
              <p className="font-medium">{shipment.destination.name}</p>
              <p className="text-sm text-opsgrid-text-secondary">{shipment.destination.city}, {shipment.destination.state}</p>
              <p className="text-xs text-opsgrid-text-secondary mt-2">
                Scheduled: {new Date(shipment.scheduledDelivery).toLocaleString()}
              </p>
            </div>
          </div>

          {shipment.currentLocation && (
            <div className="bg-opsgrid-bg rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <MapPin className="w-4 h-4 text-opsgrid-primary" />
                <h4 className="font-medium">Current Location (GeoTab)</h4>
              </div>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <p className="text-opsgrid-text-secondary">Latitude</p>
                  <p>{shipment.currentLocation.latitude.toFixed(4)}</p>
                </div>
                <div>
                  <p className="text-opsgrid-text-secondary">Longitude</p>
                  <p>{shipment.currentLocation.longitude.toFixed(4)}</p>
                </div>
                <div>
                  <p className="text-opsgrid-text-secondary">Speed</p>
                  <p>{shipment.currentLocation.speed?.toFixed(0) || 0} mph</p>
                </div>
              </div>
            </div>
          )}

          <div className="grid grid-cols-3 gap-4">
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Weight</p>
              <p className="font-medium">{shipment.weight?.toLocaleString() || 'N/A'} kg</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Pieces</p>
              <p className="font-medium">{shipment.pieces || 'N/A'}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Pallets</p>
              <p className="font-medium">{shipment.palletCount || 'N/A'}</p>
            </div>
          </div>

          {shipment.temperatureRequired && (
            <div className="flex items-center gap-2">
              <Thermometer className="w-4 h-4 text-opsgrid-primary" />
              <span className="text-sm">Required Temperature: {shipment.temperatureRequired}°C</span>
            </div>
          )}

          {costs && (
            <div className="bg-opsgrid-bg rounded-lg p-4">
              <h4 className="font-medium mb-3">Cost Breakdown</h4>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-opsgrid-text-secondary">Freight</span>
                  <span>${costs.freight.toFixed(2)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-opsgrid-text-secondary">Fuel Surcharge</span>
                  <span>${costs.fuel.toFixed(2)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-opsgrid-text-secondary">Accessorials</span>
                  <span>${costs.accessorials.toFixed(2)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-opsgrid-text-secondary">Detention</span>
                  <span className={costs.detention > 0 ? 'text-red-500' : ''}>${costs.detention.toFixed(2)}</span>
                </div>
                <div className="pt-2 border-t border-opsgrid-border flex justify-between font-semibold">
                  <span>Total</span>
                  <span>${costs.total.toFixed(2)}</span>
                </div>
              </div>
            </div>
          )}

          {/* Lifecycle actions (task D22): dispatch / delivered / cancel. */}
          <div className="border-t border-opsgrid-border pt-4 space-y-3">
            {actionError && <p className="text-sm text-status-alarm">{actionError}</p>}
            {shipment.status === 'planned' && (
              <div className="flex flex-wrap items-center gap-2">
                <select
                  aria-label="Dispatch driver"
                  className="px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
                  value={dispatchDriverId}
                  onChange={(e) => setDispatchDriverId(e.target.value)}
                >
                  <option value="">Select driver…</option>
                  {drivers.map((d) => (
                    <option key={d.id} value={d.id}>{d.firstName} {d.lastName}</option>
                  ))}
                </select>
                <select
                  aria-label="Dispatch vehicle"
                  className="px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
                  value={dispatchVehicleId}
                  onChange={(e) => setDispatchVehicleId(e.target.value)}
                >
                  <option value="">Select vehicle…</option>
                  {vehicles.map((v) => (
                    <option key={v.id} value={v.id}>{v.vehicleNumber}</option>
                  ))}
                </select>
                <button
                  disabled={!dispatchDriverId || !dispatchVehicleId || busy !== null}
                  onClick={() =>
                    runAction('Dispatch', () =>
                      transportationApi.dispatchShipment(shipment.id, dispatchDriverId, dispatchVehicleId)
                    )
                  }
                  className="px-4 py-2 bg-opsgrid-primary text-opsgrid-bg rounded-lg text-sm disabled:opacity-50"
                >
                  {busy === 'Dispatch' ? 'Dispatching…' : 'Dispatch Shipment'}
                </button>
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2">
              {['dispatched', 'picked_up', 'in_transit'].includes(shipment.status) && (
                <button
                  disabled={busy !== null}
                  onClick={() =>
                    runAction('Mark delivered', () =>
                      transportationApi.updateShipmentStatus(shipment.id, 'delivered')
                    )
                  }
                  className="px-4 py-2 border border-status-running text-status-running rounded-lg text-sm hover:bg-status-running/10 disabled:opacity-50"
                >
                  {busy === 'Mark delivered' ? 'Updating…' : 'Mark Delivered'}
                </button>
              )}
              {['planned', 'dispatched'].includes(shipment.status) && (
                <button
                  disabled={busy !== null}
                  onClick={() =>
                    runAction('Cancel shipment', () =>
                      transportationApi.updateShipmentStatus(shipment.id, 'cancelled')
                    )
                  }
                  className="px-4 py-2 border border-status-alarm text-status-alarm rounded-lg text-sm hover:bg-status-alarm/10 disabled:opacity-50"
                >
                  {busy === 'Cancel shipment' ? 'Cancelling…' : 'Cancel Shipment'}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

const DriverDetailModal: FC<{ driver: Driver; onClose: () => void }> = ({ driver, onClose }) => {
  return (
    <div 
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-[100] p-4"
      onClick={onClose}
    >
      <div 
        className="bg-opsgrid-panel border border-opsgrid-border rounded-lg max-w-lg w-full"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-6 border-b border-opsgrid-border flex items-center justify-between">
          <div className="flex items-center gap-3">
            <User className="w-6 h-6 text-opsgrid-primary" />
            <div>
              <h2 className="text-xl font-bold">{driver.firstName} {driver.lastName}</h2>
              <p className="text-sm text-opsgrid-text-secondary">{driver.carrierName}</p>
            </div>
          </div>
          <button onClick={onClose} className="text-opsgrid-text-secondary hover:text-opsgrid-text">
            ✕
          </button>
        </div>
        <div className="p-6 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-opsgrid-text-secondary">CDL Class</p>
              <p className="font-medium">{driver.cdlClass}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Endorsements</p>
              <p className="font-medium">{driver.endorsements.join(', ') || 'None'}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Hazmat Certified</p>
              <p className="font-medium">{driver.hazmatCertified ? 'Yes' : 'No'}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">License Expires</p>
              <p className="font-medium">{new Date(driver.licenseExpiry).toLocaleDateString()}</p>
            </div>
          </div>

          <div className="bg-opsgrid-bg rounded-lg p-4">
            <h4 className="font-medium mb-3">Hours of Service (HOS)</h4>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-sm text-opsgrid-text-secondary">Current Status</span>
                <span className="text-sm capitalize">{driver.currentHosStatus.replace('_', ' ')}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-opsgrid-text-secondary">Drive Hours Remaining</span>
                <span className={`font-medium ${driver.hosDriveHoursRemaining === 0 ? 'text-red-500' : driver.hosDriveHoursRemaining < 2 ? 'text-yellow-500' : 'text-green-500'}`}>
                  {driver.hosDriveHoursRemaining.toFixed(1)}h
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-opsgrid-text-secondary">Duty Hours Remaining</span>
                <span className={`font-medium ${driver.hosDutyHoursRemaining === 0 ? 'text-red-500' : driver.hosDutyHoursRemaining < 2 ? 'text-yellow-500' : 'text-green-500'}`}>
                  {driver.hosDutyHoursRemaining.toFixed(1)}h
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-opsgrid-text-secondary">Cycle Hours Used</span>
                <span className="font-medium">{driver.hosCycleHoursUsed.toFixed(1)}h / 70h</span>
              </div>
            </div>
          </div>

          {driver.currentVehicleId && (
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Current Vehicle</p>
              <p className="font-medium">{driver.currentVehicleId}</p>
            </div>
          )}

          {driver.geoTabDeviceId && (
            <div className="bg-opsgrid-bg rounded-lg p-3">
              <p className="text-xs text-opsgrid-text-secondary">GeoTab Device ID</p>
              <p className="text-sm font-mono">{driver.geoTabDeviceId}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default TransportationManagement;
