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

/**
 * Get current user's context and goals
 */
export async function getUserContext(): Promise<UserContext> {
  if (USE_MOCK) {
    const { mockUserContext } = await import('./mocks/nlpMocks');
    return mockUserContext;
  }
  const response = await api.get<UserContext>('/api/v1/user/context');
  return response.data;
}

/**
 * Update user context (department and priorities)
 */
export async function updateUserContext(request: UpdateUserContextRequest): Promise<UserContext> {
  const response = await api.put<UserContext>('/api/v1/user/context', request);
  return response.data;
}

/**
 * Add a new goal to the user's goals
 */
export async function addUserGoal(request: UserGoalRequest): Promise<UserContext> {
  const response = await api.post<UserContext>('/api/v1/user/goals', request);
  return response.data;
}

/**
 * Update an existing user goal
 */
export async function updateGoal(goalId: string, request: UserGoalRequest): Promise<UserContext> {
  const response = await api.put<UserContext>(`/api/v1/user/goals/${goalId}`, request);
  return response.data;
}

/**
 * Delete a user goal
 */
export async function deleteGoal(goalId: string): Promise<UserContext> {
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
