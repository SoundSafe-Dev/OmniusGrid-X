import { api } from './client';
import {
  AgentRelease,
  AgentReleaseCreate,
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
} from '../types/fleet';

const BASE = '/api/v1/fleet';

export const fleetApi = {
  versions: async (): Promise<AgentVersionDistributionResponse> => {
    const response = await api.get<AgentVersionDistributionResponse>(`${BASE}/agents/versions`);
    return response.data;
  },

  releases: async (): Promise<AgentRelease[]> => {
    const response = await api.get<AgentRelease[]>(`${BASE}/releases`);
    return response.data;
  },

  createRelease: async (payload: AgentReleaseCreate): Promise<AgentRelease> => {
    const response = await api.post<AgentRelease>(`${BASE}/releases`, payload);
    return response.data;
  },

  publishRelease: async (releaseId: string): Promise<AgentRelease> => {
    const response = await api.post<AgentRelease>(`${BASE}/releases/${releaseId}/publish`);
    return response.data;
  },

  yankRelease: async (releaseId: string): Promise<AgentRelease> => {
    const response = await api.post<AgentRelease>(`${BASE}/releases/${releaseId}/yank`);
    return response.data;
  },

  rollouts: async (): Promise<AgentRollout[]> => {
    const response = await api.get<AgentRollout[]>(`${BASE}/rollouts`);
    return response.data;
  },

  rollout: async (rolloutId: string): Promise<AgentRollout> => {
    const response = await api.get<AgentRollout>(`${BASE}/rollouts/${rolloutId}`);
    return response.data;
  },

  createRollout: async (payload: AgentRolloutCreate): Promise<AgentRollout> => {
    const response = await api.post<AgentRollout>(`${BASE}/rollouts`, payload);
    return response.data;
  },

  pauseRollout: async (rolloutId: string): Promise<AgentRollout> => {
    const response = await api.post<AgentRollout>(`${BASE}/rollouts/${rolloutId}/pause`);
    return response.data;
  },

  cancelRollout: async (rolloutId: string): Promise<AgentRollout> => {
    const response = await api.post<AgentRollout>(`${BASE}/rollouts/${rolloutId}/cancel`);
    return response.data;
  },

  sites: async (): Promise<FleetSite[]> => {
    const response = await api.get<FleetSite[]>(`${BASE}/sites`);
    return response.data;
  },

  createSite: async (payload: FleetNamedCreate): Promise<FleetSite> => {
    const response = await api.post<FleetSite>(`${BASE}/sites`, payload);
    return response.data;
  },

  updateSite: async (
    siteId: string,
    payload: FleetNamedUpdate
  ): Promise<FleetSite> => {
    const response = await api.patch<FleetSite>(`${BASE}/sites/${siteId}`, payload);
    return response.data;
  },

  deactivateSite: async (siteId: string): Promise<FleetSite> => {
    const response = await api.delete<FleetSite>(`${BASE}/sites/${siteId}`);
    return response.data;
  },

  workcells: async (): Promise<FleetWorkcell[]> => {
    const response = await api.get<FleetWorkcell[]>(`${BASE}/workcells`);
    return response.data;
  },

  assignWorkcellSite: async (
    workcellId: string,
    siteId: string | null
  ): Promise<Pick<FleetWorkcell, 'id' | 'name' | 'site_id'>> => {
    const response = await api.patch<Pick<FleetWorkcell, 'id' | 'name' | 'site_id'>>(
      `${BASE}/workcells/${workcellId}/site`,
      { site_id: siteId }
    );
    return response.data;
  },

  tags: async (): Promise<FleetTag[]> => {
    const response = await api.get<FleetTag[]>(`${BASE}/tags`);
    return response.data;
  },

  createTag: async (payload: FleetTagCreate): Promise<FleetTag> => {
    const response = await api.post<FleetTag>(`${BASE}/tags`, payload);
    return response.data;
  },

  updateTag: async (
    tagId: string,
    payload: FleetTagUpdate
  ): Promise<FleetTag> => {
    const response = await api.patch<FleetTag>(`${BASE}/tags/${tagId}`, payload);
    return response.data;
  },

  deactivateTag: async (tagId: string): Promise<FleetTag> => {
    const response = await api.delete<FleetTag>(`${BASE}/tags/${tagId}`);
    return response.data;
  },

  assignTag: async (tagId: string, assetId: string): Promise<void> => {
    await api.put(`${BASE}/tags/${tagId}/assets/${assetId}`);
  },

  removeTag: async (tagId: string, assetId: string): Promise<void> => {
    await api.delete(`${BASE}/tags/${tagId}/assets/${assetId}`);
  },

  bulkTagAssignments: async (
    payload: FleetBulkTagAssignment
  ): Promise<FleetBulkTagAssignmentResponse> => {
    const response = await api.post<FleetBulkTagAssignmentResponse>(
      `${BASE}/tags/bulk-assignments`,
      payload
    );
    return response.data;
  },

  groups: async (): Promise<FleetGroup[]> => {
    const response = await api.get<FleetGroup[]>(`${BASE}/groups`);
    return response.data;
  },

  createGroup: async (payload: FleetNamedCreate): Promise<FleetGroup> => {
    const response = await api.post<FleetGroup>(`${BASE}/groups`, payload);
    return response.data;
  },

  updateGroup: async (
    groupId: string,
    payload: FleetNamedUpdate
  ): Promise<FleetGroup> => {
    const response = await api.patch<FleetGroup>(`${BASE}/groups/${groupId}`, payload);
    return response.data;
  },

  deactivateGroup: async (groupId: string): Promise<FleetGroup> => {
    const response = await api.delete<FleetGroup>(`${BASE}/groups/${groupId}`);
    return response.data;
  },

  updateGroupMembers: async (
    payload: FleetGroupMembershipRequest
  ): Promise<FleetGroupMembershipResponse> => {
    const results = await Promise.all(
      payload.asset_ids.map(async (assetId) => {
        if (payload.operation === 'add') {
          const response = await api.put<{ created: boolean }>(
            `${BASE}/groups/${payload.group_id}/assets/${assetId}`
          );
          return response.data.created;
        }
        const response = await api.delete<{ removed: boolean }>(
          `${BASE}/groups/${payload.group_id}/assets/${assetId}`
        );
        return response.data.removed;
      })
    );
    return {
      group_id: payload.group_id,
      operation: payload.operation,
      changed_count: results.filter(Boolean).length,
    };
  },

  cohorts: async (): Promise<FleetCohort[]> => {
    const response = await api.get<FleetCohort[]>(`${BASE}/cohorts`);
    return response.data;
  },

  cohort: async (cohortId: string): Promise<FleetCohort> => {
    const response = await api.get<FleetCohort>(`${BASE}/cohorts/${cohortId}`);
    return response.data;
  },

  createCohort: async (payload: FleetCohortCreate): Promise<FleetCohort> => {
    const response = await api.post<FleetCohort>(`${BASE}/cohorts`, payload);
    return response.data;
  },

  updateCohort: async (
    cohortId: string,
    payload: FleetCohortUpdate
  ): Promise<FleetCohort> => {
    const response = await api.patch<FleetCohort>(
      `${BASE}/cohorts/${cohortId}`,
      payload
    );
    return response.data;
  },

  deactivateCohort: async (cohortId: string): Promise<FleetCohort> => {
    const response = await api.delete<FleetCohort>(`${BASE}/cohorts/${cohortId}`);
    return response.data;
  },

  inventory: async (): Promise<FleetInventoryResponse> => {
    const response = await api.get<FleetInventoryResponse>(`${BASE}/inventory`);
    return response.data;
  },

  createTargetPreview: async (
    payload: FleetTargetPreviewCreate
  ): Promise<FleetTargetPreview> => {
    const response = await api.post<FleetTargetPreview>(
      `${BASE}/target-previews`,
      payload
    );
    return response.data;
  },

  targetPreview: async (previewId: string): Promise<FleetTargetPreview> => {
    const response = await api.get<FleetTargetPreview>(
      `${BASE}/target-previews/${previewId}`
    );
    return response.data;
  },
};
