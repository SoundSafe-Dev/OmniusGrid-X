import { FC, useState, useEffect } from 'react';
import { ErrorState } from '../ui';
import { MapContainer, TileLayer, Circle } from 'react-leaflet';
import { 
  AlertTriangle, Plus, Trash2, Edit2, Bell, Volume2, 
  MapPin, CheckCircle, XCircle, Clock, X
} from 'lucide-react';
import { geofencingApi } from '../../api';
import { SkeletonCard } from '../ui/Skeleton';
import { useDialog } from '../ui';
import type { GeofenceZoneExtended, GeofenceAlertExtended, GeoLocation } from '../../types';
import 'leaflet/dist/leaflet.css';

// A leaflet <Circle> needs a center and a radius. center/radius are optional on
// a zone (polygon zones and malformed data have neither), so rendering every
// active zone as a Circle via `zone.center!.latitude` threw on the first
// centerless zone — and with only the app-root ErrorBoundary, that blanked the
// entire app. This narrows to the zones that can actually be drawn as circles,
// so the map skips the others instead of crashing.
export type CircleZone = GeofenceZoneExtended & { center: GeoLocation; radius: number };

export function circleRenderableZones(zones: GeofenceZoneExtended[]): CircleZone[] {
  return zones.filter(
    (z): z is CircleZone =>
      Boolean(z.isActive) &&
      z.center != null &&
      typeof z.center.latitude === 'number' &&
      typeof z.center.longitude === 'number' &&
      typeof z.radius === 'number'
  );
}

const getZoneColor = (color: string) => {
  switch (color) {
    case 'green': return '#22c55e';
    case 'yellow': return '#eab308';
    case 'red': return '#ef4444';
    default: return '#6b7280';
  }
};

