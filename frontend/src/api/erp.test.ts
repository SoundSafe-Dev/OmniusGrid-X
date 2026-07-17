import { describe, expect, it } from 'vitest'
import { erpApi } from './erp'

// Runs in mock mode (VITE_USE_MOCK unset -> mock), so no network needed.
describe('erpApi (mock mode)', () => {
  it('lists demo integrations', async () => {
    const list = await erpApi.listIntegrations()
    expect(list.length).toBeGreaterThanOrEqual(2)
    expect(list[0]).toHaveProperty('erp_type')
  })

  it('create + delete round-trips', async () => {
    const created = await erpApi.createIntegration({
      integration_name: 'Test Odoo', erp_type: 'odoo', auth_type: 'api_key',
      base_url: 'https://odoo.example.com', auth_config: { api_key: 'k' },
    })
    expect(created.id).toBeTruthy()
    const afterCreate = await erpApi.listIntegrations()
    expect(afterCreate.find((i) => i.id === created.id)).toBeDefined()
    await erpApi.deleteIntegration(created.id)
    const afterDelete = await erpApi.listIntegrations()
    expect(afterDelete.find((i) => i.id === created.id)).toBeUndefined()
  })

  it('test connection returns a status', async () => {
    const res = await erpApi.testConnection('erp-sap-1')
    expect(res.status).toBe('success')
    expect(res.tested_at).toBeTruthy()
  })

  it('exposes the supported ERP types', () => {
    expect(erpApi.supportedTypes()).toContain('sap')
    expect(erpApi.supportedTypes()).toContain('netsuite')
  })
})
