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

// A share of a total that may be zero or absent. `amount / 0` is Infinity, which becomes
// an `Infinity%` CSS width, and `NaN.toFixed(1)` renders the literal string "NaN".
const share = (amount: number, total?: number): number =>
  total && total > 0 ? (amount / total) * 100 : 0;

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// The server sends `YYYY-MM`. This was `month.month.split(' ')[0]`, which suited the mock's
// "Jan 2024" and rendered the real value as the literal "2026-01" — a label nobody writes on
// an axis. Anything that is not `YYYY-MM` is passed through rather than mangled.
const monthLabel = (month: string): string => {
  const match = /^\d{4}-(\d{2})$/.exec(month);
  if (!match) return month.split(' ')[0];
  return MONTH_NAMES[Number(match[1]) - 1] ?? month;
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
          {/* `|| 0` turned a missing YTD figure into "$0" — a fleet that has spent
              nothing on maintenance all year, which is a claim, not a blank. */}
          <p className="text-2xl font-bold text-green-600">
            {costs?.ytdTotal != null ? `$${costs.ytdTotal.toLocaleString()}` : '—'}
          </p>
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
                        {/* WAS `Mileage: {item.currentMileage}`, which the adapter filled
                            from `dueMileage` — the odometer at which service falls DUE —
                            or from 0. A technician reads "Mileage: 128,500" as where the
                            vehicle is now. The two differ by exactly the distance left
                            before the service, which is the number that matters here.
                            Omitted entirely when the schedule carries no due odometer,
                            because 0 miles is a reading and absence is not. */}
                        {item.dueMileage != null && (
                          <span>Due at {item.dueMileage.toLocaleString()} mi</span>
                        )}

                      </div>
                    </div>
                    <div className="text-right">
                      {/* `item.estimatedCost &&` — a FALSY check on a number, so a service
                          quoted at exactly nothing rendered no figure at all, exactly as if
                          nobody had quoted it. A zero estimate is a quote. */}
                      {item.estimatedCost != null && (
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
                      {/* Headed by the repair's own summary. It used to be
                          `workOrderNumber` — the first eight characters of the row's UUID, an
                          identifier no system issued, printed as the heading a technician
                          would quote to a vendor. */}
                      <span className="font-semibold">{order.title}</span>
                      <span className={`px-2 py-0.5 rounded text-xs ${getStatusColor(order.status)}`}>
                        {order.status?.replace(/_/g, ' ')}
                      </span>
                      <span className={`text-xs ${getPriorityColor(order.priority)}`}>
                        {order.priority}
                      </span>
                    </div>
                    {order.description && (
                      <p className="text-sm text-gray-600 mt-1">{order.description}</p>
                    )}
                    <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
                      <span className="flex items-center gap-1">
                        <Truck className="w-3 h-3" />
                        {order.vehicleNumber}
                      </span>
                      {order.openedAt && (
                        <span className="flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          Reported: {new Date(order.openedAt).toLocaleDateString()}
                        </span>
                      )}
                      {/* WAS "Tech: {assignedTechnician}" — a column that does not exist, so
                          the line never rendered, while `vendor` (who actually did the work)
                          arrived on every response and was shown nowhere. */}
                      {order.vendor && <span>Vendor: {order.vendor}</span>}
                      {order.category && <span>{order.category}</span>}
                    </div>
                  </div>
                  <div className="text-right">
                    {/* WAS `${order.estimatedCost}` with the caption "estimated". It was
                        fed from `repair_orders.cost` — what the repair COST — and a null
                        one was coerced to 0, so a repair with nothing recorded against it
                        displayed as "$0 estimated": a free repair, and an estimate that
                        nobody made. Omitted when there is no figure. */}
                    {order.cost != null && (
                      <>
                        <p className="font-medium">${order.cost.toLocaleString()}</p>
                        <p className="text-xs text-gray-500">cost</p>
                      </>
                    )}
                    {/* `actualCost` was a second cost line on a table with ONE cost column.
                        It never rendered, and had it ever been populated the card would have
                        shown the same number twice under two labels. */}
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
              {/* Only the figures the server actually sent. "Per Vehicle $0" and
                  "Upcoming (Est.) $0" were hardcoded zeros, and the second sat in a
                  highlighted box where it read as "nothing is coming up" rather than
                  "nobody calculated this". A row that is absent prompts a question; a row
                  reading $0 answers one. */}
              {costs.ytdTotal != null && (
                <div className="flex justify-between items-center p-3 bg-opsgrid-bg rounded-lg">
                  <span>Total YTD</span>
                  <span className="font-bold text-xl">${costs.ytdTotal.toLocaleString()}</span>
                </div>
              )}
              {costs.monthlyAverage != null && (
                <div className="flex justify-between items-center p-3 bg-opsgrid-bg rounded-lg">
                  <span>Monthly Average</span>
                  <span className="font-bold">${costs.monthlyAverage.toLocaleString()}</span>
                </div>
              )}
              {costs.costPerVehicle != null && (
                <div className="flex justify-between items-center p-3 bg-opsgrid-bg rounded-lg">
                  <span>Per Vehicle</span>
                  <span className="font-bold">${costs.costPerVehicle.toLocaleString()}</span>
                </div>
              )}
              {costs.upcomingEstimated != null && (
                <div className="flex justify-between items-center p-3 bg-yellow-50 rounded-lg">
                  <span>Upcoming (Est.)</span>
                  <span className="font-bold text-yellow-600">${costs.upcomingEstimated.toLocaleString()}</span>
                </div>
              )}
              {costs.monthlyAverage == null && costs.costPerVehicle == null && (
                <p className="text-xs text-opsgrid-text-secondary px-3">
                  Monthly average, per-vehicle and upcoming figures are not reported by
                  this deployment.
                </p>
              )}
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
                        style={{ width: `${share(amount, costs.ytdTotal)}%` }}
                      />
                    </div>
                  </div>
                  {/* `amount / 0` is Infinity and `NaN.toFixed(1)` prints the string
                      "NaN" — both were reachable whenever the YTD total was zero or
                      absent, which is exactly when a category breakdown is least
                      meaningful. */}
                  <span className="text-xs text-gray-500 w-12 text-right">
                    {costs.ytdTotal ? `${share(amount, costs.ytdTotal).toFixed(1)}%` : '—'}
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
                    <span className="text-xs text-gray-500">{monthLabel(month.month)}</span>
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
  // WAS `currentMileage`, collected under a "Current Mileage" label and sent as a
  // field `maintenance_schedules` does not have — so the handler dropped it in silence
  // and the panel then displayed the DUE mileage back, which looked like it had saved.
  // A schedule holds the odometer at which service falls due; that is what this asks for
  // now, and it is stored.
  const [dueMileage, setDueMileage] = useState('');
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
        // Both names, from one input. `_schedule_out` emits vehicleId and vehicleNumber
        // from the same column, and create used to demand `vehicleId` specifically — so
        // this form, which only ever knew the number it was shown, failed every time
        // with "vehicleId is required". The backend accepts either now; sending both
        // means neither end has to guess.
        vehicleId: vehicleNumber.trim(),
        vehicleNumber: vehicleNumber.trim(),
        serviceType,
        description: description.trim() || serviceType?.replace(/_/g, ' '),
        scheduledDate: new Date(scheduledDate).toISOString(),
        priority,
        // Only when given. `Number('') || 0` sent a real zero for a blank field, which
        // the schema would now store as "service is due at zero miles".
        ...(dueMileage.trim() ? { dueMileage: Number(dueMileage) } : {}),
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
          <label htmlFor="maintenancepanel-vehicle-number" className="block text-sm text-gray-600 mb-1">Vehicle Number</label>
          <input
              id="maintenancepanel-vehicle-number"
            className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
            value={vehicleNumber} onChange={(e) => setVehicleNumber(e.target.value)} placeholder="TRK-104"
          />
        </div>
        <div>
          <label htmlFor="maintenancepanel-service-type" className="block text-sm text-gray-600 mb-1">Service Type</label>
          <select
              id="maintenancepanel-service-type"
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
          <label htmlFor="maintenancepanel-description" className="block text-sm text-gray-600 mb-1">Description</label>
          <input
              id="maintenancepanel-description"
            className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
            value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional details"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="maintenancepanel-scheduled-date" className="block text-sm text-gray-600 mb-1">Scheduled Date</label>
            <input
              id="maintenancepanel-scheduled-date"
              type="date"
              className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
              value={scheduledDate} onChange={(e) => setScheduledDate(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="maintenancepanel-priority" className="block text-sm text-gray-600 mb-1">Priority</label>
            <select
              id="maintenancepanel-priority"
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
          <label htmlFor="due-mileage" className="block text-sm text-gray-600 mb-1">
            Due at mileage
          </label>
          <input
            id="due-mileage"
            type="number"
            className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
            value={dueMileage} onChange={(e) => setDueMileage(e.target.value)} placeholder="Optional"
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
