import { api } from './client';
import { mockApi } from './mockApi';
import {
  Asset,
  AssetCreate,
  AssetUpdate,
  AssetStatus,
  AssetType,
  PaginatedResponse,
  FleetOEE,
  OEEMetrics,
  DashboardOverview,
  Workcell,
  Organization,
} from '../types';
import { USE_MOCK } from './mockMode';
import { registerTransform } from './transformRegistry';

// FS-61: casing handled by the axios seam — no per-call toCamel/toSnake.
registerTransform('/api/v1/assets');
registerTransform('/api/v1/dashboard');
registerTransform('/api/v1/workcells');
registerTransform('/api/v1/organizations');
registerTransform('/admin/assets'); // setMaintenanceMode body -> snake_case

interface AssetListParams {
  organizationId?: string;
  workcellId?: string;
  assetTypeId?: string;
  isActive?: boolean;
  skip?: number;
  limit?: number;
}

export const assetsApi = {
  list: async (params?: AssetListParams): Promise<PaginatedResponse<Asset>> => {
    if (USE_MOCK) return mockApi.getAssets();
    // Backend now returns a {items, meta} envelope (FS-82) with a real total,
    // instead of a bare array we had to fake a count from. Map it to the flat
    // PaginatedResponse; tolerate either casing of has_more from the transform seam.
    const response = await api.get<{
      items: Asset[];
      meta: { total: number; skip: number; limit: number; has_more?: boolean; hasMore?: boolean };
    }>('/api/v1/assets/', { params });
    const { items, meta } = response.data;
    return {
      items,
      total: meta.total,
      skip: meta.skip,
      limit: meta.limit,
      hasMore: meta.hasMore ?? meta.has_more ?? meta.skip + items.length < meta.total,
    };
  },

  get: async (assetId: string): Promise<Asset> => {
    if (USE_MOCK) {
      const asset = await mockApi.getAsset(assetId);
      if (!asset) throw new Error('Asset not found');
      return asset;
    }
    const response = await api.get<Asset>(`/api/v1/assets/${assetId}`);
    return response.data;
  },

  create: async (assetData: AssetCreate): Promise<Asset> => {
    const response = await api.post<Asset>('/api/v1/assets/', assetData);
    return response.data;
  },

  update: async (assetId: string, assetData: AssetUpdate): Promise<Asset> => {
    const response = await api.put<Asset>(`/api/v1/assets/${assetId}`, assetData);
    return response.data;
  },

  delete: async (assetId: string): Promise<void> => {
    await api.delete(`/api/v1/assets/${assetId}`);
  },

  getStatus: async (assetId: string): Promise<AssetStatus> => {
    const response = await api.get<AssetStatus>(`/api/v1/assets/${assetId}/status`);
    return response.data;
  },

  getTypes: async (category?: string): Promise<AssetType[]> => {
    if (USE_MOCK) return mockApi.getAssetTypes();
    const response = await api.get<AssetType[]>('/api/v1/assets/types/', {
      params: category ? { category } : undefined,
    });
    return response.data;
  },

  restartCollector: async (assetId: string): Promise<void> => {
    await api.post(`/admin/collectors/${assetId}/restart`);
  },

  setMaintenanceMode: async (assetId: string, inMaintenance: boolean): Promise<void> => {
    await api.post(`/admin/assets/${assetId}/maintenance`, { inMaintenance });
  },
};

export const dashboardApi = {
  getOverview: async (organizationId?: string): Promise<DashboardOverview> => {
    if (USE_MOCK) return mockApi.getDashboardOverview();
    const response = await api.get<DashboardOverview>('/api/v1/dashboard/overview', {
      params: organizationId ? { organization_id: organizationId } : undefined,
    });
    return response.data;
  },

  getWorkcellStatus: async (workcellId: string): Promise<{
    workcellId: string;
    assetCount: number;
    assets: AssetStatus[];
  }> => {
    const response = await api.get(`/api/v1/dashboard/workcells/${workcellId}/status`);
    return response.data;
  },

  getAssetOEE: async (assetId: string, hours: number = 24): Promise<OEEMetrics> => {
    if (USE_MOCK) return mockApi.getAssetOEE(assetId);
    const response = await api.get<OEEMetrics>(`/api/v1/dashboard/assets/${assetId}/oee`, {
      params: { hours },
    });
    return response.data;
  },

  getFleetOEE: async (organizationId?: string, hours: number = 24): Promise<FleetOEE> => {
    if (USE_MOCK) return mockApi.getFleetOEE();
    const response = await api.get<FleetOEE>('/api/v1/dashboard/fleet/oee', {
      params: { organization_id: organizationId, hours },
    });
    return response.data;
  },
};

export const workcellsApi = {
  list: async (organizationId?: string): Promise<Workcell[]> => {
    if (USE_MOCK) return mockApi.getWorkcells();
    // FS-99: backend returns the {items, meta} pagination envelope now; callers
    // consume a plain array, so unwrap here.
    const response = await api.get<{ items: Workcell[]; meta: { total: number } }>(
      '/api/v1/workcells/',
      { params: organizationId ? { organization_id: organizationId } : undefined },
    );
    return response.data.items;
  },

  get: async (workcellId: string): Promise<Workcell> => {
    const response = await api.get<Workcell>(`/api/v1/workcells/${workcellId}`);
    return response.data;
  },
};

export const organizationsApi = {
  list: async (): Promise<Organization[]> => {
    if (USE_MOCK) return mockApi.getOrganizations();
    const response = await api.get<Organization[]>('/api/v1/organizations/');
    return response.data;
  },

  get: async (orgId: string): Promise<Organization> => {
    const response = await api.get<Organization>(`/api/v1/organizations/${orgId}`);
    return response.data;
  },
};
