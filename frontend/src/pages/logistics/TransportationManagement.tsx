import { FC, forwardRef, type HTMLAttributes, useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
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
import type { ShipmentCosts } from '../../api/transportation';
import { transportationApi, geoTabApi, yardApi } from '../../api';
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
  YardTrailer,
  ShipmentFilters,
  GeoLocation,
  MapFilterType
} from '../../types';
import { Button, Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';

// Four outcomes, not three: exhausted, low, ample, and NOT REPORTED. The last was
// previously indistinguishable from "low", because `null < 2` coerces to `0 < 2` — so a
// driver who had reported nothing was painted as a driver running short of hours.
// Module scope because the drivers table and the driver detail panel are separate
// components and both have to answer this the same way.
// A tile that renders nothing rather than a bare unit. The fleet card previously printed
// "{undefined} mph" and "{undefined} mi" — a label, a space and a unit — which reads as a
// measurement of zero rather than as an absent one.
const FleetStat: FC<{ label: string; value?: number; unit?: string; tone?: string }> = ({
  label,
  value,
  unit,
  tone,
}) => (
  <div className="bg-opsgrid-bg rounded-lg p-3">
    <p className="text-xs text-opsgrid-text-secondary">{label}</p>
    <p className={`text-xl font-bold ${tone ?? ''}`}>
      {value == null ? '—' : unit ? `${value} ${unit}` : value}
    </p>
  </div>
);

const hosClass = (hours: number | null | undefined): string =>
  hours == null
    ? 'text-opsgrid-text-secondary'
    : hours === 0
      ? 'text-red-500'
      : hours < 2
        ? 'text-yellow-500'
        : 'text-green-500';


const TRANSPORT_QUERY_KEY = 'transportation';

/** A money figure, or an em dash when the server could not estimate one (FS-665).
 *
 *  `$0.00` is not the honest render for "not calculated": the comment on the cost breakdown
 *  already makes that argument about accessorials, and it applies identically to a charge the
 *  server declines to estimate. Null reaches here whenever a shipment has no route distance.
 */
const money = (amount: number | null): string =>
  amount === null ? '—' : `$${amount.toFixed(2)}`;

export const TransportationManagement: FC = () => {
  const [selectedShipment, setSelectedShipment] = useState<Shipment | null>(null);
  const [selectedDriver, setSelectedDriver] = useState<Driver | null>(null);
  const [selectedVehicle, setSelectedVehicle] = useState<Vehicle | null>(null);
  const [filters, setFilters] = useState<ShipmentFilters>({});
  const [searchTerm, setSearchTerm] = useState('');
  const [activeTab, setActiveTab] = useState<'shipments' | 'fleet' | 'carriers' | 'compliance' | 'geofencing' | 'health' | 'maintenance' | 'performance'>('shipments');
  const [fleetLocation, setFleetLocation] = useState<GeoLocation | null>(null);
  const [selectedMapVehicle, setSelectedMapVehicle] = useState<string | null>(null);
  const [selectedMapShipment, setSelectedMapShipment] = useState<string | null>(null);

  const {
    data: shipmentsData,
    isLoading: shipmentsLoading,
    isError: shipmentsError,
    refetch: refetchShipments,
  } = useQuery({
    queryKey: [TRANSPORT_QUERY_KEY, 'shipments', filters],
    queryFn: () => transportationApi.getShipments(filters),
  });

  const { data: carriersData, isLoading: carriersLoading, isError: carriersError } =
    useQuery({
    queryKey: [TRANSPORT_QUERY_KEY, 'carriers'],
    queryFn: () => transportationApi.getCarriers(),
  });

  const { data: driversData, isLoading: driversLoading, isError: driversError } =
    useQuery({
    queryKey: [TRANSPORT_QUERY_KEY, 'drivers'],
    queryFn: () => transportationApi.getDrivers(),
  });

  // Yard trailers, for the dispatch picker (FS-420). From the yard API because that is
  // where trailers live — `Shipment.trailer_id` is a foreign key to `yard_trailers`.
  const { data: trailersData } = useQuery({
    queryKey: [TRANSPORT_QUERY_KEY, 'trailers'],
    queryFn: () => yardApi.getTrailers(),
  });

  const { data: vehiclesData, isLoading: vehiclesLoading, isError: vehiclesError } =
    useQuery({
    queryKey: [TRANSPORT_QUERY_KEY, 'vehicles'],
    queryFn: () => transportationApi.getVehicles(),
  });

  const { data: fleetSummary, isError: fleetSummaryError } = useQuery({
    queryKey: [TRANSPORT_QUERY_KEY, 'fleet-summary'],
    queryFn: () => geoTabApi.getFleetSummary(),
  });

  const { data: deliveryEfficiency, isError: deliveryEfficiencyError } = useQuery({
    queryKey: [TRANSPORT_QUERY_KEY, 'efficiency'],
    queryFn: () => transportationApi.getDeliveryEfficiency(),
  });

  const { data: complianceSummary, isError: complianceSummaryError } = useQuery({
    queryKey: [TRANSPORT_QUERY_KEY, 'compliance'],
    queryFn: () => transportationApi.getComplianceSummary(),
  });

  const allShipments = shipmentsData?.items || [];
  const shipments = searchTerm
    ? allShipments.filter((s) =>
        [s.shipmentNumber, s.poNumber, s.carrierName, s.driverName]
          .filter(Boolean)
          .some((v) => String(v).toLowerCase().includes(searchTerm.toLowerCase()))
      )
    : allShipments;
  const carriers = carriersData?.items || [];
  const drivers = driversData?.items || [];
  const vehicles = vehiclesData?.items || [];
  // Trailers, for the dispatch picker. A shipment records `trailer_id` — a foreign key to
  // yard_trailers — and has no vehicle column at all, so the vehicle picker this modal used
  // to offer could never have produced a storable value (FS-420).
  const trailers = trailersData?.items || [];

  const stats = {
    totalShipments: shipments.length,
    inTransit: shipments.filter(s => s.status === 'in_transit').length,
    delivered: shipments.filter(s => s.status === 'delivered').length,
    planned: shipments.filter(s => s.status === 'planned').length,
    activeDrivers: drivers.filter(d => d.currentHosStatus === 'driving' || d.currentHosStatus === 'on_duty').length,
    offDutyDrivers: drivers.filter(d => d.currentHosStatus === 'off_duty').length,
    // `=== 0` on a field that is null for every driver who has not reported. `null === 0`
    // is false, so an unreported driver counted as compliant — the same "absence read as
    // clearance" the failed-query branch below was already fixed for, arriving through
    // the SUCCESS path instead.
    hosViolations: drivers.filter(d => d.hosDriveHoursRemaining === 0).length,
    hosUnassessable: drivers.filter(d => d.hosDriveHoursRemaining == null).length,
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


  // `== null`, not `=== undefined`. The API sends JSON null for an unreported driver and
  // `null === undefined` is FALSE, so this fell through to `null.toFixed(1)` and threw —
  // taking the whole drivers tab down with it on any deployment where the column was
  // unpopulated, which was all of them. It never surfaced because the mock fixtures
  // supply a number for every driver.
  const formatDuration = (hours?: number | null) => {
    if (hours == null) return 'not reported';
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
      {fleetSummaryError && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <p className="text-status-alarm text-sm">Failed to load GeoTab fleet status.</p>
        </div>
      )}
      {fleetSummary && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <h3 className="font-semibold mb-1 flex items-center gap-2">
            <Activity className="w-5 h-5 text-opsgrid-primary" />
            {/* WAS "Fleet Status (GeoTab Live)". Every GeoTab payload carries
                `simulated: true` and a warning that the figures are "not valid for DOT/ELD
                compliance reporting" — stamped server-side precisely so a consumer could
                tell — and nothing read it while the heading claimed the data was live. */}
            Fleet Status{fleetSummary.simulated ? ' (simulated)' : ' (GeoTab Live)'}
          </h3>
          {fleetSummary.simulated && (
            <p role="alert" className="text-xs text-status-warning mb-3">
              {fleetSummary.dataSourceWarning ??
                'Simulated telematics. Not measured from a device and not valid for DOT/ELD compliance reporting.'}
            </p>
          )}
          {/* Only the figures the endpoint actually reports. This card promised
              totalVehicles / vehiclesMoving / vehiclesIdle / avgSpeed / totalDistanceToday
              / fuelConsumedToday, and the API sends none of those names — so all six
              rendered blank, two of them beside bare units (" mph", " mi"). `avgSpeed` and
              fuel CONSUMED have no counterpart at all; the server reports fuel
              EFFICIENCY, which is a different quantity, and is shown as itself. */}
          <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
            <FleetStat label="Devices" value={fleetSummary.totalDevices} />
            <FleetStat label="Active" value={fleetSummary.activeDevices} tone="text-green-500" />
            <FleetStat label="Drivers" value={fleetSummary.totalDrivers} />
            <FleetStat label="On Duty" value={fleetSummary.driversOnDuty} tone="text-yellow-500" />
            <FleetStat label="Distance Today" value={fleetSummary.totalMilesToday} unit="mi" />
            <FleetStat label="Fuel Efficiency" value={fleetSummary.averageFuelEfficiency} unit="mpg" />
          </div>
        </div>
      )}

      {/* Delivery Efficiency */}
      {deliveryEfficiencyError && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <p className="text-status-alarm text-sm">Failed to load delivery efficiency metrics.</p>
        </div>
      )}
      {deliveryEfficiency && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
            <p className="text-sm text-opsgrid-text-secondary">On-Time Delivery Rate</p>
            <div className="flex items-end gap-2">
              {/* `onTimeRatePct`, not `onTimeRate`: the wire sends a RATIO 0..1, so this
                  tile printed 0.3% for a genuine 33.3% and the 90 threshold could never be
                  reached. The client converts once and puts the unit in the name (FS-394). */}
              {/* Null means the figure did not arrive, and an em dash says so. It must not
                  fall back to a number: `?? 100` here would paint a green all-clear out of a
                  malformed response. */}
              <p className={`text-2xl font-bold ${
                deliveryEfficiency.onTimeRatePct !== null && deliveryEfficiency.onTimeRatePct >= 90
                  ? 'text-green-500' : 'text-yellow-500'}`}>
                {deliveryEfficiency.onTimeRatePct === null
                  ? '—'
                  : `${deliveryEfficiency.onTimeRatePct.toFixed(1)}%`}
              </p>
            </div>
          </div>
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
            <p className="text-sm text-opsgrid-text-secondary">Average Transit Time</p>
            <p className="text-2xl font-bold">
              {deliveryEfficiency.avgTransitHours === null ? '—' : `${deliveryEfficiency.avgTransitHours}h`}
            </p>
          </div>
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
            <p className="text-sm text-opsgrid-text-secondary">Deliveries Today</p>
            <p className="text-2xl font-bold">
              {deliveryEfficiency.deliveredToday === null ? '—' : deliveryEfficiency.deliveredToday}
            </p>
            {/* Was `{lateDeliveries} late`, a field the endpoint has never sent. The count
                is not derivable from what it does send without rounding a percentage back
                into a count, so this reports the figure that IS sent instead of inferring
                one. */}
            {deliveryEfficiency.totalDelivered !== null && (
              <p className="text-sm text-opsgrid-text-secondary">
                {deliveryEfficiency.totalDelivered} delivered in total
              </p>
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
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
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
          ) : shipmentsError ? (
            /* A FAILED QUERY IS NOT AN EMPTY BOARD. This fell through to "No shipments
               found", which a dispatcher reads as "nothing is in transit" — an
               operational fact they plan around. Three OTHER queries on this page
               already handled `isError`, which is why the sweep for this defect class
               passed the file: it checked whether the FILE mentions isError, not
               whether THIS query does. */
            <div className="p-8 text-center space-y-3" role="alert">
              <p className="text-status-alarm">
                Couldn’t load shipments — this is a loading failure, not an empty board.
              </p>
              <Button variant="secondary" onClick={() => refetchShipments()}>
                Retry
              </Button>
            </div>
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
                          <span className="capitalize">{shipment.status?.replace('_', ' ')}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-sm">{shipment.carrierName}</td>
                      <td className="px-4 py-3 text-sm">
                        <div>
                          {/* A live position for the shipment was rendered here from
                              `currentLocation`, which `shipments` has no column for and no
                              endpoint has ever sent. The nearest real position belongs to the
                              driver's vehicle, two hops away, and goes stale the moment they
                              change vehicle. */}
                          <p>{shipment.origin.city} → {shipment.destination.city}</p>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {/* WAS a running-late warning: yellow when `estimatedDelivery`
                            exceeded `scheduledDelivery`. Nothing in this product predicts a
                            delivery time, so the field was never sent and the branch never
                            taken — the column silently showed the schedule instead. It shows
                            the schedule, and says so. */}
                        {shipment.scheduledDelivery
                          ? new Date(shipment.scheduledDelivery).toLocaleDateString()
                          : '-'}
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
              ) : vehiclesError ? (
                <div className="col-span-full p-8 text-center" role="alert">
                  <p className="text-status-alarm">
                    Couldn’t load vehicles — this is a loading failure, not an empty fleet.
                  </p>
                </div>
              ) : vehicles.length === 0 ? (
                <div className="col-span-full p-8 text-center text-opsgrid-text-secondary">No vehicles found</div>
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
                  {vehicle.lastLocation && (
                    <div className="mt-3 pt-3 border-t border-opsgrid-border">
                      <p className="text-xs text-opsgrid-text-secondary flex items-center gap-1">
                        <MapPin className="w-3 h-3" />
                        {vehicle.lastLocation.latitude.toFixed(4)}, {vehicle.lastLocation.longitude.toFixed(4)}
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
              ) : driversError ? (
                <div className="p-8 text-center" role="alert">
                  <p className="text-status-alarm">
                    Couldn’t load drivers — this is a loading failure, not an empty roster.
                  </p>
                </div>
              ) : drivers.length === 0 ? (
                <div className="p-8 text-center text-opsgrid-text-secondary">No drivers found</div>
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
                              {driver.currentHosStatus?.replace('_', ' ')}
                            </span>
                          </td>
                          <td className={`px-4 py-3 font-medium ${hosClass(driver.hosDriveHoursRemaining)}`}>
                            {formatDuration(driver.hosDriveHoursRemaining)}
                          </td>
                          <td className={`px-4 py-3 font-medium ${hosClass(driver.hosDutyHoursRemaining)}`}>
                            {/* Same null handling as the drive-hours cell beside it —
                                `getHosColor` takes a plain number and paints null amber,
                                the colour meaning "nearly out of hours". */}
                            {formatDuration(driver.hosDutyHoursRemaining)}
                          </td>
                          {/* `hos_cycle_hours` is nullable too, and this was the third
                              unguarded `.toFixed()` in one row — each of which takes the
                              whole tab down rather than blanking one cell. */}
                          <td className="px-4 py-3 text-sm">
                            {driver.hosCycleHoursUsed == null
                              ? 'not reported'
                              : `${driver.hosCycleHoursUsed.toFixed(1)}h / 70h`}
                          </td>
                          <td className="px-4 py-3 text-sm">
                            {/* `drivers` has no position column. This cell was always '-';
                                a driver's position is their vehicle's, which the vehicle
                                panel shows. The column now names the vehicle they are on,
                                which the API resolves from `vehicles.current_driver_id`. */}
                            {driver.currentVehicleId ?? '-'}
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
          ) : carriersError ? (
            <div className="col-span-full p-8 text-center" role="alert">
              <p className="text-status-alarm">
                Couldn’t load carriers — this is a loading failure, not an empty list.
              </p>
            </div>
          ) : carriers.length === 0 ? (
            <div className="col-span-full p-8 text-center text-opsgrid-text-secondary">No carriers found</div>
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
                  <span className="capitalize">{carrier.operatingAuthority?.replace('_', ' ')}</span>
                </div>
              </div>
              {/* A "Contact" SECTION WITH NOTHING IN IT. `carriers` has no contact_phone or
                  contact_email column — the table carries DOT/MC numbers, C-TPAT and
                  insurance dates, safety rating, CSA score, SCAC and operating authority,
                  and no way to reach anybody. So this rendered a heading above two empty
                  lines for every carrier.
                  Removed rather than filled with "not recorded", which would be permanent
                  noise on every row. Carrier contact details are collected nowhere in this
                  product; that is a gap in the schema, recorded in
                  docs/engineering/defect-class-sweeps.md, not something a panel can paper
                  over. */}
            </div>
          ))}
        </div>
      )}

      {activeTab === 'compliance' && (
        <div className="space-y-6">
          {complianceSummaryError && (
            <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
              <p className="text-status-alarm text-sm">Failed to load compliance summary.</p>
            </div>
          )}
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
              {/* GREEN ZERO WAS AN ALL-CLEAR NOBODY HAD EARNED. The rollup counted
                  `(hos_drive_hours_today or 0) >= 11`, so a driver who had not reported
                  coerced to zero hours and cleared the threshold; a fleet where nobody had
                  reported showed 0 violations in green. The count is now taken over the
                  drivers it could actually assess, and zero is only green when there were
                  some — otherwise it is grey, with the number that explains it. */}
              <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
                <p className="text-sm text-opsgrid-text-secondary">Active Violations</p>
                <p className={`text-2xl font-bold ${
                  complianceSummary.activeViolations > 0
                    ? 'text-red-500'
                    : complianceSummary.driversAssessed === 0
                      ? 'text-opsgrid-text-secondary'
                      : 'text-green-500'
                }`}>
                  {complianceSummary.activeViolations}
                </p>
                {complianceSummary.driversUnassessable != null
                  && complianceSummary.driversUnassessable > 0 && (
                  <p className="text-xs text-yellow-600 mt-1">
                    {complianceSummary.driversUnassessable} driver
                    {complianceSummary.driversUnassessable === 1 ? '' : 's'} unassessed — no
                    hours reported
                  </p>
                )}
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
            {driversError ? (
              /* THE WORST VERSION OF THIS DEFECT IN THE CODEBASE. On a failed drivers
                 query `drivers` is [], so the filter returned nothing and this rendered
                 a GREEN TICK reading "No HOS violations detected" — a positive
                 compliance assurance about DOT-regulated Hours of Service, produced by
                 a request that never returned. A compliance officer reads a green tick
                 as clearance. Unknown is not the same as clear. */
              <div className="bg-status-alarm/10 border border-status-alarm/50 rounded-lg p-4 text-center" role="alert">
                <AlertTriangle className="w-8 h-8 text-status-alarm mx-auto mb-2" />
                <p className="text-status-alarm font-medium">
                  HOS status unknown — driver data could not be loaded
                </p>
                <p className="text-xs text-opsgrid-text-secondary mt-1">
                  This is not a clean bill of compliance; it means the check could not run.
                </p>
              </div>
            ) : stats.hosUnassessable > 0 ? (
              /* THE SECOND WAY THIS WAS WRONG. The branch above covers a failed query;
                 this one covers a query that SUCCEEDED and returned drivers whose hours
                 nobody has reported. `hosDriveHoursRemaining` is null for them, `null ===
                 0` is false, and they fell straight through to the green tick below.
                 Every fleet was cleared. Hours of Service is DOT-regulated and a
                 compliance officer reads that tick as clearance. */
              <div className="bg-status-warning/10 border border-status-warning/50 rounded-lg p-4 text-center" role="alert">
                <AlertTriangle className="w-8 h-8 text-status-warning mx-auto mb-2" />
                <p className="text-status-warning font-medium">
                  {stats.hosUnassessable} of {drivers.length} drivers have no reported hours
                </p>
                <p className="text-xs text-opsgrid-text-secondary mt-1">
                  Their Hours of Service cannot be checked. This is missing data, not a
                  clean record — and not a violation either.
                </p>
              </div>
            ) : drivers.filter(d => d.hosDriveHoursRemaining === 0).length === 0 ? (
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
          trailers={trailers}
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

      {/* Vehicle Detail Modal */}
      {selectedVehicle && (
        <VehicleDetailModal
          vehicle={selectedVehicle}
          onClose={() => setSelectedVehicle(null)}
        />
      )}
    </div>
  );
};

// Components
//
// forwardRef AND `...rest`, because all nine of these sit inside `<TooltipTrigger asChild>`.
// Radix's Slot clones the child to merge in a ref and its own event handlers; a plain
// function component that destructures only its own props silently drops BOTH. The result
// was not a cosmetic React warning — it was nine dead tooltips. Verified by hovering
// "Total Shipments" against a running app: 0 elements with role="tooltip", 0 Radix poppers.
// Same shape, same fix, in YardManagement.tsx.
const StatCard = forwardRef<
  HTMLDivElement,
  { label: string; value: string | number; icon: any; color?: string } & HTMLAttributes<HTMLDivElement>
>(({ label, value, icon: Icon, color = 'text-opsgrid-text', ...rest }, ref) => (
  <div ref={ref} {...rest} className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-3">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-xs text-opsgrid-text-secondary">{label}</p>
        <p className={`text-lg font-bold ${color}`}>{value}</p>
      </div>
      <Icon className={`w-5 h-5 ${color}`} />
    </div>
  </div>
));
StatCard.displayName = 'StatCard';

const ShipmentDetailModal: FC<{
  shipment: Shipment;
  drivers: Driver[];
  //: Trailers, not vehicles. The modal used to take `vehicles` for the dispatch picker;
  //: a shipment has no vehicle column, so nothing it offered could be stored (FS-420).
  trailers: YardTrailer[];
  onClose: () => void;
  onChanged: () => void;
}> = ({ shipment, drivers, trailers, onClose, onChanged }) => {
  // TYPED, NOT `any` — and `any` is why this pane rendered five undefined values without
  // tsc noticing (FS-397). The client's declared shape was wrong, and the one place that
  // could have compared them opted out. A wrong type at least fails the build; `any`
  // guarantees it never will.
  const [costs, setCosts] = useState<ShipmentCosts | null>(null);
  const [dispatchDriverId, setDispatchDriverId] = useState('');
  const [dispatchTrailerId, setDispatchTrailerId] = useState('');
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

  // FS-588. THREE DEFECTS IN TWO LINES, and all three show one shipment's MONEY under
  // another shipment's name.
  //
  //   `getShipmentCosts(shipment.id).then(setCosts)` with `[shipment.id]`
  //
  //   1. NO CLEAR. Switching from shipment A to B leaves A's linehaul, fuel surcharge and
  //      total on screen, under B's heading, until B's request returns.
  //   2. NO CATCH. If B's request FAILS, A's figures stay there permanently — the panel
  //      never stops attributing them to B, and an unhandled rejection is the only trace.
  //   3. NO CANCELLATION. If A's request is slow and B's is fast, A's response lands
  //      second and overwrites B's. Both requests succeeded; the screen is still wrong,
  //      and it stays wrong until something else re-renders.
  //
  // A stale list is a visible annoyance. A stale COST is a number a dispatcher reads and
  // acts on, and nothing about it looks stale.
  const [costsError, setCostsError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // Cleared FIRST, so the gap between shipments renders as absent rather than as the
    // previous shipment's figures.
    setCosts(null);
    setCostsError(false);
    transportationApi
      .getShipmentCosts(shipment.id)
      .then((loaded) => {
        if (!cancelled) setCosts(loaded);
      })
      .catch(() => {
        if (!cancelled) setCostsError(true);
      });
    return () => {
      cancelled = true;
    };
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
              <p className="font-medium capitalize">{shipment.status?.replace('_', ' ')}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Carrier</p>
              <p className="font-medium">{shipment.carrierName}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Driver</p>
              <p className="font-medium">{shipment.driverName || 'Not assigned'}</p>
            </div>
            {/* TRAILER, not vehicle (FS-439). This read `shipment.vehicleId`, which
                `shipments` has no column for and no handler computes — so every shipment
                in the product rendered "Not assigned" under a Vehicle heading, which is a
                STATEMENT, not a blank. A shipment references a trailer; `trailerId` was
                declared here all along and is sent. */}
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Trailer</p>
              <p className="font-medium">{shipment.trailerId || 'Not assigned'}</p>
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

          {/* A "Current Location (GeoTab)" card sat here with latitude, longitude and speed,
              fed by `shipment.currentLocation` — a field `shipments` has no column for and no
              endpoint has ever sent, so the card never appeared. The heading was the most
              specific claim in it: GeoTab is not the source of a shipment's position, because
              nothing is. The vehicle panel shows `vehicles.last_location`, which is real. */}

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

          {costsError && (
            <p role="alert" className="text-sm text-status-alarm">
              Could not load costs for this shipment.
            </p>
          )}
          {costs && (
            <div className="bg-opsgrid-bg rounded-lg p-4">
              <h4 className="font-medium mb-3">Cost Breakdown</h4>
              <div className="space-y-2 text-sm">
                {/* The money is on nested charge objects — `linehaul.amount` and
                    `fuelSurcharge.amount`. Every line here used to read a flat field the
                    endpoint has never sent, so all five called .toFixed(2) on undefined
                    (FS-397).

                    Accessorials and Detention are GONE rather than shown as $0.00: this
                    endpoint does not bill either, and a zero in a cost breakdown reads as
                    "nothing was charged" rather than "not calculated here". The mock
                    computed both, which is why the panel looked complete in development. */}
                {/* NOT ESTIMATED is a state, not a zero (FS-665). The same argument as the
                    missing accessorials above: the server used to substitute 500 miles for a
                    shipment with no route and bill $1,250 against it, reporting
                    `distanceMiles: 500` as fact — this panel rendered "500 mi" and a
                    confident total. It now answers null, and a dash is the honest render. */}
                {costs.linehaul.rateBasis === 'not_estimated' && (
                  <p role="status" className="text-xs text-status-warning">
                    No route distance on this shipment, so the per-mile charges cannot be
                    estimated. Assign a route, or price it by hand.
                  </p>
                )}
                <div className="flex justify-between">
                  <span className="text-opsgrid-text-secondary">Linehaul</span>
                  <span>{money(costs.linehaul.amount)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-opsgrid-text-secondary">
                    Fuel Surcharge
                    <span className="ml-1 text-xs">({costs.fuelSurcharge.rateBasis})</span>
                  </span>
                  <span>{money(costs.fuelSurcharge.amount)}</span>
                </div>
                {costs.distanceMiles !== null && (
                  <div className="flex justify-between">
                    <span className="text-opsgrid-text-secondary">Distance</span>
                    <span>{costs.distanceMiles.toFixed(0)} mi</span>
                  </div>
                )}
                <div className="pt-2 border-t border-opsgrid-border flex justify-between font-semibold">
                  <span>Total</span>
                  <span>{money(costs.totalCost)}</span>
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
                  aria-label="Dispatch trailer"
                  className="px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
                  value={dispatchTrailerId}
                  onChange={(e) => setDispatchTrailerId(e.target.value)}
                >
                  <option value="">Select trailer…</option>
                  {trailers.map((t) => (
                    <option key={t.id} value={t.id}>{t.trailerId}</option>
                  ))}
                </select>
                <button
                  disabled={!dispatchDriverId || !dispatchTrailerId || busy !== null}
                  onClick={() =>
                    runAction('Dispatch', () =>
                      transportationApi.dispatchShipment(shipment.id, dispatchDriverId, dispatchTrailerId)
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
              <p className="font-medium">{driver.endorsements?.join(', ') || 'None'}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Hazmat Certified</p>
              <p className="font-medium">{driver.hazmatCertified ? 'Yes' : 'No'}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">License Expires</p>
              <p className="font-medium">{driver.licenseExpiry ? new Date(driver.licenseExpiry).toLocaleDateString() : 'N/A'}</p>
            </div>
          </div>

          <div className="bg-opsgrid-bg rounded-lg p-4">
            <h4 className="font-medium mb-3">Hours of Service (HOS)</h4>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-sm text-opsgrid-text-secondary">Current Status</span>
                <span className="text-sm capitalize">{driver.currentHosStatus?.replace('_', ' ')}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-opsgrid-text-secondary">Drive Hours Remaining</span>
                {/* `null < 2` is `0 < 2` — true — so an unreported driver was coloured as
                    a warning and captioned "N/Ah". Neither the number nor the colour was
                    a statement anyone had earned. */}
                <span className={`font-medium ${hosClass(driver.hosDriveHoursRemaining)}`}>
                  {driver.hosDriveHoursRemaining == null
                    ? 'not reported'
                    : `${driver.hosDriveHoursRemaining.toFixed(1)}h`}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-opsgrid-text-secondary">Duty Hours Remaining</span>
                <span className={`font-medium ${hosClass(driver.hosDutyHoursRemaining)}`}>
                  {driver.hosDutyHoursRemaining == null
                    ? 'not reported'
                    : `${driver.hosDutyHoursRemaining.toFixed(1)}h`}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-opsgrid-text-secondary">Cycle Hours Used</span>
                <span className="font-medium">{driver.hosCycleHoursUsed?.toFixed(1) ?? 'N/A'}h / 70h</span>
              </div>
            </div>
          </div>

          {driver.currentVehicleId && (
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Current Vehicle</p>
              <p className="font-medium">{driver.currentVehicleId}</p>
            </div>
          )}

          {/* WAS "GeoTab Device ID" reading `driver.geoTabDeviceId`. Drivers have no
              GeoTab device: the column is `eld_device_id`, an ELD, which is a different
              system with different compliance meaning. The row could never populate, and
              the id the driver DOES have was being sent and never shown. */}
          {driver.eldDeviceId && (
            <div className="bg-opsgrid-bg rounded-lg p-3">
              <p className="text-xs text-opsgrid-text-secondary">ELD Device ID</p>
              <p className="text-sm font-mono">{driver.eldDeviceId}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const VehicleDetailModal: FC<{ vehicle: Vehicle; onClose: () => void }> = ({ vehicle, onClose }) => {
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
            <Truck className="w-6 h-6 text-opsgrid-primary" />
            <div>
              <h2 className="text-xl font-bold">{vehicle.vehicleNumber}</h2>
              <p className="text-sm text-opsgrid-text-secondary">
                {[vehicle.year, vehicle.make, vehicle.model].filter(Boolean).join(' ') || 'Vehicle details'}
              </p>
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
              <p className="font-medium">{vehicle.currentDriverId ? 'Active' : 'Idle'}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Carrier</p>
              <p className="font-medium">{vehicle.carrierName || 'N/A'}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Type</p>
              <p className="font-medium capitalize">{vehicle.vehicleType?.replace('_', ' ') || 'N/A'}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Fuel Type</p>
              <p className="font-medium capitalize">{vehicle.fuelType || 'N/A'}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">License Plate</p>
              <p className="font-medium">{vehicle.licensePlate || 'N/A'}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">VIN</p>
              <p className="font-medium">{vehicle.vin || 'N/A'}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">DOT Number</p>
              <p className="font-medium">{vehicle.dotNumber || 'N/A'}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Gross Vehicle Weight</p>
              <p className="font-medium">{vehicle.grossVehicleWeight?.toLocaleString() ?? 'N/A'} kg</p>
            </div>
          </div>

          <div className="bg-opsgrid-bg rounded-lg p-4">
            <h4 className="font-medium mb-3 flex items-center gap-2">
              <Activity className="w-4 h-4 text-opsgrid-primary" />
              Telematics
            </h4>
            <div className="grid grid-cols-3 gap-4 text-sm">
              <div>
                <p className="text-opsgrid-text-secondary flex items-center gap-1">
                  <Fuel className="w-3 h-3" /> Fuel Level
                </p>
                <p className="font-medium">{vehicle.fuelLevel ?? 'N/A'}%</p>
              </div>
              <div>
                <p className="text-opsgrid-text-secondary flex items-center gap-1">
                  <Gauge className="w-3 h-3" /> Odometer
                </p>
                <p className="font-medium">{vehicle.odometer?.toLocaleString() ?? 'N/A'} mi</p>
              </div>
              <div>
                <p className="text-opsgrid-text-secondary">Engine Hours</p>
                <p className="font-medium">{vehicle.engineHours?.toLocaleString() ?? 'N/A'}</p>
              </div>
            </div>
          </div>

          {vehicle.lastLocation && (
            <div className="bg-opsgrid-bg rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <MapPin className="w-4 h-4 text-opsgrid-primary" />
                <h4 className="font-medium">Current Location (GeoTab)</h4>
              </div>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <p className="text-opsgrid-text-secondary">Latitude</p>
                  <p>{vehicle.lastLocation.latitude.toFixed(4)}</p>
                </div>
                <div>
                  <p className="text-opsgrid-text-secondary">Longitude</p>
                  <p>{vehicle.lastLocation.longitude.toFixed(4)}</p>
                </div>
                <div>
                  <p className="text-opsgrid-text-secondary">Speed</p>
                  <p>{vehicle.lastLocation.speed?.toFixed(0) || 0} mph</p>
                </div>
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Registration Expires</p>
              <p className="font-medium">
                {vehicle.registrationExpiry ? new Date(vehicle.registrationExpiry).toLocaleDateString() : 'N/A'}
              </p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Inspection Due</p>
              <p className="font-medium">
                {vehicle.inspectionDue ? new Date(vehicle.inspectionDue).toLocaleDateString() : 'N/A'}
              </p>
            </div>
          </div>

          {/* `geotabDeviceId`, not `geoTabDeviceId`. The column is `geotab_device_id` and
              the casing seam lower-cases the t, so the old name matched nothing. */}
          {vehicle.geotabDeviceId && (
            <div className="bg-opsgrid-bg rounded-lg p-3">
              <p className="text-xs text-opsgrid-text-secondary">GeoTab Device ID</p>
              <p className="text-sm font-mono">{vehicle.geotabDeviceId}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default TransportationManagement;
