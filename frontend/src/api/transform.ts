// Real-mode shape adapters (W3 cutover): the legacy backend routers return
// snake_case ORM dumps while the frontend types are camelCase (and a few field
// names diverge beyond casing). These helpers convert at the client seam so
// neither the API contract nor the TS types need to change.

const snakeToCamel = (s: string) => s.replace(/_([a-z0-9])/g, (_, c) => c.toUpperCase())
const camelToSnake = (s: string) => s.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`)

// Free-form JSON blobs whose inner keys are DATA, not field names. Their keys
// must not be case-converted (e.g. a collector config {"mqtt_broker_2": ...} or
// telemetry metadata) — case conversion is lossy and would break round-trips.
// The key itself is still renamed; only its value is passed through untouched.
const OPAQUE_KEYS = new Set([
  // every spelling a wire or client can produce — a missing variant means
  // toCamel/toSnake recurse INTO the blob and corrupt its data keys
  'metadata', 'meta_data', 'metaData',
  'featureVector', 'feature_vector',  // ML feature names are data, not fields
  'connectionConfig', 'connection_config',
  'mediaConfig', 'media_config',
  'settings', 'details', 'payload',
  'contactInfo', 'contact_info',
  'contractRate', 'contract_rate',
  // FS-405/406: counts and descriptions KEYED BY POSTING STATUS — 'manual_required',
  // 'not_applicable'. Camel-casing those keys turns them into 'manualRequired', which no
  // status lookup matches, so the shop-floor and activation panels would silently render
  // the raw key instead of the label. The values are counts and sentences, not fields.
  'byStatus', 'by_status',
  'postingStatuses', 'posting_statuses',
  // Which target systems each event type / correlation domain reaches. Keyed by event type
  // ('part_issue', 'labor_entry') and by domain ('QUALITY_CONTROL'); both are data.
  'routing',
])

export function toCamel<T = any>(value: any, aliases: Record<string, string> = {}): T {
  if (Array.isArray(value)) return value.map((v) => toCamel(v, aliases)) as any
  if (value !== null && typeof value === 'object') {
    const out: Record<string, any> = {}
    for (const [k, v] of Object.entries(value)) {
      const camel = snakeToCamel(k)
      const name = aliases[camel] ?? camel
      out[name] = OPAQUE_KEYS.has(k) ? v : toCamel(v, aliases)
    }
    return out as T
  }
  return value
}

export function toSnake<T = any>(value: any, aliases: Record<string, string> = {}): T {
  if (Array.isArray(value)) return value.map((v) => toSnake(v, aliases)) as any
  if (value !== null && typeof value === 'object') {
    const out: Record<string, any> = {}
    for (const [k, v] of Object.entries(value)) {
      const renamed = aliases[k] ?? k
      out[camelToSnake(renamed)] = OPAQUE_KEYS.has(k) ? v : toSnake(v, aliases)
    }
    return out as T
  }
  return value
}

// Field-name divergences beyond casing (camelized backend name -> TS type name).
export const YARD_ALIASES: Record<string, string> = {
  trailerNumber: 'trailerId',
  checkInAt: 'checkedInAt',
  checkOutAt: 'checkedOutAt',
  dockDoorId: 'assignedDoorId',
  metaData: 'metadata',
  // DockAppointment: backend scheduled_start/_end -> TS scheduledArrival/Departure
  scheduledStart: 'scheduledArrival',
  scheduledEnd: 'scheduledDeparture',
}
// Outbound (TS name -> camel backend name) for write payloads.
export const YARD_OUT_ALIASES: Record<string, string> = {
  trailerId: 'trailerNumber',
  checkedInAt: 'checkInAt',
  checkedOutAt: 'checkOutAt',
  assignedDoorId: 'dockDoorId',
  metadata: 'metaData',
}

export const TRANSPORT_ALIASES: Record<string, string> = {
  carrierName: 'name',            // CarrierResponse.carrier_name -> Carrier.name
  ctpatExpiresAt: 'ctpatExpiry',
  insuranceExpiresAt: 'insuranceExpiry',
  hosCycleHours: 'hosCycleHoursUsed',
  metaData: 'metadata',
  // Driver: backend hazmat_endorsed -> TS hazmatCertified
  hazmatEndorsed: 'hazmatCertified',
  // Shipment: backend total_weight_lbs/total_pieces -> TS weight/pieces
  totalWeightLbs: 'weight',
  totalPieces: 'pieces',
}
export const TRANSPORT_OUT_ALIASES: Record<string, string> = {
  name: 'carrierName',
  ctpatExpiry: 'ctpatExpiresAt',
  insuranceExpiry: 'insuranceExpiresAt',
  hosCycleHoursUsed: 'hosCycleHours',
  metadata: 'metaData',
}
