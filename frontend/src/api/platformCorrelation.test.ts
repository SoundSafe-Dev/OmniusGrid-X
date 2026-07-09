import { describe, expect, it } from 'vitest'
import { platformCorrelationApi } from './platformCorrelation'

// Mock mode (default): no network.
describe('platformCorrelationApi (mock mode)', () => {
  it('lists the platform source types', async () => {
    const types = await platformCorrelationApi.listSourceTypes()
    expect(types.map((t) => t.source_type)).toEqual(
      expect.arrayContaining(['asset_telemetry', 'yard', 'transportation'])
    )
  })

  it('attaches a source and returns a row count', async () => {
    const res = await platformCorrelationApi.attach('sess-1', 'asset_telemetry', { asset_id: 'a1' })
    expect(res.source_type).toBe('asset_telemetry')
    expect(res.row_count).toBeGreaterThan(0)
    expect(res.data_type).toBe('spreadsheet')
  })
})
