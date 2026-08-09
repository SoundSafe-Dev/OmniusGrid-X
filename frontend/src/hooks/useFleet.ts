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
  return useMutation<AgentRollout, Error, string>({
    mutationFn: fleetApi.resumeRollout,
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

export function useFleetSites() {
  return useQuery<FleetSite[], Error>({
    queryKey: [...TARGETING_KEY, 'sites'],
    queryFn: fleetApi.sites,
    placeholderData: keepPreviousData,
  });
}

export function useCreateFleetSite() {
  const queryClient = useQueryClient();
  return useMutation<FleetSite, Error, FleetNamedCreate>({
    mutationFn: fleetApi.createSite,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TARGETING_KEY }),
  });
}

export function useUpdateFleetSite() {
  const queryClient = useQueryClient();
  return useMutation<
    FleetSite,
    Error,
    { siteId: string; payload: FleetNamedUpdate }
  >({
    mutationFn: ({ siteId, payload }) => fleetApi.updateSite(siteId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TARGETING_KEY }),
  });
}

export function useDeactivateFleetSite() {
  const queryClient = useQueryClient();
  return useMutation<FleetSite, Error, string>({
    mutationFn: fleetApi.deactivateSite,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TARGETING_KEY }),
  });
}

export function useMaintenanceWindows() {
  return useQuery<MaintenanceWindow[], Error>({
    queryKey: MAINTENANCE_KEY,
    queryFn: fleetApi.maintenanceWindows,
    placeholderData: keepPreviousData,
  });
}

export function useCreateMaintenanceWindow() {
  const queryClient = useQueryClient();
  return useMutation<MaintenanceWindow, Error, MaintenanceWindowCreate>({
    mutationFn: fleetApi.createMaintenanceWindow,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: MAINTENANCE_KEY }),
  });
}

export function useUpdateMaintenanceWindow() {
  const queryClient = useQueryClient();
  return useMutation<
    MaintenanceWindow,
    Error,
    { windowId: string; payload: MaintenanceWindowUpdate }
  >({
    mutationFn: ({ windowId, payload }) =>
      fleetApi.updateMaintenanceWindow(windowId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: MAINTENANCE_KEY }),
  });
}

export function useDisableMaintenanceWindow() {
  const queryClient = useQueryClient();
  return useMutation<MaintenanceWindow, Error, string>({
    mutationFn: fleetApi.disableMaintenanceWindow,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: MAINTENANCE_KEY }),
  });
}

export function usePreviewMaintenanceWindows() {
  return useMutation<
    MaintenanceWindowPreview,
    Error,
    MaintenanceWindowPreviewRequest
  >({
    mutationFn: fleetApi.previewMaintenanceWindows,
  });
}

export function useFleetWorkcells() {
  return useQuery<FleetWorkcell[], Error>({
    queryKey: [...TARGETING_KEY, 'workcells'],
    queryFn: fleetApi.workcells,
    placeholderData: keepPreviousData,
  });
}

export function useAssignFleetWorkcellSite() {
  const queryClient = useQueryClient();
  return useMutation<
    Pick<FleetWorkcell, 'id' | 'name' | 'site_id'>,
    Error,
    { workcellId: string; siteId: string | null }
  >({
    mutationFn: ({ workcellId, siteId }) =>
      fleetApi.assignWorkcellSite(workcellId, siteId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TARGETING_KEY }),
  });
}

export function useFleetTags() {
  return useQuery<FleetTag[], Error>({
    queryKey: [...TARGETING_KEY, 'tags'],
    queryFn: fleetApi.tags,
    placeholderData: keepPreviousData,
  });
}

export function useCreateFleetTag() {
  const queryClient = useQueryClient();
  return useMutation<FleetTag, Error, FleetTagCreate>({
    mutationFn: fleetApi.createTag,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TARGETING_KEY }),
  });
}

export function useUpdateFleetTag() {
  const queryClient = useQueryClient();
  return useMutation<
    FleetTag,
    Error,
    { tagId: string; payload: FleetTagUpdate }
  >({
    mutationFn: ({ tagId, payload }) => fleetApi.updateTag(tagId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TARGETING_KEY }),
  });
}

export function useDeactivateFleetTag() {
  const queryClient = useQueryClient();
  return useMutation<FleetTag, Error, string>({
    mutationFn: fleetApi.deactivateTag,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TARGETING_KEY }),
  });
}

export function useBulkFleetTagAssignments() {
  const queryClient = useQueryClient();
  return useMutation<
    FleetBulkTagAssignmentResponse,
    Error,
    FleetBulkTagAssignment
  >({
    mutationFn: fleetApi.bulkTagAssignments,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TARGETING_KEY }),
  });
}

