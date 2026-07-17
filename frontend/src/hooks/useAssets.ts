import { useQuery, useMutation, useQueryClient, UseQueryOptions, keepPreviousData } from '@tanstack/react-query';
import { assetsApi, dashboardApi, workcellsApi, organizationsApi } from '../api';
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
  return useQuery<PaginatedResponse<Asset>, Error>({
    queryKey: [ASSETS_QUERY_KEY, 'list', params],
    queryFn: () => assetsApi.list(params),
    // FS-127: params (skip/limit) are part of the key; keep the previous page
    // rendered while the next one loads so paging doesn't blank the list.
    placeholderData: keepPreviousData,
    ...options,
  });
}

export function useAsset(assetId: string) {
  return useQuery<Asset, Error>({
    queryKey: [ASSETS_QUERY_KEY, 'detail', assetId],
    queryFn: () => assetsApi.get(assetId),
    enabled: !!assetId,
  });
}

export function useCreateAsset() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: AssetCreate) => assetsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ASSETS_QUERY_KEY] });
    },
  });
}

export function useUpdateAsset() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ assetId, data }: { assetId: string; data: AssetUpdate }) =>
      assetsApi.update(assetId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: [ASSETS_QUERY_KEY] });
      queryClient.invalidateQueries({ queryKey: [ASSETS_QUERY_KEY, 'detail', variables.assetId] });
    },
  });
}

export function useDeleteAsset() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (assetId: string) => assetsApi.delete(assetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ASSETS_QUERY_KEY] });
    },
  });
}

export function useAssetTypes(category?: string) {
  return useQuery<AssetType[], Error>({
    queryKey: [ASSETS_QUERY_KEY, 'types', category],
    queryFn: () => assetsApi.getTypes(category),
  });
}

export function useWorkcells(organizationId?: string) {
  return useQuery<Workcell[], Error>({
    queryKey: [ASSETS_QUERY_KEY, 'workcells', organizationId],
    queryFn: () => workcellsApi.list(organizationId),
  });
}

export function useOrganizations() {
  return useQuery<Organization[], Error>({
    queryKey: [ASSETS_QUERY_KEY, 'organizations'],
    queryFn: () => organizationsApi.list(),
  });
}

// Dashboard
export function useDashboardOverview(organizationId?: string) {
  return useQuery<DashboardOverview, Error>({
    queryKey: [DASHBOARD_QUERY_KEY, 'overview', organizationId],
    queryFn: () => dashboardApi.getOverview(organizationId),
    refetchInterval: 30000, // Refresh every 30 seconds
  });
}

export function useFleetOEE(organizationId?: string, hours: number = 24) {
  return useQuery<FleetOEE, Error>({
    queryKey: [DASHBOARD_QUERY_KEY, 'fleet-oee', organizationId, hours],
    queryFn: () => dashboardApi.getFleetOEE(organizationId, hours),
    refetchInterval: 60000, // Refresh every minute
  });
}

export function useAssetOEE(assetId: string, hours: number = 24) {
  return useQuery<OEEMetrics, Error>({
    queryKey: [DASHBOARD_QUERY_KEY, 'asset-oee', assetId, hours],
    queryFn: () => dashboardApi.getAssetOEE(assetId, hours),
    enabled: !!assetId,
  });
}
