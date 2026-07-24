import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { fleetApi } from '../api/fleet';
import {
  AgentRelease,
  AgentReleaseCreate,
  AgentRemoteOperationCommand,
  AgentRemoteOperationSubmission,
  AgentRollout,
  AgentRolloutCreate,
  AgentVersionDistributionResponse,
  FleetBulkTagAssignment,
  FleetBulkTagAssignmentResponse,
  FleetCohort,
  FleetCohortCreate,
  FleetCohortUpdate,
  FleetGroup,
  FleetGroupMembershipRequest,
  FleetGroupMembershipResponse,
  FleetInventoryResponse,
  FleetNamedCreate,
  FleetNamedUpdate,
  FleetSite,
  FleetTag,
  FleetTagCreate,
  FleetTagUpdate,
  FleetTargetPreview,
  FleetTargetPreviewCreate,
  FleetWorkcell,
  MaintenanceWindow,
  MaintenanceWindowCreate,
  MaintenanceWindowPreview,
  MaintenanceWindowPreviewRequest,
  MaintenanceWindowUpdate,
  SubmitAgentRemoteOperation,
} from '../types/fleet';

const FLEET_KEY = 'fleetOta';
const TARGETING_KEY = [FLEET_KEY, 'targeting'];
const MAINTENANCE_KEY = [FLEET_KEY, 'maintenance'];
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

