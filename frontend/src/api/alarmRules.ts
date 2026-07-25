import { api } from './client';
import { USE_MOCK } from './mockMode';
import { registerTransform } from './transformRegistry';
import {
  AlarmRule,
  AlarmRuleCreate,
  AlarmRuleFilters,
  AlarmRuleUpdate,
  PaginatedResponse,
} from '../types';

// Casing handled by the axios seam (FS-61) — no per-call toCamel/toSnake, so
// `duration_seconds` arrives as `durationSeconds` and request bodies are
// converted on the way out.
registerTransform('/api/v1/alarm-rules');

// Mock fixtures live here rather than in mockApi.ts because they exist only to
// keep the offline demo page renderable; nothing else consumes them. Two rules
// with contrasting shapes — one instant/untargeted, one duration+hysteresis on a
// single asset — so the page's own rendering of those columns is exercised.
const MOCK_RULES: AlarmRule[] = [
  {
    id: 'rule-mock-1',
    organizationId: 'org-mock',
    name: 'Spindle temperature critical',
    description: 'Bearing temperature above the ISO limit',
    metricName: 'temperature',
    comparator: 'gt',
    threshold: 80,
    durationSeconds: 300,
    hysteresis: 2,
    severity: 'critical',
    alarmCode: 'TEMP_HIGH',
    messageTemplate: '{metricName} reached {value} (limit {threshold})',
    assetId: null,
    assetTypeId: null,
    workcellId: null,
    isEnabled: true,
    createdBy: null,
    createdAt: new Date(Date.now() - 86_400_000).toISOString(),
    updatedAt: new Date(Date.now() - 86_400_000).toISOString(),
  },
  {
    id: 'rule-mock-2',
    organizationId: 'org-mock',
    name: 'Coolant pressure low',
    description: null,
    metricName: 'pressure',
    comparator: 'lt',
    threshold: 20,
    durationSeconds: 0,
    hysteresis: 0,
    severity: 'high',
    alarmCode: 'PRESSURE_LOW',
    messageTemplate: null,
    assetId: null,
    assetTypeId: null,
    workcellId: null,
    isEnabled: false,
    createdBy: null,
    createdAt: new Date(Date.now() - 3_600_000).toISOString(),
    updatedAt: new Date(Date.now() - 3_600_000).toISOString(),
  },
];

export const alarmRulesApi = {
  list: async (filters?: AlarmRuleFilters): Promise<PaginatedResponse<AlarmRule>> => {
    if (USE_MOCK) {
      return {
        items: MOCK_RULES,
        total: MOCK_RULES.length,
        skip: 0,
        limit: MOCK_RULES.length,
        hasMore: false,
      };
    }
    const params: Record<string, unknown> = {};
    if (filters?.metricName) params.metric_name = filters.metricName;
    if (filters?.severity) params.severity = filters.severity;
    if (filters?.isEnabled !== undefined) params.is_enabled = filters.isEnabled;
    if (filters?.skip !== undefined) params.skip = filters.skip;
    if (filters?.limit !== undefined) params.limit = filters.limit;

    // {items, meta} envelope (FS-82) with a real total.
    const response = await api.get<{
      items: AlarmRule[];
      meta: { total: number; skip: number; limit: number; has_more?: boolean; hasMore?: boolean };
    }>('/api/v1/alarm-rules/', { params });
    const { items, meta } = response.data;
    return {
      items,
      total: meta.total,
      skip: meta.skip,
      limit: meta.limit,
      hasMore: meta.hasMore ?? meta.has_more ?? meta.skip + items.length < meta.total,
    };
  },

  get: async (ruleId: string): Promise<AlarmRule> => {
    const response = await api.get<AlarmRule>(`/api/v1/alarm-rules/${ruleId}`);
    return response.data;
  },

  create: async (payload: AlarmRuleCreate): Promise<AlarmRule> => {
    const response = await api.post<AlarmRule>('/api/v1/alarm-rules/', payload);
    return response.data;
  },

  update: async (ruleId: string, payload: AlarmRuleUpdate): Promise<AlarmRule> => {
    // PATCH, not PUT: the server distinguishes "omitted" from "reset to default",
    // so sending only the changed fields cannot silently re-enable a disabled rule.
    const response = await api.patch<AlarmRule>(`/api/v1/alarm-rules/${ruleId}`, payload);
    return response.data;
  },

  remove: async (ruleId: string): Promise<void> => {
    await api.delete(`/api/v1/alarm-rules/${ruleId}`);
  },
};
