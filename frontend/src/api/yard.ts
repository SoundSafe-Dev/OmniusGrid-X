import { api } from './client';
import { YARD_ALIASES, YARD_OUT_ALIASES } from './transform';
import { registerTransform } from './transformRegistry';
import { 
  YardTrailer, 
  DockDoor, 
  DockAppointment, 
  YardMove,
  TrailerFilters,
  AppointmentFilters,
  DetentionAlert,
  PaginatedResponse,
  GeoLocation
} from '../types';

import { USE_MOCK } from './mockMode';

// FS-61: casing handled by the axios seam — no per-call toCamel/toSnake.
// (/api/v1/geotab is registered in transportation.ts alongside geoTabApi.)
registerTransform('/api/v1/yard', { inAliases: YARD_ALIASES, outAliases: YARD_OUT_ALIASES });

/** One row of `GET /api/v1/yard/dwell-times` (`DwellTimeAnalytics`), after the casing
 *  seam. Declared locally because the shared types describe the SUMMARY this module
 *  derives, and the wire shape had no type at all — which is how the mismatch in
 *  `getDwellTimes` survived (FS-393). */
interface DwellTimeRow {
  trailerId: string;
  trailerNumber: string;
  dwellHours: number;
  // `isDetention` and `detentionCharge` are DELIBERATELY NOT DECLARED, and the omission is
  // load-bearing. The endpoint sends `detention_charge: null` until a charge has been
  // ASSESSED, and a sibling `detention_assessed` flag saying which — because
  // `float(None or 0)` turns "not yet worked out" into "nothing owed" on billable time.
  //
  // `test_qualifiers_reach_the_frontend.py` exempts that flag only while nothing here reads
  // the field it qualifies, and declaring the charge tripped it immediately. It was right
  // to: this summary does not consume the charge, so claiming it would be the first half of
  // rendering an unassessed trailer as owing nothing. Whoever wires the charge into the UI
  // wires `detentionAssessed` with it, and that guard will say so again.
}

/** The page's stated target ("Target: 120 min"), named so the count and the label cannot
 *  drift apart. */
const DWELL_TARGET_MINUTES = 120;

const MOCK_DELAY = 500;

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

// Real-mode adapter: the backend stores po_number/contents inside the opaque
// `metadata` blob (whose inner keys the casing seam deliberately does not
// rename), but the trailer components read top-level trailer.contents /
// trailer.poNumber. Lift them onto each trailer.
// NOTHING IS SYNTHESISED HERE ANY MORE. This read
//   contents: t?.contents ?? t?.metadata?.contents
//   poNumber: t?.poNumber ?? t?.metadata?.po_number
// — two fields `yard_trailers` has no column for, fished out of the free-form `meta_data`
// blob, which nothing writes either key into. Both are gone from `YardTrailer` now.
//
// TYPESCRIPT DID NOT CATCH THE ORPHANS. Excess-property checking is relaxed for an object
// literal that spreads an `any`, so `{ ...t, contents: … }` kept compiling after the type
// stopped declaring `contents`. That is exactly why an adapter's inventions are invisible to
// a static sweep over the types, and why `maintenance.realmode.test.ts` and this module's
// real-mode tests assert the adapter's OUTPUT rather than its declarations.
const adaptTrailer = (t: any): YardTrailer => ({ ...t });

