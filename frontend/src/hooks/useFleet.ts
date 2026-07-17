import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { fleetApi } from '../api/fleet';
import {
  AgentRelease,
  AgentReleaseCreate,
  AgentRollout,
  AgentRolloutCreate,
  AgentVersionDistributionResponse,
} from '../types/fleet';

const FLEET_KEY = 'fleetOta';
const REFRESH_MS = 30_000;

export function useAgentVersions() {
  return useQuery<AgentVersionDistributionResponse, Error>({
    queryKey: [FLEET_KEY, 'versions'],
    queryFn: fleetApi.versions,
    refetchInterval: REFRESH_MS,
    placeholderData: keepPreviousData,
  });
}

export function useAgentReleases() {
  return useQuery<AgentRelease[], Error>({
    queryKey: [FLEET_KEY, 'releases'],
    queryFn: fleetApi.releases,
    refetchInterval: REFRESH_MS,
    placeholderData: keepPreviousData,
  });
}

export function useAgentRollouts() {
  return useQuery<AgentRollout[], Error>({
    queryKey: [FLEET_KEY, 'rollouts'],
    queryFn: fleetApi.rollouts,
    refetchInterval: REFRESH_MS,
    placeholderData: keepPreviousData,
  });
}

export function useAgentRollout(rolloutId: string) {
  return useQuery<AgentRollout, Error>({
    queryKey: [FLEET_KEY, 'rollout', rolloutId],
    queryFn: () => fleetApi.rollout(rolloutId),
    enabled: Boolean(rolloutId),
    refetchInterval: REFRESH_MS,
  });
}

export function useCreateAgentRelease() {
  const queryClient = useQueryClient();
  return useMutation<AgentRelease, Error, AgentReleaseCreate>({
    mutationFn: fleetApi.createRelease,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [FLEET_KEY, 'releases'] }),
  });
}

export function usePublishAgentRelease() {
  const queryClient = useQueryClient();
  return useMutation<AgentRelease, Error, string>({
    mutationFn: fleetApi.publishRelease,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [FLEET_KEY, 'releases'] }),
  });
}

export function useYankAgentRelease() {
  const queryClient = useQueryClient();
  return useMutation<AgentRelease, Error, string>({
    mutationFn: fleetApi.yankRelease,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [FLEET_KEY, 'releases'] }),
  });
}

export function useCreateAgentRollout() {
  const queryClient = useQueryClient();
  return useMutation<AgentRollout, Error, AgentRolloutCreate>({
    mutationFn: fleetApi.createRollout,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [FLEET_KEY, 'rollouts'] }),
  });
}

export function usePauseAgentRollout() {
  const queryClient = useQueryClient();
  return useMutation<AgentRollout, Error, string>({
    mutationFn: fleetApi.pauseRollout,
    onSuccess: (data) => {
      queryClient.setQueryData([FLEET_KEY, 'rollout', data.id], data);
      queryClient.invalidateQueries({ queryKey: [FLEET_KEY, 'rollouts'] });
    },
  });
}

export function useCancelAgentRollout() {
  const queryClient = useQueryClient();
  return useMutation<AgentRollout, Error, string>({
    mutationFn: fleetApi.cancelRollout,
    onSuccess: (data) => {
      queryClient.setQueryData([FLEET_KEY, 'rollout', data.id], data);
      queryClient.invalidateQueries({ queryKey: [FLEET_KEY, 'rollouts'] });
    },
  });
}
