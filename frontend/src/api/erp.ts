import { api } from './client'

// ERP integration API client (Phase A, task 5).
// Env toggle (matches fleetTracker.ts): mock by default so demos work offline,
// real backend when VITE_USE_MOCK=false. Never touches Harsh's mockMode.ts.
const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

export interface ERPIntegration {
  id: string
  integration_name: string
  erp_type: string
  erp_version?: string | null
  auth_type: string
  base_url: string
  is_active: boolean
  sync_schedule: string
  sync_frequency_minutes: number
  last_successful_sync?: string | null
  created_at: string
  updated_at: string
}

export interface ERPIntegrationCreate {
  integration_name: string
  erp_type: string
  erp_version?: string
  auth_type: string
  base_url: string
  auth_config: Record<string, any>
  rate_limit?: { requests_per_minute: number; burst_limit: number }
  sync_schedule?: string
  sync_frequency_minutes?: number
  webhook_secret?: string
}

export interface SyncStatus {
  entity_type: string
  last_sync_at?: string | null
  last_sync_status?: string | null
  records_synced: number
  records_failed: number
  sync_duration_seconds?: number | null
  next_sync_at?: string | null
}

export interface FieldMapping {
  id: string
  source_entity: string
  source_field: string
  target_entity: string
  target_field: string
  transformation_rule?: string | null
  data_type?: string | null
  is_required: boolean
}

export interface ConnectionTestResult {
  status: string
  message: string
  details?: Record<string, any>
  tested_at: string
}

// ---- demo-ready mock data ----
const mockIntegrations: ERPIntegration[] = [
  {
    id: 'erp-sap-1', integration_name: 'SAP S/4HANA (Prod)', erp_type: 'sap',
    erp_version: 'S/4HANA 2023', auth_type: 'oauth2', base_url: 'https://sap.example.com',
    is_active: true, sync_schedule: '0 * * * *', sync_frequency_minutes: 60,
    last_successful_sync: new Date(Date.now() - 3600_000).toISOString(),
    created_at: '2026-06-01T10:00:00Z', updated_at: '2026-07-09T09:00:00Z',
  },
  {
    id: 'erp-netsuite-1', integration_name: 'NetSuite (Finance)', erp_type: 'netsuite',
    erp_version: '2024.1', auth_type: 'token', base_url: 'https://netsuite.example.com',
    is_active: true, sync_schedule: '*/30 * * * *', sync_frequency_minutes: 30,
    last_successful_sync: new Date(Date.now() - 1800_000).toISOString(),
    created_at: '2026-06-15T10:00:00Z', updated_at: '2026-07-09T08:30:00Z',
  },
]
const mockSyncStatus: Record<string, SyncStatus[]> = {
  'erp-sap-1': [
    { entity_type: 'PurchaseOrder', last_sync_at: new Date(Date.now() - 3600_000).toISOString(), last_sync_status: 'success', records_synced: 128, records_failed: 0, sync_duration_seconds: 12 },
    { entity_type: 'Invoice', last_sync_at: new Date(Date.now() - 3600_000).toISOString(), last_sync_status: 'success', records_synced: 74, records_failed: 2, sync_duration_seconds: 8 },
  ],
}
const mockMappings: Record<string, FieldMapping[]> = {
  'erp-sap-1': [
    { id: 'm1', source_entity: 'PurchaseOrder', source_field: 'PONumber', target_entity: 'operation', target_field: 'job_id', data_type: 'string', is_required: true },
  ],
}