export function useFleetGroups() {
  return useQuery<FleetGroup[], Error>({
    queryKey: [...TARGETING_KEY, 'groups'],
    queryFn: fleetApi.groups,
    placeholderData: keepPreviousData,
  });
}

export function useCreateFleetGroup() {
  const queryClient = useQueryClient();
  return useMutation<FleetGroup, Error, FleetNamedCreate>({
    mutationFn: fleetApi.createGroup,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TARGETING_KEY }),
  });
}

export function useUpdateFleetGroup() {
  const queryClient = useQueryClient();
  return useMutation<
    FleetGroup,
    Error,
    { groupId: string; payload: FleetNamedUpdate }
  >({
    mutationFn: ({ groupId, payload }) => fleetApi.updateGroup(groupId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TARGETING_KEY }),
  });
}

export function useDeactivateFleetGroup() {
  const queryClient = useQueryClient();
  return useMutation<FleetGroup, Error, string>({
    mutationFn: fleetApi.deactivateGroup,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TARGETING_KEY }),
  });
}

export function useUpdateFleetGroupMembers() {
  const queryClient = useQueryClient();
  return useMutation<
    FleetGroupMembershipResponse,
    Error,
    FleetGroupMembershipRequest
  >({
    mutationFn: fleetApi.updateGroupMembers,
    // Individual membership routes may partially succeed before one request
    // fails, so always refresh inventory after the batch settles.
    onSettled: () => queryClient.invalidateQueries({ queryKey: TARGETING_KEY }),
  });
}

export function useFleetCohorts() {
  return useQuery<FleetCohort[], Error>({
    queryKey: [...TARGETING_KEY, 'cohorts'],
    queryFn: fleetApi.cohorts,
    placeholderData: keepPreviousData,
  });
}

export function useFleetCohort(cohortId: string) {
  return useQuery<FleetCohort, Error>({
    queryKey: [...TARGETING_KEY, 'cohort', cohortId],
    queryFn: () => fleetApi.cohort(cohortId),
    enabled: Boolean(cohortId),
  });
}

export function useCreateFleetCohort() {
  const queryClient = useQueryClient();
  return useMutation<FleetCohort, Error, FleetCohortCreate>({
    mutationFn: fleetApi.createCohort,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TARGETING_KEY }),
  });
}

export function useUpdateFleetCohort() {
  const queryClient = useQueryClient();
  return useMutation<
    FleetCohort,
    Error,
    { cohortId: string; payload: FleetCohortUpdate }
  >({
    mutationFn: ({ cohortId, payload }) =>
      fleetApi.updateCohort(cohortId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TARGETING_KEY }),
  });
}

export function useDeactivateFleetCohort() {
  const queryClient = useQueryClient();
  return useMutation<FleetCohort, Error, string>({
    mutationFn: fleetApi.deactivateCohort,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TARGETING_KEY }),
  });
}

export function useFleetInventory() {
  return useQuery<FleetInventoryResponse, Error>({
    queryKey: [...TARGETING_KEY, 'inventory'],
    queryFn: fleetApi.inventory,
    placeholderData: keepPreviousData,
  });
}

export function useSubmitAgentRemoteOperation() {
  return useMutation<
    AgentRemoteOperationSubmission,
    Error,
    SubmitAgentRemoteOperation
  >({
    mutationFn: fleetApi.submitRemoteOperation,
  });
}

export function useAgentRemoteOperation(
  assetId: string,
  commandId: string
) {
  return useQuery<AgentRemoteOperationCommand, Error>({
    queryKey: [FLEET_KEY, 'remote-operation', assetId, commandId],
    queryFn: () => fleetApi.remoteOperationStatus(assetId, commandId),
    enabled: Boolean(assetId && commandId),
    refetchInterval: (query) => {
      const data = query.state.data;
      return data &&
        ['completed', 'failed', 'cancelled', 'timeout'].includes(data.status)
        ? false
        : 1_500;
    },
  });
}

export function useCreateFleetTargetPreview() {
  return useMutation<FleetTargetPreview, Error, FleetTargetPreviewCreate>({
    mutationFn: fleetApi.createTargetPreview,
  });
}

export function useFleetTargetPreview(previewId: string) {
  return useQuery<FleetTargetPreview, Error>({
    queryKey: [...TARGETING_KEY, 'preview', previewId],
    queryFn: () => fleetApi.targetPreview(previewId),
    enabled: Boolean(previewId),
  });
}
