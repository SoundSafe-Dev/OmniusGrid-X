/**
 * User Context API Client
 *
 * API client for managing user context, priorities, and goals.
 */

import { api } from './client';
import { USE_MOCK } from './mockMode';

// ==================== Types ====================

export interface UserContext {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  department: string | null;
  priorities: string[];
  user_context: Record<string, any>;
  user_goals: UserGoal[];
}

export interface UserGoal {
  id: string;
  title: string;
  progress: number;
  deadline: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface UpdateUserContextRequest {
  department?: string;
  priorities?: string[];
}

export interface UserGoalRequest {
  title: string;
  progress: number;
  deadline?: string;
}

// ==================== API Functions ====================

/** The demo's working copy (FS-488).
 *
 *  Only the READ was mocked here. The four writers below went straight to the API in every
 *  mode, so in the demo `ContextManagementModal` showed a fixture, accepted edits, and
 *  failed on Save against a backend that is not there. FS-478 made that failure visible,
 *  which turned a silent oddity into a visible broken button.
 *
 *  Every other client in this codebase mocks its writes — `erp.createIntegration`,
 *  `notifications.createSubscription`, `kanbanStore.moveTask` — so this is the convention
 *  rather than a new one. A mode that mocks half a surface is a double for the half nobody
 *  was testing.
 */
let mockContext: UserContext | null = null;

async function demoContext(): Promise<UserContext> {
  if (!mockContext) {
    const { mockUserContext } = await import('./mocks/nlpMocks');
    mockContext = { ...mockUserContext, user_goals: [...mockUserContext.user_goals] };
  }
  return mockContext;
}

/**
 * Get current user's context and goals
 */
export async function getUserContext(): Promise<UserContext> {
  if (USE_MOCK) {
    return demoContext();
  }
  const response = await api.get<UserContext>('/api/v1/user/context');
  return response.data;
}

/**
 * Update user context (department and priorities)
 */
export async function updateUserContext(request: UpdateUserContextRequest): Promise<UserContext> {
  if (USE_MOCK) {
    const context = await demoContext();
    mockContext = { ...context, ...request };
    return mockContext;
  }
  const response = await api.put<UserContext>('/api/v1/user/context', request);
  return response.data;
}

/**
 * Add a new goal to the user's goals
 */
export async function addUserGoal(request: UserGoalRequest): Promise<UserContext> {
  if (USE_MOCK) {
    const context = await demoContext();
    mockContext = {
      ...context,
      user_goals: [
        ...context.user_goals,
        {
          id: `goal-${context.user_goals.length + 1}`,
          title: request.title,
          progress: request.progress,
          deadline: request.deadline ?? null,
        },
      ],
    };
    return mockContext;
  }
  const response = await api.post<UserContext>('/api/v1/user/goals', request);
  return response.data;
}

/**
 * Update an existing user goal
 */
export async function updateGoal(goalId: string, request: UserGoalRequest): Promise<UserContext> {
  if (USE_MOCK) {
    const context = await demoContext();
    mockContext = {
      ...context,
      user_goals: context.user_goals.map((g) => (g.id === goalId ? { ...g, ...request } : g)),
    };
    return mockContext;
  }
  const response = await api.put<UserContext>(`/api/v1/user/goals/${goalId}`, request);
  return response.data;
}

/**
 * Delete a user goal
 */
export async function deleteGoal(goalId: string): Promise<UserContext> {
  if (USE_MOCK) {
    const context = await demoContext();
    mockContext = { ...context, user_goals: context.user_goals.filter((g) => g.id !== goalId) };
    return mockContext;
  }
  const response = await api.delete<UserContext>(`/api/v1/user/goals/${goalId}`);
  return response.data;
}

// Export as a single object for convenience
export const userContextApi = {
  getUserContext,
  updateUserContext,
  addUserGoal,
  updateGoal,
  deleteGoal,
};