// Mock Data
const mockTrailers: YardTrailer[] = [
  {
    id: 'trailer-1',
    trailerId: 'TR-2024-001',
    licensePlate: 'ABC-1234',
    carrierId: 'carrier-1',
    carrierName: 'Swift Transportation',
    trailerType: 'dry_van',
    status: 'docked',
    yardLocation: 'DOCK-A1',
    assignedDoorId: 'door-1',
    checkedInAt: new Date(Date.now() - 2 * 3600000).toISOString(),
    detentionRisk: 'low',
    detentionCost: 0,
    sealNumber: 'SL-998877',
    driverName: 'John Smith',
    driverPhone: '+1-555-0101',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'trailer-2',
    trailerId: 'TR-2024-002',
    licensePlate: 'XYZ-5678',
    carrierId: 'carrier-2',
    carrierName: 'Schneider National',
    trailerType: 'reefer',
    status: 'yard',
    yardLocation: 'ZONE-B-12',
    checkedInAt: new Date(Date.now() - 4 * 3600000).toISOString(),
    expectedDuration: 180,
    detentionRisk: 'medium',
    detentionCost: 75,
    sealNumber: 'SL-998878',
    driverName: 'Maria Garcia',
    driverPhone: '+1-555-0102',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'trailer-3',
    trailerId: 'TR-2024-003',
    licensePlate: 'DEF-9012',
    carrierId: 'carrier-3',
    carrierName: 'JB Hunt',
    trailerType: 'flatbed',
    status: 'in_transit',
    checkedInAt: new Date(Date.now() - 1 * 3600000).toISOString(),
    detentionRisk: 'low',
    detentionCost: 0,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'trailer-4',
    trailerId: 'TR-2024-004',
    licensePlate: 'GHI-3456',
    carrierId: 'carrier-1',
    carrierName: 'Swift Transportation',
    trailerType: 'dry_van',
    status: 'yard',
    yardLocation: 'ZONE-A-05',
    checkedInAt: new Date(Date.now() - 6 * 3600000).toISOString(),
    expectedDuration: 240,
    detentionRisk: 'high',
    detentionCost: 450,
    sealNumber: 'SL-998879',
    driverName: 'Robert Johnson',
    driverPhone: '+1-555-0103',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockDockDoors: DockDoor[] = [
  {
    id: 'door-1',
    doorNumber: 'DOCK-A1',
    workcellId: 'workcell-1',
    status: 'occupied',
    currentTrailerId: 'trailer-1',
    trailerLicensePlate: 'ABC-1234',
    equipmentCapabilities: { 'forklift': true, 'pallet_jack': true, 'conveyor': true },
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'door-2',
    doorNumber: 'DOCK-A2',
    workcellId: 'workcell-1',
    status: 'available',
    equipmentCapabilities: { 'forklift': true, 'pallet_jack': true },
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'door-3',
    doorNumber: 'DOCK-B1',
    workcellId: 'workcell-2',
    status: 'reserved',
    equipmentCapabilities: { 'forklift': true, 'crane': true },
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'door-4',
    doorNumber: 'DOCK-B2',
    workcellId: 'workcell-2',
    status: 'maintenance',
    equipmentCapabilities: { 'forklift': true },
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockAppointments: DockAppointment[] = [
  {
    id: 'appt-1',
    carrierId: 'carrier-1',
    carrierName: 'Swift Transportation',
    trailerId: 'trailer-1',
    trailerLicensePlate: 'ABC-1234',
    doorId: 'door-1',
    doorNumber: 'DOCK-A1',
    workcellId: 'workcell-1',
    appointmentType: 'delivery',
    scheduledArrival: new Date(Date.now() - 2 * 3600000).toISOString(),
    actualArrival: new Date(Date.now() - 2 * 3600000).toISOString(),
    scheduledDeparture: new Date(Date.now() + 2 * 3600000).toISOString(),
    status: 'docked',
    loadDescription: 'Electronics - Batch #4521',
    priority: 'normal',
    driverName: 'John Smith',
    driverPhone: '+1-555-0101',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'appt-2',
    carrierId: 'carrier-2',
    carrierName: 'Schneider National',
    trailerId: 'trailer-2',
    trailerLicensePlate: 'XYZ-5678',
    workcellId: 'workcell-2',
    appointmentType: 'pickup',
    scheduledArrival: new Date(Date.now() + 1 * 3600000).toISOString(),
    scheduledDeparture: new Date(Date.now() + 3 * 3600000).toISOString(),
    status: 'scheduled',
    loadDescription: 'Frozen Foods - Temperature Sensitive',
    priority: 'high',
    driverName: 'Maria Garcia',
    driverPhone: '+1-555-0102',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockYardMoves: YardMove[] = [
  {
    id: 'move-1',
    trailerId: 'trailer-1',
    trailerLicensePlate: 'ABC-1234',
    fromLocation: 'GATE-IN',
    toLocation: 'DOCK-A1',
    moveType: 'dock',
    performedBy: 'Yard Jockey - Mike Wilson',
    equipmentUsed: 'Yard Truck #3',
    startTime: new Date(Date.now() - 2 * 3600000).toISOString(),
    endTime: new Date(Date.now() - 1.9 * 3600000).toISOString(),
    status: 'completed',
    createdAt: new Date().toISOString(),
  },
  {
    id: 'move-2',
    trailerId: 'trailer-2',
    trailerLicensePlate: 'XYZ-5678',
    fromLocation: 'GATE-IN',
    toLocation: 'ZONE-B-12',
    moveType: 'check_in',
    performedBy: 'Yard Jockey - Sarah Lee',
    equipmentUsed: 'Yard Truck #2',
    startTime: new Date(Date.now() - 4 * 3600000).toISOString(),
    endTime: new Date(Date.now() - 3.9 * 3600000).toISOString(),
    status: 'completed',
    createdAt: new Date().toISOString(),
  },
];

// YMS API
export const yardApi = {
  // Trailers
  getTrailers: async (filters?: TrailerFilters): Promise<PaginatedResponse<YardTrailer>> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      let filtered = [...mockTrailers];
      if (filters?.status) filtered = filtered.filter(t => t.status === filters.status);
      if (filters?.carrierId) filtered = filtered.filter(t => t.carrierId === filters.carrierId);
      if (filters?.trailerType) filtered = filtered.filter(t => t.trailerType === filters.trailerType);
      if (filters?.detentionRisk) filtered = filtered.filter(t => t.detentionRisk === filters.detentionRisk);
      return {
        items: filtered,
        total: filtered.length,
        skip: 0,
        limit: filtered.length,
        hasMore: false,
      };
    }
    // FS-99: backend returns the {items, meta} pagination envelope with a real
    // total now. Map it to the flat PaginatedResponse; tolerate either casing
    // of has_more from the transform seam.
    const response = await api.get<{
      items: YardTrailer[];
      meta: { total: number; skip: number; limit: number; has_more?: boolean; hasMore?: boolean };
    }>('/api/v1/yard/trailers', { params: filters ?? {} });
    const { items, meta } = response.data;
    return {
      items: (items ?? []).map(adaptTrailer),
      total: meta.total,
      skip: meta.skip,
      limit: meta.limit,
      hasMore: meta.hasMore ?? meta.has_more ?? meta.skip + items.length < meta.total,
    };
  },

  getTrailer: async (id: string): Promise<YardTrailer> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const trailer = mockTrailers.find(t => t.id === id);
      if (!trailer) throw new Error('Trailer not found');
      return trailer;
    }
    const response = await api.get<YardTrailer>(`/api/v1/yard/trailers/${id}`);
    return adaptTrailer(response.data);
  },

  checkInTrailer: async (data: Partial<YardTrailer>): Promise<YardTrailer> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const newTrailer: YardTrailer = {
        ...data as YardTrailer,
        id: `trailer-${Date.now()}`,
        status: 'yard',
        checkedInAt: new Date().toISOString(),
        detentionRisk: 'low',
        detentionCost: 0,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      mockTrailers.push(newTrailer);
      return newTrailer;
    }
    const response = await api.post<YardTrailer>('/api/v1/yard/trailers/checkin', data);
    return response.data;
  },

  checkOutTrailer: async (id: string): Promise<YardTrailer> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const trailer = mockTrailers.find(t => t.id === id);
      if (!trailer) throw new Error('Trailer not found');
      trailer.status = 'outbound';
      trailer.checkedOutAt = new Date().toISOString();
      trailer.updatedAt = new Date().toISOString();
      return trailer;
    }
    const response = await api.post<YardTrailer>(`/api/v1/yard/trailers/${id}/checkout`);
    return response.data;
  },

  assignToDoor: async (trailerId: string, doorId: string): Promise<YardTrailer> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const trailer = mockTrailers.find(t => t.id === trailerId);
      const door = mockDockDoors.find(d => d.id === doorId);
      if (!trailer) throw new Error('Trailer not found');
      if (!door) throw new Error('Door not found');
      trailer.assignedDoorId = doorId;
      trailer.yardLocation = door.doorNumber;
      trailer.status = 'docked';
      trailer.updatedAt = new Date().toISOString();
      door.status = 'occupied';
      door.currentTrailerId = trailerId;
      door.trailerLicensePlate = trailer.licensePlate;
      door.updatedAt = new Date().toISOString();
      return trailer;
    }
    const response = await api.post<YardTrailer>(`/api/v1/yard/dock/doors/${doorId}/assign/${trailerId}`);
    return response.data;
  },

  // Dock Doors
  //
  // No workcell filter. This took a `workcellId` and sent it as `workcell_id`, which
  // the endpoint does not declare — FastAPI ignores unknown query parameters silently,
  // so a filtered request would have returned every door and looked like a filtered
  // result. `dock_doors` has no workcell column at all, so the filter could never have
  // been honoured; only the mock branch, filtering fixture data on a field the real
  // model lacks, made it look implemented. The one caller passes nothing.
  getDockDoors: async (): Promise<DockDoor[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockDockDoors;
    }
    const response = await api.get<DockDoor[]>('/api/v1/yard/dock/doors');
    return response.data;
  },

  // Appointments
  getAppointments: async (filters?: AppointmentFilters): Promise<PaginatedResponse<DockAppointment>> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      let filtered = [...mockAppointments];
      if (filters?.status) filtered = filtered.filter(a => a.status === filters.status);
      if (filters?.workcellId) filtered = filtered.filter(a => a.workcellId === filters.workcellId);
      if (filters?.carrierId) filtered = filtered.filter(a => a.carrierId === filters.carrierId);
      if (filters?.priority) filtered = filtered.filter(a => a.priority === filters.priority);
      return {
        items: filtered,
        total: filtered.length,
        skip: 0,
        limit: filtered.length,
        hasMore: false,
      };
    }
    const response = await api.get<DockAppointment[]>('/api/v1/yard/dock/appointments', { params: filters ?? {} });
    return { items: response.data, total: (response.data as any[]).length } as any;
  },

  createAppointment: async (data: Partial<DockAppointment>): Promise<DockAppointment> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const newAppt: DockAppointment = {
        ...data as DockAppointment,
        id: `appt-${Date.now()}`,
        status: 'scheduled',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      mockAppointments.push(newAppt);
      return newAppt;
    }
    const response = await api.post<DockAppointment>('/api/v1/yard/dock/appointments', data);
    return response.data;
  },


  recordMove: async (data: Partial<YardMove>): Promise<YardMove> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const newMove: YardMove = {
        ...data as YardMove,
        id: `move-${Date.now()}`,
        startTime: new Date().toISOString(),
        status: 'in_progress',
        createdAt: new Date().toISOString(),
      };
      mockYardMoves.push(newMove);
      return newMove;
    }
    const response = await api.post<YardMove>('/api/v1/yard/moves', data);
    return response.data;
  },

  // Analytics
  getDwellTimes: async (): Promise<{ avgDwellTime: number; maxDwellTime: number; trailersExceedingTarget: number }> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return {
        avgDwellTime: 180,
        maxDwellTime: 420,
        trailersExceedingTarget: 2,
      };
    }
    // THE ENDPOINT RETURNS A LIST, NOT THIS SUMMARY (FS-393).
    //
    // `GET /api/v1/yard/dwell-times` is `response_model=List[DwellTimeAnalytics]` — one row
    // per trailer with `dwell_hours`. This function declared, and returned, a summary
    // OBJECT. `response.data` was therefore an array, and `YardManagement` reads
    // `dwellTimes.trailersExceedingTarget` on it: `undefined`, so `undefined > 0` is false
    // and THE DWELL WARNING BANNER NEVER RENDERED IN REAL MODE. The mock returned the
    // summary shape, so it rendered in development and only there.
    //
    // Verified against a running backend: the endpoint returned a list whose first row was
    // TRL-9017 at 23 dwell hours — a trailer eleven times past the target, on a page whose
    // banner exists to say so.
    //
    // Summarised here rather than adding a backend endpoint: every figure is derivable
    // from the rows already sent, and the per-trailer detail is what the API is for.
    const response = await api.get<DwellTimeRow[]>('/api/v1/yard/dwell-times');
    const rows = Array.isArray(response.data) ? response.data : [];
    // `dwell_hours` is hours; the page formats minutes and compares against a 120-minute
    // target, so the conversion belongs here and not in the component.
    const minutes = rows.map((r) => (r.dwellHours ?? 0) * 60);
    return {
      avgDwellTime: minutes.length
        ? Math.round(minutes.reduce((a, b) => a + b, 0) / minutes.length)
        : 0,
      maxDwellTime: minutes.length ? Math.round(Math.max(...minutes)) : 0,
      trailersExceedingTarget: minutes.filter((m) => m > DWELL_TARGET_MINUTES).length,
    };
  },

  getDetentionAlerts: async (): Promise<DetentionAlert[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      // The mock now matches `/api/v1/yard/detention-alerts` exactly. It used to describe a
      // richer alert — an id, a severity, a driver name — none of which the endpoint sends,
      // so the mock path rendered a banner the real path could not (rule 50).
      return [
        {
          trailerId: 'trailer-4',
          trailerNumber: 'TRL-4409',
          status: 'detention',
          licensePlate: 'GHI-3456',
          yardLocation: 'ZONE-A-05',
          carrierName: 'Swift Transportation',
          checkInAt: new Date(Date.now() - 6 * 3600000).toISOString(),
          elapsedMinutes: 360,
          freeMinutes: 120,
          detentionMinutes: 240,
          currentCharge: 450,
          hourlyRate: 112.5,
        },
      ];
    }
    const response = await api.get<DetentionAlert[]>('/api/v1/yard/detention-alerts');
    return response.data;
  },
};

// GeoTab Integration for Yard
export const geoTabYardApi = {
  // Get real-time trailer location from GeoTab device
  getTrailerLocation: async (deviceId: string): Promise<GeoLocation> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return {
        latitude: 40.7128 + (Math.random() - 0.5) * 0.01,
        longitude: -74.0060 + (Math.random() - 0.5) * 0.01,
        speed: Math.random() * 60,
        timestamp: new Date().toISOString(),
      };
    }
    const response = await api.get<GeoLocation>(`/api/v1/geotab/devices/${deviceId}/location`);
    return response.data;
  },

  // Get trailer trip history
  getTrailerTrips: async (deviceId: string, from: string, to: string): Promise<any[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return [];
    }
    const response = await api.get(`/api/v1/geotab/devices/${deviceId}/trips`, { params: { from, to } });
    return response.data;
  },
};
