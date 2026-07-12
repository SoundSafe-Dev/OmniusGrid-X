import { FC, useState, useEffect } from 'react';
import { useQuery } from 'react-query';
import {
  Truck,
  Warehouse,
  Clock,
  AlertTriangle,
  MapPin,
  CheckCircle2,
  ArrowRightLeft,
  Calendar,
  Filter,
  Search,
  RefreshCw,
  DollarSign,
  Thermometer,
  Package
} from 'lucide-react';
import { yardApi } from '../../api';
import {
  YardTrailer,
  DockDoor,
  TrailerFilters
} from '../../types';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';
import { YardMapPanel } from '../../components/yard/YardMapPanel';

const YARD_QUERY_KEY = 'yard';

export const YardManagement: FC = () => {
  const [selectedTrailer, setSelectedTrailer] = useState<YardTrailer | null>(null);
  const [selectedDoor, setSelectedDoor] = useState<DockDoor | null>(null);
  const [filters, setFilters] = useState<TrailerFilters>({});
  const [searchTerm, setSearchTerm] = useState('');
  const [showCheckIn, setShowCheckIn] = useState(false);
  const [activeTab, setActiveTab] = useState<'trailers' | 'map' | 'doors' | 'appointments' | 'detention'>('trailers');

  const { data: trailersData, isLoading: trailersLoading, refetch: refetchTrailers } = useQuery(
    [YARD_QUERY_KEY, 'trailers', filters],
    () => yardApi.getTrailers(filters)
  );

  const { data: doorsData, isLoading: doorsLoading } = useQuery(
    [YARD_QUERY_KEY, 'doors'],
    () => yardApi.getDockDoors()
  );

  const { data: appointmentsData, isLoading: appointmentsLoading } = useQuery(
    [YARD_QUERY_KEY, 'appointments'],
    () => yardApi.getAppointments()
  );

  const { data: detentionAlerts } = useQuery(
    [YARD_QUERY_KEY, 'detention'],
    () => yardApi.getDetentionAlerts()
  );

  const { data: dwellTimes } = useQuery(
    [YARD_QUERY_KEY, 'dwell-times'],
    () => yardApi.getDwellTimes()
  );

  const allTrailers = trailersData?.items || [];
  const trailers = searchTerm
    ? allTrailers.filter((t) =>
        [t.trailerId, t.carrierName, t.licensePlate]
          .filter(Boolean)
          .some((v) => String(v).toLowerCase().includes(searchTerm.toLowerCase()))
      )
    : allTrailers;
  const doors = doorsData || [];
  const appointments = appointmentsData?.items || [];
  const alerts = detentionAlerts || [];

  const stats = {
    totalTrailers: trailers.length,
    inYard: trailers.filter(t => t.status === 'yard').length,
    docked: trailers.filter(t => t.status === 'docked').length,
    inTransit: trailers.filter(t => t.status === 'in_transit').length,
    detentionRisk: trailers.filter(t => t.detentionRisk === 'high' || t.detentionRisk === 'medium').length,
    totalDetentionCost: trailers.reduce((sum, t) => sum + t.detentionCost, 0),
    availableDoors: doors.filter(d => d.status === 'available').length,
    occupiedDoors: doors.filter(d => d.status === 'occupied').length,
    todayAppointments: appointments.filter(a => {
      const apptDate = new Date(a.scheduledArrival).toDateString();
      const today = new Date().toDateString();
      return apptDate === today;
    }).length,
  };

  const getStatusColor = (status: YardTrailer['status']) => {
    switch (status) {
      case 'docked': return 'bg-green-500';
      case 'yard': return 'bg-blue-500';
      case 'in_transit': return 'bg-yellow-500';
      case 'outbound': return 'bg-purple-500';
      case 'maintenance': return 'bg-gray-500';
      default: return 'bg-gray-400';
    }
  };

  const getDoorStatusColor = (status: DockDoor['status']) => {
    switch (status) {
      case 'available': return 'bg-green-500';
      case 'occupied': return 'bg-blue-500';
      case 'reserved': return 'bg-yellow-500';
      case 'maintenance': return 'bg-red-500';
      case 'blocked': return 'bg-gray-500';
      default: return 'bg-gray-400';
    }
  };

  const getDetentionColor = (risk: YardTrailer['detentionRisk']) => {
    switch (risk) {
      case 'low': return 'text-green-500';
      case 'medium': return 'text-yellow-500';
      case 'high': return 'text-red-500';
      default: return 'text-gray-400';
    }
  };

  const getTrailerTypeIcon = (type: YardTrailer['trailerType']) => {
    switch (type) {
      case 'reefer': return <Thermometer className="w-4 h-4" />;
      case 'container': return <Package className="w-4 h-4" />;
      default: return <Truck className="w-4 h-4" />;
    }
  };

  const formatDuration = (minutes?: number) => {
    if (!minutes) return 'N/A';
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <Tooltip>
          <TooltipTrigger asChild>
            <div>
              <h1 className="text-2xl font-bold flex items-center gap-2">
                <Warehouse className="w-6 h-6 text-opsgrid-primary" />
                Yard Management System (YMS)
              </h1>
              <p className="text-opsgrid-text-secondary mt-1">
                Real-time trailer tracking, dock scheduling, and detention management
              </p>
            </div>
          </TooltipTrigger>
          <TooltipContent>Yard management system overview</TooltipContent>
        </Tooltip>
        <div className="flex items-center gap-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={() => setShowCheckIn(true)}
                className="flex items-center gap-2 px-4 py-2 bg-opsgrid-primary text-opsgrid-bg rounded-lg hover:bg-opsgrid-accent transition-colors"
              >
                <Truck className="w-4 h-4" />
                Check In Trailer
              </button>
            </TooltipTrigger>
            <TooltipContent>Check a trailer into the yard</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={() => refetchTrailers()}
                className="flex items-center gap-2 px-4 py-2 bg-opsgrid-panel border border-opsgrid-border rounded-lg hover:bg-opsgrid-border transition-colors"
              >
                <RefreshCw className="w-4 h-4" />
                Refresh
              </button>
            </TooltipTrigger>
            <TooltipContent>Refresh yard data</TooltipContent>
          </Tooltip>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4">
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard label="Total Trailers" value={stats.totalTrailers} icon={Truck} />
          </TooltipTrigger>
          <TooltipContent>Total number of trailers in the system</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard label="In Yard" value={stats.inYard} icon={Warehouse} color="text-blue-500" />
          </TooltipTrigger>
          <TooltipContent>Trailers currently in the yard</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard label="Docked" value={stats.docked} icon={CheckCircle2} color="text-green-500" />
          </TooltipTrigger>
          <TooltipContent>Trailers currently docked at doors</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard label="In Transit" value={stats.inTransit} icon={ArrowRightLeft} color="text-yellow-500" />
          </TooltipTrigger>
          <TooltipContent>Trailers currently in transit</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard
              label="Detention Risk"
              value={stats.detentionRisk}
              icon={AlertTriangle}
              color={stats.detentionRisk > 0 ? 'text-red-500' : 'text-green-500'}
            />
          </TooltipTrigger>
          <TooltipContent>Trailers at risk of detention fees</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard
              label="Detention Cost"
              value={`$${stats.totalDetentionCost}`}
              icon={DollarSign}
              color={stats.totalDetentionCost > 0 ? 'text-red-500' : 'text-green-500'}
            />
          </TooltipTrigger>
          <TooltipContent>Total detention costs incurred</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard label="Available Doors" value={stats.availableDoors} icon={Warehouse} color="text-green-500" />
          </TooltipTrigger>
          <TooltipContent>Dock doors currently available</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <StatCard label="Today's Appts" value={stats.todayAppointments} icon={Calendar} color="text-blue-500" />
          </TooltipTrigger>
          <TooltipContent>Scheduled appointments for today</TooltipContent>
        </Tooltip>
      </div>

      {/* Dwell Time Alert */}
      {dwellTimes && dwellTimes.trailersExceedingTarget > 0 && (
        <div className="bg-yellow-500/10 border border-yellow-500/50 rounded-lg p-4 flex items-center gap-3">
          <Clock className="w-5 h-5 text-yellow-500" />
          <div>
            <p className="font-medium text-yellow-500">
              {dwellTimes.trailersExceedingTarget} trailers exceeding target dwell time
            </p>
            <p className="text-sm text-opsgrid-text-secondary">
              Average dwell time: {formatDuration(dwellTimes.avgDwellTime)} (Target: 120 min)
            </p>
          </div>
        </div>
      )}

      {/* Detention Alerts */}
      {alerts.length > 0 && (
        <div className="bg-red-500/10 border border-red-500/50 rounded-lg p-4">
          <h3 className="font-semibold text-red-500 flex items-center gap-2 mb-3">
            <AlertTriangle className="w-5 h-5" />
            Detention Alerts ({alerts.length})
          </h3>
          <div className="space-y-2">
            {alerts.map(alert => (
              <div key={alert.id} className="flex items-center justify-between bg-opsgrid-bg rounded-lg p-3">
                <div className="flex items-center gap-3">
                  <Truck className="w-4 h-4 text-opsgrid-text-secondary" />
                  <div>
                    <p className="font-medium">{alert.trailerLicensePlate || alert.trailerId}</p>
                    <p className="text-sm text-opsgrid-text-secondary">
                      {alert.carrierName} • {alert.location}
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="font-medium text-red-500">${alert.estimatedCost}</p>
                  <p className="text-sm text-opsgrid-text-secondary">
                    {formatDuration(alert.excessMinutes)} excess
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-opsgrid-border">
        <div className="flex gap-1">
          {[
            { id: 'trailers', label: 'Trailers', icon: Truck, tooltip: 'View all trailers' },
            { id: 'map', label: 'Yard Map', icon: MapPin, tooltip: 'Dock and zone occupancy map' },
            { id: 'doors', label: 'Dock Doors', icon: Warehouse, tooltip: 'View dock door status' },
            { id: 'appointments', label: 'Appointments', icon: Calendar, tooltip: 'View scheduled appointments' },
            { id: 'detention', label: 'Detention', icon: DollarSign, tooltip: 'View detention alerts and costs' },
          ].map(tab => (
            <Tooltip key={tab.id}>
              <TooltipTrigger asChild>
                <button
                  onClick={() => setActiveTab(tab.id as typeof activeTab)}
                  className={`flex items-center gap-2 px-4 py-2 border-b-2 transition-colors ${
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
      {activeTab === 'trailers' && (
        <div className="flex flex-wrap gap-3 items-center">
          <div className="flex items-center gap-2 px-3 py-2 bg-opsgrid-panel border border-opsgrid-border rounded-lg">
            <Filter className="w-4 h-4 text-opsgrid-text-secondary" />
            <select
              value={filters.status || ''}
              onChange={(e) => setFilters({ ...filters, status: e.target.value as any })}
              className="bg-transparent text-sm focus:outline-none"
            >
              <option value="">All Statuses</option>
              <option value="yard">In Yard</option>
              <option value="docked">Docked</option>
              <option value="in_transit">In Transit</option>
              <option value="outbound">Outbound</option>
            </select>
          </div>
          <div className="flex items-center gap-2 px-3 py-2 bg-opsgrid-panel border border-opsgrid-border rounded-lg">
            <Search className="w-4 h-4 text-opsgrid-text-secondary" />
            <input
              type="text"
              placeholder="Search trailer..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="bg-transparent text-sm focus:outline-none w-40"
            />
          </div>
        </div>
      )}

      {/* Content */}
      {activeTab === 'trailers' && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg overflow-hidden">
          {trailersLoading ? (
            <div className="p-8 text-center text-opsgrid-text-secondary">Loading trailers...</div>
          ) : trailers.length === 0 ? (
            <div className="p-8 text-center text-opsgrid-text-secondary">No trailers found</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-opsgrid-bg/50">
                  <tr>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Trailer</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Status</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Carrier</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Location</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Duration</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Detention</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Contents</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-opsgrid-border">
                  {trailers.map(trailer => (
                    <tr 
                      key={trailer.id} 
                      className="hover:bg-opsgrid-bg/50 cursor-pointer"
                      onClick={() => setSelectedTrailer(trailer)}
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          {getTrailerTypeIcon(trailer.trailerType)}
                          <div>
                            <p className="font-medium">{trailer.trailerId}</p>
                            <p className="text-sm text-opsgrid-text-secondary">{trailer.licensePlate}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${getStatusColor(trailer.status)}`} />
                          <span className="capitalize">{trailer.status.replace('_', ' ')}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-sm">{trailer.carrierName}</td>
                      <td className="px-4 py-3 text-sm">
                        {trailer.yardLocation || trailer.assignedDoorId || '-'}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {trailer.checkedInAt && (
                          <span className="flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            {formatDuration(Math.floor((Date.now() - new Date(trailer.checkedInAt).getTime()) / 60000))}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className={`font-medium ${getDetentionColor(trailer.detentionRisk)}`}>
                          ${trailer.detentionCost}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-sm text-opsgrid-text-secondary truncate max-w-xs">
                        {trailer.contents || '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === 'map' && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-6">
          <YardMapPanel doors={doors} trailers={allTrailers} onTrailerClick={setSelectedTrailer} />
        </div>
      )}

      {activeTab === 'doors' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {doorsLoading ? (
            <div className="col-span-full p-8 text-center text-opsgrid-text-secondary">Loading doors...</div>
          ) : doors.map(door => (
            <div 
              key={door.id}
              className={`bg-opsgrid-panel border rounded-lg p-4 cursor-pointer transition-all ${
                selectedDoor?.id === door.id ? 'border-opsgrid-primary ring-1 ring-opsgrid-primary' : 'border-opsgrid-border'
              }`}
              onClick={() => setSelectedDoor(door)}
            >
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-semibold">{door.doorNumber}</h3>
                <span className={`w-3 h-3 rounded-full ${getDoorStatusColor(door.status)}`} />
              </div>
              <p className="text-sm text-opsgrid-text-secondary mb-2">{door.workcellName}</p>
              <p className="text-sm capitalize">{door.status.replace('_', ' ')}</p>
              {door.currentTrailerId && (
                <div className="mt-3 pt-3 border-t border-opsgrid-border">
                  <p className="text-sm font-medium">Occupied by:</p>
                  <p className="text-sm text-opsgrid-text-secondary">{door.trailerLicensePlate}</p>
                  {door.estimatedReleaseAt && (
                    <p className="text-xs text-opsgrid-text-secondary mt-1">
                      Release: {new Date(door.estimatedReleaseAt).toLocaleTimeString()}
                    </p>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {activeTab === 'appointments' && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg overflow-hidden">
          {appointmentsLoading ? (
            <div className="p-8 text-center text-opsgrid-text-secondary">Loading appointments...</div>
          ) : appointments.length === 0 ? (
            <div className="p-8 text-center text-opsgrid-text-secondary">No appointments found</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-opsgrid-bg/50">
                  <tr>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Time</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Carrier</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Trailer</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Type</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Door</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Status</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-opsgrid-text-secondary">Priority</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-opsgrid-border">
                  {appointments.map(appt => (
                    <tr key={appt.id} className="hover:bg-opsgrid-bg/50">
                      <td className="px-4 py-3">
                        <div className="text-sm">
                          <p>{new Date(appt.scheduledArrival).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</p>
                          <p className="text-xs text-opsgrid-text-secondary">
                            {new Date(appt.scheduledArrival).toLocaleDateString()}
                          </p>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-sm">{appt.carrierName}</td>
                      <td className="px-4 py-3 text-sm">{appt.trailerLicensePlate || appt.trailerId || '-'}</td>
                      <td className="px-4 py-3 text-sm capitalize">{appt.appointmentType}</td>
                      <td className="px-4 py-3 text-sm">{appt.doorNumber || 'Not assigned'}</td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          appt.status === 'docked' ? 'bg-green-500/20 text-green-500' :
                          appt.status === 'scheduled' ? 'bg-blue-500/20 text-blue-500' :
                          appt.status === 'complete' ? 'bg-gray-500/20 text-gray-500' :
                          'bg-yellow-500/20 text-yellow-500'
                        }`}>
                          {appt.status.replace('_', ' ')}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-sm capitalize ${
                          appt.priority === 'urgent' ? 'text-red-500' :
                          appt.priority === 'high' ? 'text-yellow-500' :
                          'text-green-500'
                        }`}>
                          {appt.priority}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === 'detention' && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-6">
          <h3 className="font-semibold mb-4">Detention & Demurrage Summary</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="bg-opsgrid-bg rounded-lg p-4">
              <p className="text-sm text-opsgrid-text-secondary">Today's Detention Cost</p>
              <p className="text-2xl font-bold text-red-500">${stats.totalDetentionCost}</p>
            </div>
            <div className="bg-opsgrid-bg rounded-lg p-4">
              <p className="text-sm text-opsgrid-text-secondary">Trailers at Risk</p>
              <p className="text-2xl font-bold text-yellow-500">{stats.detentionRisk}</p>
            </div>
            <div className="bg-opsgrid-bg rounded-lg p-4">
              <p className="text-sm text-opsgrid-text-secondary">Avg Dwell Time</p>
              <p className="text-2xl font-bold">{formatDuration(dwellTimes?.avgDwellTime)}</p>
            </div>
          </div>
          <div className="mt-6">
            <h4 className="font-medium mb-3">Detention Rate Schedule</h4>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-opsgrid-bg/50">
                  <tr>
                    <th className="px-4 py-2 text-left text-sm font-medium text-opsgrid-text-secondary">Hours</th>
                    <th className="px-4 py-2 text-left text-sm font-medium text-opsgrid-text-secondary">Rate</th>
                    <th className="px-4 py-2 text-left text-sm font-medium text-opsgrid-text-secondary">Description</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-opsgrid-border">
                  <tr>
                    <td className="px-4 py-2 text-sm">0-2 hours</td>
                    <td className="px-4 py-2 text-sm text-green-500">$0</td>
                    <td className="px-4 py-2 text-sm text-opsgrid-text-secondary">Free time included</td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2 text-sm">2-4 hours</td>
                    <td className="px-4 py-2 text-sm text-yellow-500">$50/hr</td>
                    <td className="px-4 py-2 text-sm text-opsgrid-text-secondary">Standard detention rate</td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2 text-sm">4+ hours</td>
                    <td className="px-4 py-2 text-sm text-red-500">$75/hr</td>
                    <td className="px-4 py-2 text-sm text-opsgrid-text-secondary">Extended detention rate</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Trailer Detail Modal */}
      {selectedTrailer && (
        <TrailerDetailModal
          trailer={selectedTrailer}
          doors={doors}
          onClose={() => setSelectedTrailer(null)}
          onChanged={() => {
            setSelectedTrailer(null);
            refetchTrailers();
          }}
        />
      )}

      {/* Check-In Modal */}
      {showCheckIn && (
        <CheckInModal
          onClose={() => setShowCheckIn(false)}
          onCheckedIn={() => {
            setShowCheckIn(false);
            refetchTrailers();
          }}
        />
      )}
    </div>
  );
};

// Check a new trailer into the yard (task C18).
const CheckInModal: FC<{ onClose: () => void; onCheckedIn: () => void }> = ({ onClose, onCheckedIn }) => {
  const [trailerId, setTrailerId] = useState('');
  const [carrierName, setCarrierName] = useState('');
  const [trailerType, setTrailerType] = useState<YardTrailer['trailerType']>('dry_van');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!trailerId.trim()) {
      setError('Trailer ID is required');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await yardApi.checkInTrailer({
        trailerId: trailerId.trim(),
        carrierName: carrierName.trim() || 'Unknown Carrier',
        trailerType,
        status: 'yard',
      } as Partial<YardTrailer>);
      onCheckedIn();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Check-in failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" role="dialog" aria-modal="true">
      <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg max-w-md w-full p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold">Check In Trailer</h2>
          <button onClick={onClose} aria-label="Close" className="text-opsgrid-text-secondary hover:text-opsgrid-text">✕</button>
        </div>
        <div>
          <label className="block text-sm text-opsgrid-text-secondary mb-1">Trailer ID</label>
          <input
            className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
            value={trailerId} onChange={(e) => setTrailerId(e.target.value)} placeholder="TRL-1042"
          />
        </div>
        <div>
          <label className="block text-sm text-opsgrid-text-secondary mb-1">Carrier</label>
          <input
            className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
            value={carrierName} onChange={(e) => setCarrierName(e.target.value)} placeholder="Carrier name"
          />
        </div>
        <div>
          <label className="block text-sm text-opsgrid-text-secondary mb-1">Type</label>
          <select
            className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
            value={trailerType} onChange={(e) => setTrailerType(e.target.value as YardTrailer['trailerType'])}
          >
            <option value="dry_van">Dry Van</option>
            <option value="reefer">Reefer</option>
            <option value="flatbed">Flatbed</option>
            <option value="container">Container</option>
          </select>
        </div>
        {error && <p className="text-sm text-status-alarm">{error}</p>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 border border-opsgrid-border rounded-lg text-sm">Cancel</button>
          <button
            onClick={submit}
            disabled={busy}
            className="px-4 py-2 bg-opsgrid-primary text-opsgrid-bg rounded-lg text-sm disabled:opacity-50"
          >
            {busy ? 'Checking in…' : 'Check In'}
          </button>
        </div>
      </div>
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

const TrailerDetailModal: FC<{
  trailer: YardTrailer;
  doors: DockDoor[];
  onClose: () => void;
  onChanged: () => void;
}> = ({ trailer, doors, onClose, onChanged }) => {
  const [location, setLocation] = useState<any>(null);
  const [assignDoorId, setAssignDoorId] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const availableDoors = doors.filter((d) => d.status === 'available');

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
    // Fetch real-time location if in transit
    if (trailer.status === 'in_transit' && trailer.lastLocation) {
      setLocation(trailer.lastLocation);
    }
  }, [trailer]);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg max-w-2xl w-full max-h-[90vh] overflow-auto">
        <div className="p-6 border-b border-opsgrid-border flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Truck className="w-6 h-6 text-opsgrid-primary" />
            <div>
              <h2 className="text-xl font-bold">{trailer.trailerId}</h2>
              <p className="text-sm text-opsgrid-text-secondary">{trailer.licensePlate}</p>
            </div>
          </div>
          <button onClick={onClose} className="text-opsgrid-text-secondary hover:text-opsgrid-text">
            ✕
          </button>
        </div>
        <div className="p-6 space-y-6">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Carrier</p>
              <p className="font-medium">{trailer.carrierName}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Type</p>
              <p className="font-medium capitalize">{trailer.trailerType.replace('_', ' ')}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Status</p>
              <p className="font-medium capitalize">{trailer.status.replace('_', ' ')}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Current Location</p>
              <p className="font-medium">{trailer.yardLocation || trailer.assignedDoorId || 'In Transit'}</p>
            </div>
          </div>

          {location && (
            <div className="bg-opsgrid-bg rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <MapPin className="w-4 h-4 text-opsgrid-primary" />
                <h4 className="font-medium">Current GPS Location (GeoTab)</h4>
              </div>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <p className="text-opsgrid-text-secondary">Latitude</p>
                  <p>{location.latitude.toFixed(4)}</p>
                </div>
                <div>
                  <p className="text-opsgrid-text-secondary">Longitude</p>
                  <p>{location.longitude.toFixed(4)}</p>
                </div>
                <div>
                  <p className="text-opsgrid-text-secondary">Speed</p>
                  <p>{location.speed?.toFixed(0) || 0} mph</p>
                </div>
              </div>
              <p className="text-xs text-opsgrid-text-secondary mt-2">
                Last updated: {new Date(location.timestamp).toLocaleString()}
              </p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-opsgrid-text-secondary">PO Number</p>
              <p className="font-medium">{trailer.poNumber || '-'}</p>
            </div>
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Seal Number</p>
              <p className="font-medium">{trailer.sealNumber || '-'}</p>
            </div>
          </div>

          <div>
            <p className="text-sm text-opsgrid-text-secondary">Contents</p>
            <p className="font-medium">{trailer.contents || '-'}</p>
          </div>

          {trailer.driverName && (
            <div className="bg-opsgrid-bg rounded-lg p-4">
              <h4 className="font-medium mb-2">Driver Information</h4>
              <p className="text-sm">{trailer.driverName}</p>
              {trailer.driverPhone && <p className="text-sm text-opsgrid-text-secondary">{trailer.driverPhone}</p>}
            </div>
          )}

          <div className="bg-opsgrid-bg rounded-lg p-4">
            <h4 className="font-medium mb-2">Detention Information</h4>
            <div className="grid grid-cols-3 gap-4 text-sm">
              <div>
                <p className="text-opsgrid-text-secondary">Risk Level</p>
                <p className={`capitalize ${
                  trailer.detentionRisk === 'high' ? 'text-red-500' :
                  trailer.detentionRisk === 'medium' ? 'text-yellow-500' :
                  'text-green-500'
                }`}>{trailer.detentionRisk}</p>
              </div>
              <div>
                <p className="text-opsgrid-text-secondary">Current Cost</p>
                <p className="font-medium">${trailer.detentionCost}</p>
              </div>
              <div>
                <p className="text-opsgrid-text-secondary">Checked In</p>
                <p>{trailer.checkedInAt ? new Date(trailer.checkedInAt).toLocaleString() : '-'}</p>
              </div>
            </div>
          </div>

          {/* Actions (task C18): assign door + check out, wired to the yard API. */}
          <div className="border-t border-opsgrid-border pt-4 space-y-3">
            {actionError && <p className="text-sm text-status-alarm">{actionError}</p>}
            <div className="flex flex-wrap items-center gap-2">
              {trailer.status === 'yard' && (
                <>
                  <select
                    aria-label="Assign to door"
                    className="px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
                    value={assignDoorId}
                    onChange={(e) => setAssignDoorId(e.target.value)}
                  >
                    <option value="">Select door…</option>
                    {availableDoors.map((d) => (
                      <option key={d.id} value={d.id}>Door {d.doorNumber ?? d.id}</option>
                    ))}
                  </select>
                  <button
                    disabled={!assignDoorId || busy !== null}
                    onClick={() => runAction('Assign door', () => yardApi.assignToDoor(trailer.id, assignDoorId))}
                    className="px-4 py-2 bg-opsgrid-primary text-opsgrid-bg rounded-lg text-sm disabled:opacity-50"
                  >
                    {busy === 'Assign door' ? 'Assigning…' : 'Assign to Door'}
                  </button>
                </>
              )}
              {trailer.status !== 'outbound' && (
                <button
                  disabled={busy !== null}
                  onClick={() => runAction('Check out', () => yardApi.checkOutTrailer(trailer.id))}
                  className="px-4 py-2 border border-status-alarm text-status-alarm rounded-lg text-sm hover:bg-status-alarm/10 disabled:opacity-50"
                >
                  {busy === 'Check out' ? 'Checking out…' : 'Check Out Trailer'}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default YardManagement;
