import { FC, useState, useEffect } from 'react';
import {
  Wrench, Calendar, AlertTriangle, DollarSign, Plus,
  Clock, Truck
} from 'lucide-react';
import { maintenanceApi } from '../../api';
import { SkeletonCard } from '../ui/Skeleton';
import type { MaintenanceSchedule, RepairOrder, MaintenanceCosts } from '../../types';

const getStatusColor = (status: string) => {
  switch (status) {
    case 'completed': return 'bg-green-100 text-green-700';
    case 'in_progress': return 'bg-blue-100 text-blue-700';
    case 'scheduled': return 'bg-gray-100 text-gray-700';
    case 'overdue': return 'bg-red-100 text-red-700';
    case 'waiting_parts': return 'bg-yellow-100 text-yellow-700';
    default: return 'bg-gray-100 text-gray-700';
  }
};

const getPriorityColor = (priority: string) => {
  switch (priority) {
    case 'urgent': return 'text-red-600 font-bold';
    case 'high': return 'text-orange-600 font-semibold';
    case 'normal': return 'text-blue-600';
    default: return 'text-gray-600';
  }
};

export const MaintenancePanel: FC = () => {
  const [schedules, setSchedules] = useState<MaintenanceSchedule[]>([]);
  const [repairOrders, setRepairOrders] = useState<RepairOrder[]>([]);
  const [costs, setCosts] = useState<MaintenanceCosts | null>(null);
  const [stats, setStats] = useState({ totalSchedules: 0, overdue: 0, activeROs: 0, urgentROs: 0 });
  const [activeTab, setActiveTab] = useState<'schedule' | 'repairs' | 'costs'>('schedule');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [schedulesData, repairData, costsData, statsData] = await Promise.all([
        maintenanceApi.getSchedules(),
        maintenanceApi.getActiveRepairOrders(),
        maintenanceApi.getMaintenanceCosts(),
        maintenanceApi.getMaintenanceStatistics(),
      ]);
      setSchedules(schedulesData);
      setRepairOrders(repairData);
      setCosts(costsData);
      setStats(statsData);
    } catch (err) {
      console.error('Failed to load maintenance data:', err);
      setError('Failed to load maintenance data. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const overdueMaintenance = schedules.filter(s => s.status === 'overdue');

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="bg-opsgrid-panel border border-opsgrid-border rounded-lg">
            <SkeletonCard lines={5} />
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
        <p className="text-status-alarm text-sm">{error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <Calendar className="w-5 h-5 text-blue-500" />
            <span className="text-sm text-gray-600">Scheduled</span>
          </div>
          <p className="text-2xl font-bold text-blue-600">{stats.totalSchedules}</p>
        </div>
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-5 h-5 text-red-500" />
            <span className="text-sm text-gray-600">Overdue</span>
          </div>
          <p className="text-2xl font-bold text-red-600">{stats.overdue}</p>
        </div>
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <Wrench className="w-5 h-5 text-orange-500" />
            <span className="text-sm text-gray-600">Active Repairs</span>
          </div>
          <p className="text-2xl font-bold text-orange-600">{stats.activeROs}</p>
        </div>
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <DollarSign className="w-5 h-5 text-green-500" />
            <span className="text-sm text-gray-600">YTD Costs</span>
          </div>
          <p className="text-2xl font-bold text-green-600">${costs?.totalYTD.toLocaleString() || 0}</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-opsgrid-border">
        {['schedule', 'repairs', 'costs'].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab as any)}
            className={`px-4 py-2 font-medium capitalize ${
              activeTab === tab 
                ? 'text-opsgrid-primary border-b-2 border-opsgrid-primary' 
                : 'text-gray-500 hover:text-opsgrid-primary'
            }`}
          >
            {tab === 'schedule' ? 'Maintenance Schedule' : tab === 'repairs' ? 'Repair Orders' : 'Cost Analysis'}
          </button>
        ))}
      </div>

      {/* Content */}
      {activeTab === 'schedule' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Overdue Alerts */}
          {overdueMaintenance.length > 0 && (
            <div className="lg:col-span-2 bg-red-50 border border-red-200 rounded-lg p-4">
              <h3 className="font-semibold text-red-700 flex items-center gap-2 mb-3">
                <AlertTriangle className="w-5 h-5" />
                Overdue Maintenance ({overdueMaintenance.length})
              </h3>
              <div className="space-y-2">
                {overdueMaintenance.map(item => (
                  <div key={item.id} className="bg-white rounded-lg p-3 flex items-center justify-between">
                    <div>
                      <p className="font-medium">{item.vehicleNumber} - {item.serviceType?.replace(/_/g, ' ')}</p>
                      <p className="text-sm text-gray-600">{item.description}</p>
                      <p className="text-xs text-red-500 mt-1">
                        Due: {new Date(item.scheduledDate).toLocaleDateString()}
                      </p>
                    </div>
                    <span className={`px-2 py-1 rounded text-xs font-medium ${getPriorityColor(item.priority)}`}>
                      {item.priority}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Upcoming Maintenance */}
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg lg:col-span-2">
            <div className="p-3 border-b border-opsgrid-border flex items-center justify-between">
              <h3 className="font-semibold flex items-center gap-2">
                <Calendar className="w-5 h-5 text-opsgrid-primary" />
                Upcoming Maintenance (Next 30 Days)
              </h3>
              <button
                onClick={() => setShowCreate(true)}
                className="p-2 bg-opsgrid-primary text-white rounded hover:bg-opsgrid-accent"
                title="Add maintenance schedule"
              >
                <Plus className="w-4 h-4" />
              </button>
            </div>
            <div className="max-h-[400px] overflow-y-auto">
              {schedules.filter(s => s.status === 'scheduled').length === 0 && (
                <p className="p-4 text-sm text-gray-500 text-center">No upcoming maintenance scheduled.</p>
              )}
              {schedules.filter(s => s.status === 'scheduled').map(item => (
                <div key={item.id} className="p-3 border-b border-opsgrid-border hover:bg-opsgrid-bg">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <Truck className="w-4 h-4 text-gray-400" />
                        <span className="font-medium">{item.vehicleNumber}</span>
                        <span className={`px-2 py-0.5 rounded text-xs ${getStatusColor(item.status)}`}>
                          {item.status}
                        </span>
                      </div>
                      <p className="text-sm text-gray-600 mt-1">{item.description}</p>
                      <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
                        <span className="flex items-center gap-1">
                          <Calendar className="w-3 h-3" />
                          {new Date(item.scheduledDate).toLocaleDateString()}
                        </span>
                        <span>Mileage: {item.currentMileage.toLocaleString()}</span>
                        {item.assignedTechnician && (
                          <span>Tech: {item.assignedTechnician}</span>
                        )}
                      </div>
                    </div>
                    <div className="text-right">
                      {item.estimatedCost && (
                        <p className="font-medium text-green-600">${item.estimatedCost}</p>
                      )}
                      <span className={`text-xs ${getPriorityColor(item.priority)}`}>
                        {item.priority}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {activeTab === 'repairs' && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg">
          <div className="p-3 border-b border-opsgrid-border">
            <h3 className="font-semibold flex items-center gap-2">
              <Wrench className="w-5 h-5 text-opsgrid-primary" />
              Active Repair Orders
            </h3>
          </div>
          <div className="max-h-[500px] overflow-y-auto">
            {repairOrders.length === 0 && (
              <p className="p-4 text-sm text-gray-500 text-center">No active repair orders.</p>
            )}
            {repairOrders.map(order => (
              <div key={order.id} className="p-4 border-b border-opsgrid-border hover:bg-opsgrid-bg">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold">{order.workOrderNumber}</span>
                      <span className={`px-2 py-0.5 rounded text-xs ${getStatusColor(order.status)}`}>
                        {order.status?.replace(/_/g, ' ')}
                      </span>
                      <span className={`text-xs ${getPriorityColor(order.priority)}`}>
                        {order.priority}
                      </span>
                    </div>
                    <p className="text-sm text-gray-600 mt-1">{order.issueDescription}</p>
                    <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
                      <span className="flex items-center gap-1">
                        <Truck className="w-3 h-3" />
                        {order.vehicleNumber}
                      </span>
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        Reported: {new Date(order.reportedDate).toLocaleDateString()}
                      </span>
                      {order.assignedTechnician && (
                        <span>Tech: {order.assignedTechnician}</span>
                      )}
                      {order.laborHours && (
                        <span>{order.laborHours} hours</span>
                      )}
                    </div>
                    {order.partsUsed.length > 0 && (
                      <div className="mt-2 text-xs">
                        <span className="text-gray-500">Parts: </span>
                        {order.partsUsed.map(p => p.description).join(', ')}
                      </div>
                    )}
                  </div>
                  <div className="text-right">
                    <p className="font-medium">${order.estimatedCost.toLocaleString()}</p>
                    <p className="text-xs text-gray-500">estimated</p>
                    {order.actualCost && (
                      <p className="text-xs text-green-600">${order.actualCost.toLocaleString()} actual</p>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeTab === 'costs' && costs && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Cost Summary */}
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
            <h3 className="font-semibold mb-4 flex items-center gap-2">
              <DollarSign className="w-5 h-5 text-opsgrid-primary" />
              Cost Summary
            </h3>
            <div className="space-y-3">
              <div className="flex justify-between items-center p-3 bg-opsgrid-bg rounded-lg">
                <span>Total YTD</span>
                <span className="font-bold text-xl">${costs.totalYTD.toLocaleString()}</span>
              </div>
              <div className="flex justify-between items-center p-3 bg-opsgrid-bg rounded-lg">
                <span>Monthly Average</span>
                <span className="font-bold">${costs.monthlyAverage.toLocaleString()}</span>
              </div>
              <div className="flex justify-between items-center p-3 bg-opsgrid-bg rounded-lg">
                <span>Per Vehicle</span>
                <span className="font-bold">${costs.costPerVehicle.toLocaleString()}</span>
              </div>
              <div className="flex justify-between items-center p-3 bg-yellow-50 rounded-lg">
                <span>Upcoming (Est.)</span>
                <span className="font-bold text-yellow-600">${costs.upcomingEstimated.toLocaleString()}</span>
              </div>
            </div>
          </div>

          {/* Cost by Category */}
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
            <h3 className="font-semibold mb-4">Costs by Category</h3>
            <div className="space-y-2">
              {Object.entries(costs.byCategory).map(([category, amount]) => (
                <div key={category} className="flex items-center gap-3">
                  <div className="flex-1">
                    <div className="flex justify-between text-sm mb-1">
                      <span>{category}</span>
                      <span className="font-medium">${amount.toLocaleString()}</span>
                    </div>
                    <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-opsgrid-primary rounded-full"
                        style={{ width: `${(amount / costs.totalYTD) * 100}%` }}
                      />
                    </div>
                  </div>
                  <span className="text-xs text-gray-500 w-12 text-right">
                    {((amount / costs.totalYTD) * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Monthly Trend */}
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4 lg:col-span-2">
            <h3 className="font-semibold mb-4">Monthly Cost Trend</h3>
            <div className="h-48 flex items-end gap-2">
              {costs.monthlyBreakdown.map((month) => {
                const maxCost = Math.max(...costs.monthlyBreakdown.map(m => m.cost));
                const height = maxCost > 0 ? (month.cost / maxCost) * 100 : 0;
                return (
                  <div key={month.month} className="flex-1 flex flex-col items-center gap-1">
                    <div 
                      className="w-full bg-opsgrid-primary rounded-t hover:bg-opsgrid-accent transition-all relative group"
                      style={{ height: `${height}%`, minHeight: '4px' }}
                    >
                      <div className="absolute -top-8 left-1/2 -translate-x-1/2 bg-gray-800 text-white text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 whitespace-nowrap">
                        ${month.cost.toLocaleString()}
                      </div>
                    </div>
                    <span className="text-xs text-gray-500">{month.month.split(' ')[0]}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {showCreate && (
        <CreateScheduleModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            loadData();
          }}
        />
      )}
    </div>
  );
};

// Create a new maintenance schedule, wired to maintenanceApi.createSchedule.
const CreateScheduleModal: FC<{ onClose: () => void; onCreated: () => void }> = ({ onClose, onCreated }) => {
  const [vehicleNumber, setVehicleNumber] = useState('');
  const [serviceType, setServiceType] = useState<MaintenanceSchedule['serviceType']>('oil_change');
  const [description, setDescription] = useState('');
  const [scheduledDate, setScheduledDate] = useState('');
  const [priority, setPriority] = useState<MaintenanceSchedule['priority']>('normal');
  const [currentMileage, setCurrentMileage] = useState('');
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const submit = async () => {
    if (!vehicleNumber.trim()) {
      setFormError('Vehicle number is required');
      return;
    }
    if (!scheduledDate) {
      setFormError('Scheduled date is required');
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      await maintenanceApi.createSchedule({
        vehicleNumber: vehicleNumber.trim(),
        serviceType,
        description: description.trim() || serviceType?.replace(/_/g, ' '),
        scheduledDate: new Date(scheduledDate).toISOString(),
        priority,
        currentMileage: Number(currentMileage) || 0,
      } as Partial<MaintenanceSchedule>);
      onCreated();
    } catch (e: any) {
      setFormError(e?.response?.data?.detail || 'Failed to create schedule');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" role="dialog" aria-modal="true">
      <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg max-w-md w-full p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold">Schedule Maintenance</h2>
          <button onClick={onClose} aria-label="Close" className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <div>
          <label className="block text-sm text-gray-600 mb-1">Vehicle Number</label>
          <input
            className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
            value={vehicleNumber} onChange={(e) => setVehicleNumber(e.target.value)} placeholder="TRK-104"
          />
        </div>
        <div>
          <label className="block text-sm text-gray-600 mb-1">Service Type</label>
          <select
            className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
            value={serviceType} onChange={(e) => setServiceType(e.target.value as MaintenanceSchedule['serviceType'])}
          >
            <option value="oil_change">Oil Change</option>
            <option value="tire_rotation">Tire Rotation</option>
            <option value="brake_inspection">Brake Inspection</option>
            <option value="engine_tuneup">Engine Tune-up</option>
            <option value="transmission_service">Transmission Service</option>
            <option value="annual_inspection">Annual Inspection</option>
            <option value="other">Other</option>
          </select>
        </div>
        <div>
          <label className="block text-sm text-gray-600 mb-1">Description</label>
          <input
            className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
            value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional details"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm text-gray-600 mb-1">Scheduled Date</label>
            <input
              type="date"
              className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
              value={scheduledDate} onChange={(e) => setScheduledDate(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">Priority</label>
            <select
              className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
              value={priority} onChange={(e) => setPriority(e.target.value as MaintenanceSchedule['priority'])}
            >
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </select>
          </div>
        </div>
        <div>
          <label className="block text-sm text-gray-600 mb-1">Current Mileage</label>
          <input
            type="number"
            className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
            value={currentMileage} onChange={(e) => setCurrentMileage(e.target.value)} placeholder="0"
          />
        </div>
        {formError && <p className="text-sm text-status-alarm">{formError}</p>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 border border-opsgrid-border rounded-lg text-sm">Cancel</button>
          <button
            onClick={submit}
            disabled={busy}
            className="px-4 py-2 bg-opsgrid-primary text-white rounded-lg text-sm disabled:opacity-50"
          >
            {busy ? 'Saving…' : 'Create Schedule'}
          </button>
        </div>
      </div>
    </div>
  );
};
