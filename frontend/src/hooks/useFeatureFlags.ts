import { useQuery, useMutation, useQueryClient, UseQueryOptions } from '@tanstack/react-query';
import { featureFlagsApi, FeatureFlag, FeatureFlagCreate, FeatureFlagUpdate } from '../api/featureFlags';

const FEATURE_FLAGS_QUERY_KEY = 'featureFlags';

type FlagMap = Record<string, boolean>;

/**
 * Resolve the current user's feature flags. Returns the raw flag map plus an
 * isEnabled(key) helper that fails closed (false) while loading or on error, so
 * a flag never appears on unless the backend explicitly says so.
 */
export function useFeatureFlags(options?: UseQueryOptions<FlagMap, Error>) {
  const query = useQuery<FlagMap, Error>({
    queryKey: [FEATURE_FLAGS_QUERY_KEY, 'evaluate'],
    queryFn: () => featureFlagsApi.evaluate(),
    staleTime: 60_000,
    ...options,
  });

  const flags = query.data ?? {};
  const isEnabled = (key: string): boolean => flags[key] === true;

  return { ...query, flags, isEnabled };
}

/** Convenience hook for a single flag. */
export function useFeatureFlag(key: string): boolean {
  const { isEnabled } = useFeatureFlags();
  return isEnabled(key);
}

// --- Admin management hooks --------------------------------------------------
const ADMIN_QUERY_KEY = [FEATURE_FLAGS_QUERY_KEY, 'admin'];

export function useFeatureFlagList(options?: UseQueryOptions<FeatureFlag[], Error>) {
  return useQuery<FeatureFlag[], Error>({
    queryKey: ADMIN_QUERY_KEY,
    queryFn: () => featureFlagsApi.list(),
    ...options,
  });
}

export function useCreateFeatureFlag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: FeatureFlagCreate) => featureFlagsApi.create(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [FEATURE_FLAGS_QUERY_KEY] });
    },
  });
}

export function useUpdateFeatureFlag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ key, payload }: { key: string; payload: FeatureFlagUpdate }) =>
      featureFlagsApi.update(key, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [FEATURE_FLAGS_QUERY_KEY] });
    },
  });
}

export function useDeleteFeatureFlag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => featureFlagsApi.remove(key),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [FEATURE_FLAGS_QUERY_KEY] });
    },
  });
}
