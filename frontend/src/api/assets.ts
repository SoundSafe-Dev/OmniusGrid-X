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
import { toCamel, toSnake } from './transform';

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
    const response = await api.get<any>('/api/v1/assets/', { params: toSnake(params ?? {}) });
    const items = toCamel<Asset[]>(response.data);
    return {
      items,
      total: items.length,
      skip: params?.skip || 0,
      limit: params?.limit || 100,
      hasMore: items.length === (params?.limit || 100),
    };
  },

  get: async (assetId: string): Promise<Asset> => {
    if (USE_MOCK) {
      const asset = await mockApi.getAsset(assetId);
      if (!asset) throw new Error('Asset not found');
      return asset;
    }
    const response = await api.get<any>(`/api/v1/assets/${assetId}`);
    return toCamel<Asset>(response.data);
  },

  create: async (assetData: AssetCreate): Promise<Asset> => {
    const response = await api.post<any>('/api/v1/assets/', toSnake(assetData));
    return toCamel<Asset>(response.data);
  },

  update: async (assetId: string, assetData: AssetUpdate): Promise<Asset> => {
    const response = await api.put<any>(`/api/v1/assets/${assetId}`, toSnake(assetData));
    return toCamel<Asset>(response.data);
  },

  delete: async (assetId: string): Promise<void> => {
    await api.delete(`/api/v1/assets/${assetId}`);
  },

  getStatus: async (assetId: string): Promise<AssetStatus> => {
    const response = await api.get<any>(`/api/v1/assets/${assetId}/status`);
    return toCamel<AssetStatus>(response.data);
  },

  getTypes: async (category?: string): Promise<AssetType[]> => {
    if (USE_MOCK) return mockApi.getAssetTypes();
    const response = await api.get<any>('/api/v1/assets/types/', {
      params: category ? { category } : undefined,
    });
    return toCamel<AssetType[]>(response.data);
  },

  restartCollector: async (assetId: string): Promise<void> => {
    await api.post(`/admin/collectors/${assetId}/restart`);
  },

  setMaintenanceMode: async (assetId: string, inMaintenance: boolean): Promise<void> => {
    await api.post(`/admin/assets/${assetId}/maintenance`, toSnake({ inMaintenance }));
  },
};

export const dashboardApi = {
  getOverview: async (organizationId?: string): Promise<DashboardOverview> => {
    if (USE_MOCK) return mockApi.getDashboardOverview();
    const response = await api.get<any>('/api/v1/dashboard/overview', {
      params: organizationId ? { organization_id: organizationId } : undefined,
    });
    return toCamel<DashboardOverview>(response.data);
  },

  getWorkcellStatus: async (workcellId: string): Promise<{
    workcellId: string;
    assetCount: number;
    assets: AssetStatus[];
  }> => {
    const response = await api.get(`/api/v1/dashboard/workcells/${workcellId}/status`);
    return toCamel(response.data);
  },

  getAssetOEE: async (assetId: string, hours: number = 24): Promise<OEEMetrics> => {
    if (USE_MOCK) return mockApi.getAssetOEE(assetId);
    const response = await api.get<any>(`/api/v1/dashboard/assets/${assetId}/oee`, {
      params: { hours },
    });
    return toCamel<OEEMetrics>(response.data);
  },

  getFleetOEE: async (organizationId?: string, hours: number = 24): Promise<FleetOEE> => {
    if (USE_MOCK) return mockApi.getFleetOEE();
    const response = await api.get<any>('/api/v1/dashboard/fleet/oee', {
      params: { organization_id: organizationId, hours },
    });
    return toCamel<FleetOEE>(response.data);
  },
};

export const workcellsApi = {
  list: async (organizationId?: string): Promise<Workcell[]> => {
    if (USE_MOCK) return mockApi.getWorkcells();
    const response = await api.get<any>('/api/v1/workcells/', {
      params: organizationId ? { organization_id: organizationId } : undefined,
    });
    return toCamel<Workcell[]>(response.data);
  },

  get: async (workcellId: string): Promise<Workcell> => {
    const response = await api.get<any>(`/api/v1/workcells/${workcellId}`);
    return toCamel<Workcell>(response.data);
  },
};

export const organizationsApi = {
  list: async (): Promise<Organization[]> => {
    if (USE_MOCK) return mockApi.getOrganizations();
    const response = await api.get<any>('/api/v1/organizations/');
    return toCamel<Organization[]>(response.data);
  },

  get: async (orgId: string): Promise<Organization> => {
    const response = await api.get<any>(`/api/v1/organizations/${orgId}`);
    return toCamel<Organization>(response.data);
  },
};
