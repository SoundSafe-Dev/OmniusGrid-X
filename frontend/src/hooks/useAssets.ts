import { useQuery, useMutation, useQueryClient, UseQueryOptions } from 'react-query';
import { assetsApi, dashboardApi } from '../api';
import {
  Asset,
  AssetCreate,
  AssetUpdate,
  AssetType,
  PaginatedResponse,
  DashboardOverview,
  FleetOEE,
  OEEMetrics,
  Workcell,
  Organization,
} from '../types';

const ASSETS_QUERY_KEY = 'assets';
const DASHBOARD_QUERY_KEY = 'dashboard';

// Assets
export function useAssets(
  params?: Parameters<typeof assetsApi.list>[0],
  options?: UseQueryOptions<PaginatedResponse<Asset>, Error>
) {
  return useQuery<PaginatedResponse<Asset>, Error>(
    [ASSETS_QUERY_KEY, 'list', params],
    () => assetsApi.list(params),
    options
  );
}

export function useAsset(assetId: string) {
  return useQuery<Asset, Error>(
    [ASSETS_QUERY_KEY, 'detail', assetId],
    () => assetsApi.get(assetId),
    {
      enabled: !!assetId,
    }
  );
}

export function useCreateAsset() {
  const queryClient = useQueryClient();

  return useMutation((data: AssetCreate) => assetsApi.create(data), {
    onSuccess: () => {
      queryClient.invalidateQueries([ASSETS_QUERY_KEY]);
    },
  });
}

export function useUpdateAsset() {
  const queryClient = useQueryClient();

  return useMutation(
    ({ assetId, data }: { assetId: string; data: AssetUpdate }) =>
      assetsApi.update(assetId, data),
    {
      onSuccess: (_, variables) => {
        queryClient.invalidateQueries([ASSETS_QUERY_KEY]);
        queryClient.invalidateQueries([ASSETS_QUERY_KEY, 'detail', variables.assetId]);
      },
    }
  );
}

export function useDeleteAsset() {
  const queryClient = useQueryClient();

  return useMutation((assetId: string) => assetsApi.delete(assetId), {
    onSuccess: () => {
      queryClient.invalidateQueries([ASSETS_QUERY_KEY]);
    },
  });
}

export function useAssetTypes(category?: string) {
  return useQuery<AssetType[], Error>(
    [ASSETS_QUERY_KEY, 'types', category],
    () => assetsApi.getTypes(category)
  );
}

export function useWorkcells(organizationId?: string) {
  return useQuery<Workcell[], Error>(
    [ASSETS_QUERY_KEY, 'workcells', organizationId],
    () => assetsApi.workcellsApi.list(organizationId)
  );
}

export function useOrganizations() {
  return useQuery<Organization[], Error>(
    [ASSETS_QUERY_KEY, 'organizations'],
    () => assetsApi.organizationsApi.list()
  );
}

// Dashboard
export function useDashboardOverview(organizationId?: string) {
  return useQuery<DashboardOverview, Error>(
    [DASHBOARD_QUERY_KEY, 'overview', organizationId],
    () => dashboardApi.getOverview(organizationId),
    {
      refetchInterval: 30000, // Refresh every 30 seconds
    }
  );
}

export function useFleetOEE(organizationId?: string, hours: number = 24) {
  return useQuery<FleetOEE, Error>(
    [DASHBOARD_QUERY_KEY, 'fleet-oee', organizationId, hours],
    () => dashboardApi.getFleetOEE(organizationId, hours),
    {
      refetchInterval: 60000, // Refresh every minute
    }
  );
}

export function useAssetOEE(assetId: string, hours: number = 24) {
  return useQuery<OEEMetrics, Error>(
    [DASHBOARD_QUERY_KEY, 'asset-oee', assetId, hours],
    () => dashboardApi.getAssetOEE(assetId, hours),
    {
      enabled: !!assetId,
    }
  );
}
