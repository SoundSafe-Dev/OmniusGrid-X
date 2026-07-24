import { describe, expect, it } from 'vitest'

import { circleRenderableZones } from './GeofencingPanel'
import type { GeofenceZoneExtended } from '../../types'

// The map rendered `zone.center!.latitude` for every active zone. A centerless
// zone (polygon type, or malformed data) threw and — with only the app-root
// ErrorBoundary — blanked the whole app. circleRenderableZones must drop those.

const zone = (over: Partial<GeofenceZoneExtended>): GeofenceZoneExtended =>
  ({ id: 'z', isActive: true, ...over }) as GeofenceZoneExtended

describe('circleRenderableZones', () => {
  it('keeps active zones that have a numeric center and radius', () => {
    const z = zone({ id: 'ok', center: { latitude: 1, longitude: 2 } as any, radius: 100 })
    expect(circleRenderableZones([z]).map(x => x.id)).toEqual(['ok'])
  })

  it('drops a centerless zone instead of letting it crash the map', () => {
    const polygon = zone({ id: 'poly', center: undefined, radius: undefined })
    expect(circleRenderableZones([polygon])).toEqual([])
  })

  it('drops a zone with a center but no radius', () => {
    const z = zone({ id: 'no-radius', center: { latitude: 1, longitude: 2 } as any })
    expect(circleRenderableZones([z])).toEqual([])
  })

  it('drops inactive zones', () => {
    const z = zone({ id: 'off', isActive: false, center: { latitude: 1, longitude: 2 } as any, radius: 50 })
    expect(circleRenderableZones([z])).toEqual([])
  })

  it('keeps the drawable zones and skips the rest in a mixed list', () => {
    const good = zone({ id: 'good', center: { latitude: 1, longitude: 2 } as any, radius: 10 })
    const bad = zone({ id: 'bad', center: undefined, radius: undefined })
    expect(circleRenderableZones([good, bad, good]).map(z => z.id)).toEqual(['good', 'good'])
  })
})
