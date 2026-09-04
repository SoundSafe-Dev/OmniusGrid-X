import { api } from './client';
import { toListResult } from './listResult';
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
  // No organizationId. `GET /api/v1/assets/` declares only workcell_id, asset_type_id,
  // is_active, skip and limit — and FastAPI drops unknown query parameters SILENTLY, so
  // supplying one returned the caller's own assets either way while reading, at the call
  // site and in the type, as a tenant filter. The organisation comes from the JWT.
  //
  // The backend guard could not see this call at all: `api.get<{ items: Asset[]; meta:
  // { … } }>(…)` has braces and a semicolon inside its type argument, and the
  // extractor's pattern excluded both — so it was neither checked nor counted as
  // skipped. Six calls were invisible that way; the extractor now scans for the opening
  // parenthesis instead of pattern-matching up to it.
  workcellId?: string;
  assetTypeId?: string;
  isActive?: boolean;
  /** Case-insensitive name substring (P6). */
  search?: string;
  skip?: number;
  limit?: number;
}

export const assetsApi = {
  list: async (params?: AssetListParams): Promise<PaginatedResponse<Asset>> => {
    if (USE_MOCK) return mockApi.getAssets();
    // Backend now returns a {items, meta} envelope (FS-82) with a real total,
    // instead of a bare array we had to fake a count from. Map it to the flat
    // PaginatedResponse; tolerate either casing of has_more from the transform seam.
    // Built explicitly rather than forwarded wholesale. Dropping `organizationId` from
    // AssetListParams is a compile-time guarantee; passing the caller's object straight
    // through still puts any extra key on the wire at runtime, where FastAPI discards
    // unknown query parameters in silence. These five are what the endpoint declares.
    const query = {
      workcell_id: params?.workcellId,
      asset_type_id: params?.assetTypeId,
      is_active: params?.isActive,
      search: params?.search,
      skip: params?.skip,
      limit: params?.limit,
    };
    const response = await api.get<{
      items: Asset[];
      meta: { total: number; skip: number; limit: number; has_more?: boolean; hasMore?: boolean };
    }>('/api/v1/assets/', { params: query });
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
    return toListResult(response).items;
  },

  /**
   * THIS INVERTED THE CALLER'S INTENT. It posted `{ inMaintenance }` as a JSON BODY, and
   * the endpoint declares `enabled: bool = True` — a scalar, which FastAPI reads from the
   * QUERY STRING. So the body was ignored and `enabled` fell to its default:
   *
   *   setMaintenanceMode(id, false)  ->  POST .../maintenance  ->  enabled = True
   *
   * Calling this to take an asset OUT of maintenance put it IN. Not a 422 that someone
   * would have noticed — a 200, with the opposite of the requested effect, and a response
   * body reading "Game-theoretic engine commands are blocked".
   *
   * `enabled` is sent explicitly now. The endpoint's `= True` default is left alone
   * deliberately: changing it would break any caller that relies on the bare POST meaning
   * "enable", and the fix belongs on the side that was wrong.
   */
  setMaintenanceMode: async (assetId: string, inMaintenance: boolean): Promise<void> => {
    await api.post(`/admin/assets/${assetId}/maintenance`, null, {
      params: { enabled: inMaintenance },
    });
  },
};

export const dashboardApi = {
  // The organization is always derived from the authenticated user server-side.
  // This used to accept an `organizationId` that became an `organization_id`
  // query param; the backend no longer honours it (it let a caller aim the
  // query at another tenant), so passing it would have been silently ignored.
  getOverview: async (): Promise<DashboardOverview> => {
    if (USE_MOCK) return mockApi.getDashboardOverview();
    const response = await api.get<DashboardOverview>('/api/v1/dashboard/overview');
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

  // Org is derived server-side from the authenticated user (see getOverview).
  getFleetOEE: async (hours: number = 24): Promise<FleetOEE> => {
    if (USE_MOCK) return mockApi.getFleetOEE();
    const response = await api.get<FleetOEE>('/api/v1/dashboard/fleet/oee', {
      params: { hours },
    });
    return response.data;
  },
};

export const workcellsApi = {
  // No organizationId parameter. `GET /api/v1/workcells/` declares only `skip` and
  // `limit`, and FastAPI drops unknown query parameters SILENTLY — so passing one
  // returned the caller's own workcells either way while looking like a filter had been
  // applied. The organisation comes from the JWT.
  list: async (): Promise<Workcell[]> => {
    if (USE_MOCK) return mockApi.getWorkcells();
    // FS-99: backend returns the {items, meta} pagination envelope now; callers
    // consume a plain array, so unwrap here.
    const response = await api.get<{ items: Workcell[]; meta: { total: number } }>(
      '/api/v1/workcells/',
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
