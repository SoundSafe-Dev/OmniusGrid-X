// Real-mode shape adapters (W3 cutover): the legacy backend routers return
// snake_case ORM dumps while the frontend types are camelCase (and a few field
// names diverge beyond casing). These helpers convert at the client seam so
// neither the API contract nor the TS types need to change.

const snakeToCamel = (s: string) => s.replace(/_([a-z0-9])/g, (_, c) => c.toUpperCase())
const camelToSnake = (s: string) => s.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`)

export function toCamel<T = any>(value: any, aliases: Record<string, string> = {}): T {
  if (Array.isArray(value)) return value.map((v) => toCamel(v, aliases)) as any
  if (value !== null && typeof value === 'object') {
    const out: Record<string, any> = {}
    for (const [k, v] of Object.entries(value)) {
      const camel = snakeToCamel(k)
      out[aliases[camel] ?? camel] = toCamel(v, aliases)
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
      out[camelToSnake(renamed)] = toSnake(v, aliases)
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
}
export const TRANSPORT_OUT_ALIASES: Record<string, string> = {
  name: 'carrierName',
  ctpatExpiry: 'ctpatExpiresAt',
  insuranceExpiry: 'insuranceExpiresAt',
  hosCycleHoursUsed: 'hosCycleHours',
  metadata: 'metaData',
}
