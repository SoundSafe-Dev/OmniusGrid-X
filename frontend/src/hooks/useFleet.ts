import { useMutation, useQuery, useQueryClient } from 'react-query';
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
  return useQuery<AgentVersionDistributionResponse, Error>(
    [FLEET_KEY, 'versions'],
    fleetApi.versions,
    {
      refetchInterval: REFRESH_MS,
      keepPreviousData: true,
    }
  );
}

export function useAgentReleases() {
  return useQuery<AgentRelease[], Error>(
    [FLEET_KEY, 'releases'],
    fleetApi.releases,
    {
      refetchInterval: REFRESH_MS,
      keepPreviousData: true,
    }
  );
}

export function useAgentRollouts() {
  return useQuery<AgentRollout[], Error>(
    [FLEET_KEY, 'rollouts'],
    fleetApi.rollouts,
    {
      refetchInterval: REFRESH_MS,
      keepPreviousData: true,
    }
  );
}

export function useAgentRollout(rolloutId: string) {
  return useQuery<AgentRollout, Error>(
    [FLEET_KEY, 'rollout', rolloutId],
    () => fleetApi.rollout(rolloutId),
    {
      enabled: Boolean(rolloutId),
      refetchInterval: REFRESH_MS,
    }
  );
}

export function useCreateAgentRelease() {
  const queryClient = useQueryClient();
  return useMutation<AgentRelease, Error, AgentReleaseCreate>(
    fleetApi.createRelease,
    {
      onSuccess: () => queryClient.invalidateQueries([FLEET_KEY, 'releases']),
    }
  );
}

export function usePublishAgentRelease() {
  const queryClient = useQueryClient();
  return useMutation<AgentRelease, Error, string>(
    fleetApi.publishRelease,
    {
      onSuccess: () => queryClient.invalidateQueries([FLEET_KEY, 'releases']),
    }
  );
}

export function useYankAgentRelease() {
  const queryClient = useQueryClient();
  return useMutation<AgentRelease, Error, string>(
    fleetApi.yankRelease,
    {
      onSuccess: () => queryClient.invalidateQueries([FLEET_KEY, 'releases']),
    }
  );
}

export function useCreateAgentRollout() {
  const queryClient = useQueryClient();
  return useMutation<AgentRollout, Error, AgentRolloutCreate>(
    fleetApi.createRollout,
    {
      onSuccess: () => queryClient.invalidateQueries([FLEET_KEY, 'rollouts']),
    }
  );
}

export function usePauseAgentRollout() {
  const queryClient = useQueryClient();
  return useMutation<AgentRollout, Error, string>(
    fleetApi.pauseRollout,
    {
      onSuccess: (data) => {
        queryClient.setQueryData([FLEET_KEY, 'rollout', data.id], data);
        queryClient.invalidateQueries([FLEET_KEY, 'rollouts']);
      },
    }
  );
}

export function useCancelAgentRollout() {
  const queryClient = useQueryClient();
  return useMutation<AgentRollout, Error, string>(
    fleetApi.cancelRollout,
    {
      onSuccess: (data) => {
        queryClient.setQueryData([FLEET_KEY, 'rollout', data.id], data);
        queryClient.invalidateQueries([FLEET_KEY, 'rollouts']);
      },
    }
  );
}