export function useResumeAgentRollout() {
  const queryClient = useQueryClient();
  return useMutation<AgentRollout, Error, string>(
    fleetApi.resumeRollout,
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
  return useMutation<AgentRollout, Error, string>({
    mutationFn: fleetApi.cancelRollout,
    onSuccess: (data) => {
      queryClient.setQueryData([FLEET_KEY, 'rollout', data.id], data);
      queryClient.invalidateQueries({ queryKey: [FLEET_KEY, 'rollouts'] });
    },
  });
}

export function useFleetSites() {
  return useQuery<FleetSite[], Error>(
    [...TARGETING_KEY, 'sites'],
    fleetApi.sites,
    { keepPreviousData: true }
  );
}

export function useCreateFleetSite() {
  const queryClient = useQueryClient();
  return useMutation<FleetSite, Error, FleetNamedCreate>(
    fleetApi.createSite,
    {
      onSuccess: () => queryClient.invalidateQueries(TARGETING_KEY),
    }
  );
}

export function useUpdateFleetSite() {
  const queryClient = useQueryClient();
  return useMutation<
    FleetSite,
    Error,
    { siteId: string; payload: FleetNamedUpdate }
  >(
    ({ siteId, payload }) => fleetApi.updateSite(siteId, payload),
    {
      onSuccess: () => queryClient.invalidateQueries(TARGETING_KEY),
    }
  );
}

export function useDeactivateFleetSite() {
  const queryClient = useQueryClient();
  return useMutation<FleetSite, Error, string>(
    fleetApi.deactivateSite,
    {
      onSuccess: () => queryClient.invalidateQueries(TARGETING_KEY),
    }
  );
}

export function useMaintenanceWindows() {
  return useQuery<MaintenanceWindow[], Error>(
    MAINTENANCE_KEY,
    fleetApi.maintenanceWindows,
    { keepPreviousData: true }
  );
}

export function useCreateMaintenanceWindow() {
  const queryClient = useQueryClient();
  return useMutation<MaintenanceWindow, Error, MaintenanceWindowCreate>(
    fleetApi.createMaintenanceWindow,
    {
      onSuccess: () => queryClient.invalidateQueries(MAINTENANCE_KEY),
    }
  );
}

export function useUpdateMaintenanceWindow() {
  const queryClient = useQueryClient();
  return useMutation<
    MaintenanceWindow,
    Error,
    { windowId: string; payload: MaintenanceWindowUpdate }
  >(
    ({ windowId, payload }) =>
      fleetApi.updateMaintenanceWindow(windowId, payload),
    {
      onSuccess: () => queryClient.invalidateQueries(MAINTENANCE_KEY),
    }
  );
}

export function useDisableMaintenanceWindow() {
  const queryClient = useQueryClient();
  return useMutation<MaintenanceWindow, Error, string>(
    fleetApi.disableMaintenanceWindow,
    {
      onSuccess: () => queryClient.invalidateQueries(MAINTENANCE_KEY),
    }
  );
}

export function usePreviewMaintenanceWindows() {
  return useMutation<
    MaintenanceWindowPreview,
    Error,
    MaintenanceWindowPreviewRequest
  >(fleetApi.previewMaintenanceWindows);
}

export function useFleetWorkcells() {
  return useQuery<FleetWorkcell[], Error>(
    [...TARGETING_KEY, 'workcells'],
    fleetApi.workcells,
    { keepPreviousData: true }
  );
}

export function useAssignFleetWorkcellSite() {
  const queryClient = useQueryClient();
  return useMutation<
    Pick<FleetWorkcell, 'id' | 'name' | 'site_id'>,
    Error,
    { workcellId: string; siteId: string | null }
  >(
    ({ workcellId, siteId }) => fleetApi.assignWorkcellSite(workcellId, siteId),
    {
      onSuccess: () => queryClient.invalidateQueries(TARGETING_KEY),
    }
  );
}

export function useFleetTags() {
  return useQuery<FleetTag[], Error>(
    [...TARGETING_KEY, 'tags'],
    fleetApi.tags,
    { keepPreviousData: true }
  );
}

export function useCreateFleetTag() {
  const queryClient = useQueryClient();
  return useMutation<FleetTag, Error, FleetTagCreate>(
    fleetApi.createTag,
    {
      onSuccess: () => queryClient.invalidateQueries(TARGETING_KEY),
    }
  );
}

export function useUpdateFleetTag() {
  const queryClient = useQueryClient();
  return useMutation<
    FleetTag,
    Error,
    { tagId: string; payload: FleetTagUpdate }
  >(
    ({ tagId, payload }) => fleetApi.updateTag(tagId, payload),
    {
      onSuccess: () => queryClient.invalidateQueries(TARGETING_KEY),
    }
  );
}

export function useDeactivateFleetTag() {
  const queryClient = useQueryClient();
  return useMutation<FleetTag, Error, string>(
    fleetApi.deactivateTag,
    {
      onSuccess: () => queryClient.invalidateQueries(TARGETING_KEY),
    }
  );
}

export function useBulkFleetTagAssignments() {
  const queryClient = useQueryClient();
  return useMutation<
    FleetBulkTagAssignmentResponse,
    Error,
    FleetBulkTagAssignment
  >(
    fleetApi.bulkTagAssignments,
    {
      onSuccess: () => queryClient.invalidateQueries(TARGETING_KEY),
    }
  );
}

export function useFleetGroups() {
  return useQuery<FleetGroup[], Error>(
    [...TARGETING_KEY, 'groups'],
    fleetApi.groups,
    { keepPreviousData: true }
  );
}

export function useCreateFleetGroup() {
  const queryClient = useQueryClient();
  return useMutation<FleetGroup, Error, FleetNamedCreate>(
    fleetApi.createGroup,
    {
      onSuccess: () => queryClient.invalidateQueries(TARGETING_KEY),
    }
  );
}

export function useUpdateFleetGroup() {
  const queryClient = useQueryClient();
  return useMutation<
    FleetGroup,
    Error,
    { groupId: string; payload: FleetNamedUpdate }
  >(
    ({ groupId, payload }) => fleetApi.updateGroup(groupId, payload),
    {
      onSuccess: () => queryClient.invalidateQueries(TARGETING_KEY),
    }
  );
}

export function useDeactivateFleetGroup() {
  const queryClient = useQueryClient();
  return useMutation<FleetGroup, Error, string>(
    fleetApi.deactivateGroup,
    {
      onSuccess: () => queryClient.invalidateQueries(TARGETING_KEY),
    }
  );
}

export function useUpdateFleetGroupMembers() {
  const queryClient = useQueryClient();
  return useMutation<
    FleetGroupMembershipResponse,
    Error,
    FleetGroupMembershipRequest
  >(
    fleetApi.updateGroupMembers,
    {
      // Individual membership routes may partially succeed before one request
      // fails, so always refresh inventory after the batch settles.
      onSettled: () => queryClient.invalidateQueries(TARGETING_KEY),
    }
  );
}

export function useFleetCohorts() {
  return useQuery<FleetCohort[], Error>(
    [...TARGETING_KEY, 'cohorts'],
    fleetApi.cohorts,
    { keepPreviousData: true }
  );
}

export function useFleetCohort(cohortId: string) {
  return useQuery<FleetCohort, Error>(
    [...TARGETING_KEY, 'cohort', cohortId],
    () => fleetApi.cohort(cohortId),
    { enabled: Boolean(cohortId) }
  );
}

export function useCreateFleetCohort() {
  const queryClient = useQueryClient();
  return useMutation<FleetCohort, Error, FleetCohortCreate>(
    fleetApi.createCohort,
    {
      onSuccess: () => queryClient.invalidateQueries(TARGETING_KEY),
    }
  );
}

export function useUpdateFleetCohort() {
  const queryClient = useQueryClient();
  return useMutation<
    FleetCohort,
    Error,
    { cohortId: string; payload: FleetCohortUpdate }
  >(
    ({ cohortId, payload }) => fleetApi.updateCohort(cohortId, payload),
    {
      onSuccess: () => queryClient.invalidateQueries(TARGETING_KEY),
    }
  );
}

export function useDeactivateFleetCohort() {
  const queryClient = useQueryClient();
  return useMutation<FleetCohort, Error, string>(
    fleetApi.deactivateCohort,
    {
      onSuccess: () => queryClient.invalidateQueries(TARGETING_KEY),
    }
  );
}

export function useFleetInventory() {
  return useQuery<FleetInventoryResponse, Error>(
    [...TARGETING_KEY, 'inventory'],
    fleetApi.inventory,
    { keepPreviousData: true }
  );
}

export function useSubmitAgentRemoteOperation() {
  return useMutation<
    AgentRemoteOperationSubmission,
    Error,
    SubmitAgentRemoteOperation
  >(fleetApi.submitRemoteOperation);
}

export function useAgentRemoteOperation(
  assetId: string,
  commandId: string
) {
  return useQuery<AgentRemoteOperationCommand, Error>(
    [FLEET_KEY, 'remote-operation', assetId, commandId],
    () => fleetApi.remoteOperationStatus(assetId, commandId),
    {
      enabled: Boolean(assetId && commandId),
      refetchInterval: (data) =>
        data &&
        ['completed', 'failed', 'cancelled', 'timeout'].includes(data.status)
          ? false
          : 1_500,
    }
  );
}

export function useCreateFleetTargetPreview() {
  return useMutation<FleetTargetPreview, Error, FleetTargetPreviewCreate>(
    fleetApi.createTargetPreview
  );
}

export function useFleetTargetPreview(previewId: string) {
  return useQuery<FleetTargetPreview, Error>(
    [...TARGETING_KEY, 'preview', previewId],
    () => fleetApi.targetPreview(previewId),
    { enabled: Boolean(previewId) }
  );
}
