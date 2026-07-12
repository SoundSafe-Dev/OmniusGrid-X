import { describe, it, expect } from 'vitest'
import { toCamel, toSnake, YARD_ALIASES, YARD_OUT_ALIASES } from './transform'

describe('transform adapters', () => {
  it('converts snake_case keys to camelCase, recursively', () => {
    const out = toCamel<any>({
      serial_number: 'S1',
      current_packml_state: 'Execute',
      nested_obj: { last_seen: 't', inner_value: 1 },
      list_field: [{ a_b: 1 }, { c_d: 2 }],
    })
    expect(out.serialNumber).toBe('S1')
    expect(out.currentPackmlState).toBe('Execute')
    expect(out.nestedObj.lastSeen).toBe('t')
    expect(out.nestedObj.innerValue).toBe(1)
    expect(out.listField).toEqual([{ aB: 1 }, { cD: 2 }])
  })

  it('converts camelCase back to snake_case', () => {
    const out = toSnake<any>({ assetTypeId: 'a', isActive: true, workcellId: null })
    expect(out).toEqual({ asset_type_id: 'a', is_active: true, workcell_id: null })
  })

  it('leaves opaque config/metadata dicts untouched (keys are data)', () => {
    // The key itself is renamed, but inner keys are preserved verbatim.
    const src = { connection_config: { mqtt_broker_2: 'x', TLS_v1: true }, metadata: { A_b: 1 } }
    const out = toCamel<any>(src)
    expect(out.connectionConfig).toEqual({ mqtt_broker_2: 'x', TLS_v1: true })
    expect(out.metadata).toEqual({ A_b: 1 })
  })

  it('round-trips an opaque config dict without key loss', () => {
    const original = { connectionConfig: { mqtt_broker_2: 'x', poll_ms: 500 } }
    const wire = toSnake<any>(original)
    expect(wire.connection_config).toEqual({ mqtt_broker_2: 'x', poll_ms: 500 })
    const back = toCamel<any>(wire)
    expect(back.connectionConfig).toEqual({ mqtt_broker_2: 'x', poll_ms: 500 })
  })

  it('applies field-name aliases beyond casing (yard)', () => {
    const back = toCamel<any>({ trailer_number: 'T1', check_in_at: 'now' }, YARD_ALIASES)
    expect(back.trailerId).toBe('T1')
    expect(back.checkedInAt).toBe('now')
    const wire = toSnake<any>({ trailerId: 'T1', checkedInAt: 'now' }, YARD_OUT_ALIASES)
    expect(wire.trailer_number).toBe('T1')
    expect(wire.check_in_at).toBe('now')
  })

  it('treats camelCase metaData as opaque (FS-59: a missing spelling variant meant toCamel recursed into blob data keys)', () => {
    const back = toCamel<any>({ id: 'x', metaData: { seal_code: 'S1', dock_door: 4 } })
    expect(back.metaData).toEqual({ seal_code: 'S1', dock_door: 4 })
  })

  it('passes through primitives and string arrays (metric names stay intact)', () => {
    expect(toCamel<any>({ asset_id: 'a', metrics: ['spindle_speed', 'motor_temp'] })).toEqual({
      assetId: 'a',
      metrics: ['spindle_speed', 'motor_temp'],
    })
  })
})
