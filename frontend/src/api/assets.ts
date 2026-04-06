import { api } from './client';
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
    const response = await api.get<Asset[]>('/api/v1/assets/', { params });
    return {
      items: response.data,
      total: response.data.length,
      skip: params?.skip || 0,
      limit: params?.limit || 100,
      hasMore: response.data.length === (params?.limit || 100),
    };
  },

  get: async (assetId: string): Promise<Asset> => {
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
    const response = await api.get<OEEMetrics>(`/api/v1/dashboard/assets/${assetId}/oee`, {
      params: { hours },
    });
    return response.data;
  },

  getFleetOEE: async (organizationId?: string, hours: number = 24): Promise<FleetOEE> => {
    const response = await api.get<FleetOEE>('/api/v1/dashboard/fleet/oee', {
      params: { organization_id: organizationId, hours },
    });
    return response.data;
  },
};

export const workcellsApi = {
  list: async (organizationId?: string): Promise<Workcell[]> => {
    const response = await api.get<Workcell[]>('/api/v1/workcells/', {
      params: organizationId ? { organization_id: organizationId } : undefined,
    });
    return response.data;
  },

  get: async (workcellId: string): Promise<Workcell> => {
    const response = await api.get<Workcell>(`/api/v1/workcells/${workcellId}`);
    return response.data;
  },
};

export const organizationsApi = {
  list: async (): Promise<Organization[]> => {
    const response = await api.get<Organization[]>('/api/v1/organizations/');
    return response.data;
  },

  get: async (orgId: string): Promise<Organization> => {
    const response = await api.get<Organization>(`/api/v1/organizations/${orgId}`);
    return response.data;
  },
};