export const erpApi = {
  async listIntegrations(): Promise<ERPIntegration[]> {
    if (USE_MOCK) { await delay(200); return [...mockIntegrations] }
    const res = await api.get<ERPIntegration[]>('/api/v1/erp/integrations')
    return res.data
  },
  async getIntegration(id: string): Promise<ERPIntegration> {
    if (USE_MOCK) { await delay(150); return mockIntegrations.find((i) => i.id === id)! }
    return (await api.get<ERPIntegration>(`/api/v1/erp/integrations/${id}`)).data
  },
  async createIntegration(body: ERPIntegrationCreate): Promise<ERPIntegration> {
    if (USE_MOCK) {
      await delay(300)
      const created: ERPIntegration = {
        id: `erp-${Date.now()}`, integration_name: body.integration_name, erp_type: body.erp_type,
        erp_version: body.erp_version ?? null, auth_type: body.auth_type, base_url: body.base_url,
        is_active: true, sync_schedule: body.sync_schedule ?? '0 * * * *',
        sync_frequency_minutes: body.sync_frequency_minutes ?? 60, last_successful_sync: null,
        created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
      }
      mockIntegrations.push(created)
      return created
    }
    return (await api.post<ERPIntegration>('/api/v1/erp/integrations', body)).data
  },
  async updateIntegration(id: string, body: Partial<ERPIntegrationCreate> & { is_active?: boolean }): Promise<ERPIntegration> {
    if (USE_MOCK) {
      await delay(200)
      const i = mockIntegrations.find((x) => x.id === id)!
      Object.assign(i, body, { updated_at: new Date().toISOString() })
      return i
    }
    return (await api.put<ERPIntegration>(`/api/v1/erp/integrations/${id}`, body)).data
  },
  async deleteIntegration(id: string): Promise<void> {
    if (USE_MOCK) { await delay(150); const idx = mockIntegrations.findIndex((x) => x.id === id); if (idx >= 0) mockIntegrations.splice(idx, 1); return }
    await api.delete(`/api/v1/erp/integrations/${id}`)
  },
  async testConnection(id: string): Promise<ConnectionTestResult> {
    if (USE_MOCK) { await delay(600); return { status: 'success', message: 'Connection test successful (demo)', details: { healthy: true }, tested_at: new Date().toISOString() } }
    return (await api.post<ConnectionTestResult>(`/api/v1/erp/integrations/${id}/test`)).data
  },
  async triggerSync(id: string, entityType?: string): Promise<{ status: string; message: string }> {
    if (USE_MOCK) { await delay(400); return { status: 'triggered', message: 'Sync triggered (demo)' } }
    const q = entityType ? `?entity_type=${encodeURIComponent(entityType)}` : ''
    return (await api.post<{ status: string; message: string }>(`/api/v1/erp/integrations/${id}/sync${q}`)).data
  },
  async getSyncStatus(id: string): Promise<SyncStatus[]> {
    if (USE_MOCK) { await delay(200); return mockSyncStatus[id] ?? [] }
    return (await api.get<SyncStatus[]>(`/api/v1/erp/integrations/${id}/sync-status`)).data
  },
  async listFieldMappings(id: string): Promise<FieldMapping[]> {
    if (USE_MOCK) { await delay(200); return mockMappings[id] ?? [] }
    return (await api.get<FieldMapping[]>(`/api/v1/erp/integrations/${id}/mappings`)).data
  },
  async createFieldMapping(id: string, body: Omit<FieldMapping, 'id'>): Promise<FieldMapping> {
    if (USE_MOCK) { await delay(200); const m = { ...body, id: `m-${Date.now()}` }; (mockMappings[id] ??= []).push(m); return m }
    return (await api.post<FieldMapping>(`/api/v1/erp/integrations/${id}/mappings`, body)).data
  },
  async deleteFieldMapping(id: string, mappingId: string): Promise<void> {
    if (USE_MOCK) { await delay(150); const arr = mockMappings[id] ?? []; const idx = arr.findIndex((m) => m.id === mappingId); if (idx >= 0) arr.splice(idx, 1); return }
    await api.delete(`/api/v1/erp/integrations/${id}/mappings/${mappingId}`)
  },
  supportedTypes(): string[] {
    return ['sap', 'oracle', 'dynamics', 'netsuite', 'odoo', 'infor', 'epicor']
  },
}
