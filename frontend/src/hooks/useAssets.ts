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

// No organizationId argument: the server derives the organisation from the JWT, and the
// query parameter this used to forward was silently discarded (GET /api/v1/workcells/
// declares only skip and limit). Keeping the argument would have implied a filter that
// never existed, and put a value into the query key that could not affect the result.
export function useWorkcells() {
  return useQuery<Workcell[], Error>({
    queryKey: [ASSETS_QUERY_KEY, 'workcells'],
    queryFn: () => workcellsApi.list(),
  });
}

export function useOrganizations() {
  return useQuery<Organization[], Error>({
    queryKey: [ASSETS_QUERY_KEY, 'organizations'],
    queryFn: () => organizationsApi.list(),
  });
}

// Dashboard — the organization always comes from the authenticated user
// server-side, so there is no org argument to thread through.
export function useDashboardOverview() {
  return useQuery<DashboardOverview, Error>({
    queryKey: [DASHBOARD_QUERY_KEY, 'overview'],
    queryFn: () => dashboardApi.getOverview(),
    refetchInterval: 30000, // Refresh every 30 seconds
  });
}

export function useFleetOEE(hours: number = 24) {
  return useQuery<FleetOEE, Error>({
    queryKey: [DASHBOARD_QUERY_KEY, 'fleet-oee', hours],
    queryFn: () => dashboardApi.getFleetOEE(hours),
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
