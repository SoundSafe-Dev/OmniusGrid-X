import { api } from './client'

// Attach live platform data (sensor/asset telemetry, yard, transportation) to an
// analysis session as a correlation source. Env toggle keeps demos offline.
import { USE_MOCK } from './mockMode';
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

export interface PlatformSourceType {
  source_type: string
  label: string
}

export interface AttachedSource {
  id: string
  source_type: string
  source_id: string | null
  file_name: string | null
  data_type: string | null
  row_count: number
}

const MOCK_TYPES: PlatformSourceType[] = [
  { source_type: 'asset_telemetry', label: 'Asset / sensor telemetry' },
  { source_type: 'yard', label: 'Yard inventory' },
  { source_type: 'transportation', label: 'Shipments' },
  { source_type: 'erp', label: 'ERP entities (orders, invoices, work orders)' },
]

export const platformCorrelationApi = {
  async listSourceTypes(): Promise<PlatformSourceType[]> {
    if (USE_MOCK) { await delay(150); return MOCK_TYPES }
    return (await api.get<PlatformSourceType[]>('/api/v1/nlp/platform-sources')).data
  },
  async attach(sessionId: string, sourceType: string, params: Record<string, any> = {}): Promise<AttachedSource> {
    if (USE_MOCK) {
      await delay(300)
      return {
        id: `plat-${Date.now()}`, source_type: sourceType,
        source_id: params.asset_id ?? sourceType, file_name: `${sourceType}-demo`,
        data_type: 'spreadsheet', row_count: 42,
      }
    }
    const res = await api.post<AttachedSource>(
      `/api/v1/nlp/sessions/${sessionId}/platform-data`,
      { source_type: sourceType, params }
    )
    return res.data
  },
}