// An UNREPORTED severity is not an informational one. The adapter used to default it to
// 'info', so an alert whose severity did not arrive was painted the same calm blue as a
// routine notice; grey says "no severity" without claiming one.
const getSeverityColor = (severity?: string | null) => {
  switch (severity) {
    case 'critical': return 'text-red-600 bg-red-50';
    case 'warning': return 'text-yellow-600 bg-yellow-50';
    case 'info': return 'text-blue-600 bg-blue-50';
    default: return 'text-gray-500 bg-gray-100';
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
  const { confirm } = useDialog();
  const [zones, setZones] = useState<GeofenceZoneExtended[]>([]);
  const [alerts, setAlerts] = useState<GeofenceAlertExtended[]>([]);
  const [selectedZone, setSelectedZone] = useState<GeofenceZoneExtended | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [showAlertPanel, setShowAlertPanel] = useState(true);
  const [showZoneForm, setShowZoneForm] = useState(false);
  const [editingZone, setEditingZone] = useState<GeofenceZoneExtended | null>(null);

  useEffect(() => {
    loadData();
    const unsubscribe = geofencingApi.subscribeToAlerts(
      (alert) => {
        setAlerts(prev => [alert, ...prev]);
        if (soundEnabled && alert.severity === 'critical') {
          playAlertSound();
        }
        onAlert?.(alert);
      },
      (error) => setAlertPollStalled(Boolean(error)),
    );
    return unsubscribe;
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing; adding deps changes retrigger behavior (FS-54)
  }, [soundEnabled]);

  // True when the server had more alerts than it returned. See loadData.
  const [alertsTruncated, setAlertsTruncated] = useState(false);
  // True when the alert poll is failing (FS-487). Distinct from every other state here
  // because the display of "no alerts" is an EMPTY LIST, and a poll that has stopped
  // produces exactly that — silence is the normal case and also the broken one.
  const [alertPollStalled, setAlertPollStalled] = useState(false);

  const loadData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [zonesData, alertsData] = await Promise.all([
        geofencingApi.getZones(),
        geofencingApi.getAlerts(),
      ]);
      setZones(zonesData);
      setAlerts(alertsData.items);
      // FS-428: the server caps this list and says so in a header. Carried into state so
      // the panel can say it too — a truncation flag that arrives and is dropped is the
      // same defect as one that was never sent.
      setAlertsTruncated(alertsData.truncated);
    } catch (err) {
      console.error('Failed to load geofencing data:', err);
      setError('Failed to load geofence zones and alerts. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleAcknowledge = async (alertId: string) => {
    await geofencingApi.acknowledgeAlert(alertId);
    setAlerts(prev => prev.map(a => a.id === alertId ? { ...a, acknowledged: true } : a));
  };

  const handleDeleteZone = async (zone: GeofenceZoneExtended) => {
    const ok = await confirm({
      title: 'Delete geofence zone',
      message: `Delete geofence zone "${zone.name}"? This cannot be undone.`,
      confirmLabel: 'Delete',
      destructive: true,
    });
    if (!ok) return;
    try {
      await geofencingApi.deleteZone(zone.id);
      setZones(prev => prev.filter(z => z.id !== zone.id));
      if (selectedZone?.id === zone.id) setSelectedZone(null);
    } catch (err) {
      console.error('Failed to delete zone:', err);
      setError('Failed to delete zone. Please try again.');
    }
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

      {/* Error banner */}
      {error && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <ErrorState
            message={error}
            onRetry={() => loadData()}
            retrying={isLoading}
          />
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
              {circleRenderableZones(zones).map(zone => (
                <Circle
                  key={zone.id}
                  center={[zone.center.latitude, zone.center.longitude]}
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
              <button
                onClick={() => { setEditingZone(null); setShowZoneForm(true); }}
                className="p-2 bg-opsgrid-primary text-white rounded hover:bg-opsgrid-accent"
                title="Add geofence zone"
              >
                <Plus className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Zone List */}
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg">
            <div className="max-h-[200px] overflow-y-auto">
              {/* `error` GATES THE EMPTY STATE, not just the banner above. The panel
                  rendered its failure message AND then "No geofence zones. Use + to create
                  one." below it — two statements about the same fetch, one of which invites
                  the operator to create a zone that may already exist. The banner explains
                  what happened; this stops the list contradicting it. */}
              {isLoading ? (
                <SkeletonCard lines={3} />
              ) : error ? (
                <p className="p-4 text-sm text-gray-500 text-center">Zones unavailable.</p>
              ) : zones.length === 0 ? (
                <p className="p-4 text-sm text-gray-500 text-center">No geofence zones. Use + to create one.</p>
              ) : zones.map(zone => (
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
                  {/* WAS an unconditional "{n} vehicles inside". `_zone_out` does not send
                      `vehiclesInside` and nothing computes it, so the adapter defaulted it to
                      `[]` and every zone reported "0 vehicles inside" — a count, which reads
                      as a measurement, not as a blank. */}
                  {zone.vehiclesInside && (
                    <p className="text-xs text-gray-500 mt-1">
                      {zone.vehiclesInside.length} vehicles inside
                    </p>
                  )}
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
                  <button
                    onClick={() => { setEditingZone(selectedZone); setShowZoneForm(true); }}
                    className="p-1 text-gray-600 hover:text-opsgrid-primary"
                    title="Edit zone"
                  >
                    <Edit2 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handleDeleteZone(selectedZone)}
                    className="p-1 text-gray-600 hover:text-red-600"
                    title="Delete zone"
                  >
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
                {/* NOT `radius!` (FS-556). This file's own header records that
                    `zone.center!.latitude` threw on the first centerless zone and, with only
                    the app-root ErrorBoundary, BLANKED THE ENTIRE APP. `radius` is optional
                    for exactly the same reason — a polygon zone has neither — and
                    `(undefined / 1000).toFixed(1)` is the same TypeError twenty lines below
                    the comment describing it.

                    A polygon zone has no radius to show, so the row is omitted rather than
                    rendered as NaN. */}
                {selectedZone.radius != null && (
                  <p>Radius: {(selectedZone.radius / 1000).toFixed(1)} km</p>
                )}
                <p>Alert on Entry: {selectedZone.alertRules.onEntry ? 'Yes' : 'No'}</p>
                <p>Alert on Exit: {selectedZone.alertRules.onExit ? 'Yes' : 'No'}</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Reopen control for the alert history panel */}
      {!showAlertPanel && (
        <button
          onClick={() => setShowAlertPanel(true)}
          className="flex items-center gap-2 text-sm bg-opsgrid-panel border border-opsgrid-border rounded-lg px-3 py-2 hover:bg-opsgrid-bg"
        >
          <Bell className="w-4 h-4 text-opsgrid-primary" />
          Show Alert History
          {unacknowledgedAlerts.length > 0 && (
            <span className="bg-red-500 text-white text-xs px-2 py-0.5 rounded-full">
              {unacknowledgedAlerts.length}
            </span>
          )}
        </button>
      )}

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
            <button onClick={() => setShowAlertPanel(false)} title="Hide alert history">
              <XCircle className="w-5 h-5 text-gray-400" />
            </button>
          </div>
          <div className="max-h-[250px] overflow-y-auto">
            {!isLoading && error && (
              <p className="p-4 text-sm text-gray-500 text-center">Alerts unavailable.</p>
            )}
            {!isLoading && !error && alerts.length === 0 && (
              <p className="p-4 text-sm text-gray-500 text-center">No geofence alerts.</p>
            )}
            {alertPollStalled && (
              <p className="border-b border-status-alarm/50 bg-status-alarm/10 p-3 text-xs text-opsgrid-text" role="alert">
                Alert checks are failing — new geofence alerts will not appear here. An empty
                list right now means nobody knows, not that nothing has happened.
              </p>
            )}
            {alertsTruncated && (
              <p className="border-b border-status-warning/50 bg-status-warning/10 p-3 text-xs text-opsgrid-text" role="status">
                Showing the most recent {alerts.length} alerts — there are more. Anything
                older than these is not on this list, including unacknowledged ones.
              </p>
            )}
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
                  {/* THE FALSY BRANCH ASSERTED A VIOLATION. The API sent `eventType`, not
                      `alertType`, so this matched neither 'entry' nor 'exit' and every
                      alert — every routine entry into an authorised zone — rendered as
                      "Violation". The field name is fixed server-side; this now also
                      refuses to guess when the value is one it does not recognise, because
                      the next unmapped event type would land in exactly the same place. */}
                  <p className="text-sm font-medium">
                    {alert.vehicleNumber ?? 'Unknown vehicle'} —{' '}
                    {alert.alertType === 'entry'
                      ? 'Entered'
                      : alert.alertType === 'exit'
                        ? 'Exited'
                        : alert.alertType === 'violation'
                          ? 'Violation'
                          : `Event: ${alert.alertType ?? 'unreported'}`}
                  </p>
                  {/* A zone the server could not resolve is not an unnamed zone. */}
                  <p className="text-xs text-gray-600">
                    {alert.geofenceName ?? 'Zone name unavailable'}
                  </p>
                  <p className="text-xs text-gray-500 flex items-center gap-1 mt-1">
                    <Clock className="w-3 h-3" />
                    {alert.timestamp
                      ? new Date(alert.timestamp).toLocaleString()
                      : 'time unreported'}
                  </p>
                </div>
                {!alert.acknowledged ? (
                  <button
                    aria-label={`Acknowledge geofence alert for ${alert.geofenceName ?? 'zone'}`}
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

      {showZoneForm && (
        <ZoneFormModal
          zone={editingZone}
          onClose={() => { setShowZoneForm(false); setEditingZone(null); }}
          onSaved={(saved) => {
            setShowZoneForm(false);
            setEditingZone(null);
            if (selectedZone && saved.id === selectedZone.id) setSelectedZone(saved);
            loadData();
          }}
        />
      )}
    </div>
  );
};

// Create or edit a geofence zone, wired to geofencingApi.createZone / updateZone.
const ZoneFormModal: FC<{
  zone: GeofenceZoneExtended | null;
  onClose: () => void;
  onSaved: (zone: GeofenceZoneExtended) => void;
}> = ({ zone, onClose, onSaved }) => {
  const isEdit = zone !== null;
  const [name, setName] = useState(zone?.name ?? '');
  const [description, setDescription] = useState(zone?.description ?? '');
  const [color, setColor] = useState<GeofenceZoneExtended['color']>(zone?.color ?? 'green');
  const [latitude, setLatitude] = useState(zone?.center?.latitude?.toString() ?? '');
  const [longitude, setLongitude] = useState(zone?.center?.longitude?.toString() ?? '');
  const [radiusKm, setRadiusKm] = useState(zone ? ((zone.radius ?? 0) / 1000).toString() : '');
  const [onEntry, setOnEntry] = useState(zone?.alertRules?.onEntry ?? true);
  const [onExit, setOnExit] = useState(zone?.alertRules?.onExit ?? false);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const submit = async () => {
    if (!name.trim()) {
      setFormError('Zone name is required');
      return;
    }
    const lat = Number(latitude);
    const lng = Number(longitude);
    const radiusMeters = Number(radiusKm) * 1000;
    if (Number.isNaN(lat) || Number.isNaN(lng) || !radiusMeters) {
      setFormError('Valid latitude, longitude, and radius are required');
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      const payload: Partial<GeofenceZoneExtended> = {
        name: name.trim(),
        description: description.trim(),
        type: 'circle',
        color,
        center: { latitude: lat, longitude: lng, timestamp: new Date().toISOString() },
        radius: radiusMeters,
        alertRules: {
          onEntry,
          onExit,
          notifyRoles: zone?.alertRules?.notifyRoles ?? [],
        },
      };
      const saved = isEdit
        ? await geofencingApi.updateZone(zone!.id, payload)
        : await geofencingApi.createZone(payload);
      onSaved(saved);
    } catch (e: any) {
      setFormError(e?.response?.data?.detail || 'Failed to save zone');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[1000] p-4" role="dialog" aria-modal="true">
      <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg max-w-md w-full p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold">{isEdit ? 'Edit Geofence Zone' : 'Create Geofence Zone'}</h2>
          <button onClick={onClose} aria-label="Close" className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div>
          <label htmlFor="geofencingpanel-name" className="block text-sm text-gray-600 mb-1">Name</label>
          <input
              id="geofencingpanel-name"
            className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
            value={name} onChange={(e) => setName(e.target.value)} placeholder="Downtown Depot"
          />
        </div>
        <div>
          <label htmlFor="geofencingpanel-description" className="block text-sm text-gray-600 mb-1">Description</label>
          <input
              id="geofencingpanel-description"
            className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
            value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional details"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="geofencingpanel-latitude" className="block text-sm text-gray-600 mb-1">Latitude</label>
            <input
              id="geofencingpanel-latitude"
              type="number"
              className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
              value={latitude} onChange={(e) => setLatitude(e.target.value)} placeholder="39.8283"
            />
          </div>
          <div>
            <label htmlFor="geofencingpanel-longitude" className="block text-sm text-gray-600 mb-1">Longitude</label>
            <input
              id="geofencingpanel-longitude"
              type="number"
              className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
              value={longitude} onChange={(e) => setLongitude(e.target.value)} placeholder="-98.5795"
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="geofencingpanel-radius-km" className="block text-sm text-gray-600 mb-1">Radius (km)</label>
            <input
              id="geofencingpanel-radius-km"
              type="number"
              className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
              value={radiusKm} onChange={(e) => setRadiusKm(e.target.value)} placeholder="5"
            />
          </div>
          <div>
            <label htmlFor="geofencingpanel-color" className="block text-sm text-gray-600 mb-1">Color</label>
            <select
              id="geofencingpanel-color"
              className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-sm focus:outline-none"
              value={color} onChange={(e) => setColor(e.target.value as GeofenceZoneExtended['color'])}
            >
              <option value="green">Green</option>
              <option value="yellow">Yellow</option>
              <option value="red">Red</option>
            </select>
          </div>
        </div>
        <div className="flex gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={onEntry} onChange={(e) => setOnEntry(e.target.checked)} />
            Alert on Entry
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={onExit} onChange={(e) => setOnExit(e.target.checked)} />
            Alert on Exit
          </label>
        </div>
        {formError && <p className="text-sm text-status-alarm">{formError}</p>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 border border-opsgrid-border rounded-lg text-sm">Cancel</button>
          <button
            onClick={submit}
            disabled={busy}
            className="px-4 py-2 bg-opsgrid-primary text-white rounded-lg text-sm disabled:opacity-50"
          >
            {busy ? 'Saving…' : isEdit ? 'Save Changes' : 'Create Zone'}
          </button>
        </div>
      </div>
    </div>
  );
};
