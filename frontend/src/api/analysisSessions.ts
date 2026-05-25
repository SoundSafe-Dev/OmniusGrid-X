/**
 * Analysis Sessions API Client
 *
 * API client for managing analysis sessions, data sources, and session-based chat.
 */

import { api } from './client';

// ==================== Types ====================

export interface AnalysisSession {
  id: string;
  user_id: string;
  organization_id: string;
  title: string;
  description: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  last_accessed_at: string;
  context_snapshot: Record<string, any>;
  goals_snapshot: Record<string, any>;
  data_sources_count: number;
  messages_count: number;
}

export interface CreateSessionRequest {
  title?: string;
  description?: string;
}

export interface UpdateSessionRequest {
  title?: string;
  description?: string;
}

export interface SessionListResponse {
  sessions: AnalysisSession[];
  total: number;
}

export interface DataSource {
  id: string;
  session_id: string;
  source_type: string;
  source_id: string | null;
  file_name: string | null;
  data_type: string | null;
  added_at: string;
}

export interface SessionChatRequest {
  message: string;
  auto_integrate?: boolean;
}

export interface SessionChatResponse {
  role: string;
  content: string;
  analysis?: Record<string, any>;
  risk_score?: number;
  domains?: string[];
  actions?: Record<string, any>[];
  timestamp: string;
}

export interface SessionMessage {
  id: string;
  session_id: string;
  role: string;
  content: string;
  analysis?: Record<string, any>;
  risk_score?: number;
  domains?: string[];
  actions?: Record<string, any>[];
  timestamp: string;
}

// ==================== API Functions ====================

/**
 * Create a new analysis session
 */
export async function createSession(request: CreateSessionRequest): Promise<AnalysisSession> {
  const response = await api.post<AnalysisSession>('/api/v1/nlp/sessions', request);
  return response.data;
}

/**
 * List user's analysis sessions
 */
export async function listSessions(limit: number = 50, offset: number = 0, status?: string): Promise<SessionListResponse> {
  const params: any = {
    limit: limit.toString(),
    offset: offset.toString(),
    _t: Date.now(), // Cache-busting timestamp
  };

  if (status) {
    params.status = status;
  }

  const response = await api.get<SessionListResponse>('/api/v1/nlp/sessions', { params });
  return response.data;
}

/**
 * Get details of a specific analysis session
 */
export async function getSession(sessionId: string): Promise<AnalysisSession> {
  const response = await api.get<AnalysisSession>(`/api/v1/nlp/sessions/${sessionId}`);
  return response.data;
}

/**
 * Update an analysis session
 */
export async function updateSession(sessionId: string, request: UpdateSessionRequest): Promise<AnalysisSession> {
  const response = await api.put<AnalysisSession>(`/api/v1/nlp/sessions/${sessionId}`, request);
  return response.data;
}

/**
 * Delete an analysis session
 */
export async function deleteSession(sessionId: string): Promise<{ message: string }> {
  const response = await api.delete<{ message: string }>(`/api/v1/nlp/sessions/${sessionId}`);
  return response.data;
}

/**
 * Clean up orphaned sessions (dev/debug only)
 */
export async function cleanupOrphanedSessions(): Promise<{ message: string; deleted_count: number }> {
  const response = await api.post<{ message: string; deleted_count: number }>('/api/v1/nlp/sessions/cleanup-orphaned');
  return response.data;
}

/**
 * Resume an analysis session
 */
export async function resumeSession(sessionId: string): Promise<AnalysisSession> {
  const response = await api.post<AnalysisSession>(`/api/v1/nlp/sessions/${sessionId}/resume`);
  return response.data;
}

/**
 * Add data from Intake Inbox to session
 */
export async function addIntakeData(sessionId: string, intakeId: string): Promise<DataSource> {
  const response = await api.post<DataSource>(`/api/v1/nlp/sessions/${sessionId}/data/intake`, null, {
    params: { intake_id: intakeId }
  });
  return response.data;
}

/**
 * Upload new data to session
 */
export async function uploadDataToSession(
  sessionId: string,
  file: File,
  dataType: string = 'document'
): Promise<DataSource> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('data_type', dataType);

  const response = await api.post<DataSource>(`/api/v1/nlp/sessions/${sessionId}/data/upload`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
}

/**
 * List data sources in a session
 */
export async function listSessionData(sessionId: string): Promise<DataSource[]> {
  const response = await api.get<DataSource[]>(`/api/v1/nlp/sessions/${sessionId}/data`);
  return response.data;
}

/**
 * Remove a data source from session
 */
export async function removeDataSource(sessionId: string, sourceId: string): Promise<{ message: string }> {
  const response = await api.delete<{ message: string }>(`/api/v1/nlp/sessions/${sessionId}/data/${sourceId}`);
  return response.data;
}

/**
 * Send message in session context
 */
export async function sessionChat(sessionId: string, request: SessionChatRequest): Promise<SessionChatResponse> {
  const response = await api.post<SessionChatResponse>(`/api/v1/nlp/sessions/${sessionId}/chat`, request);
  return response.data;
}

/**
 * Get messages in a session
 */
export async function getSessionMessages(sessionId: string, limit: number = 100, offset: number = 0): Promise<SessionMessage[]> {
  const response = await api.get<SessionMessage[]>(`/api/v1/nlp/sessions/${sessionId}/messages`, {
    params: { limit, offset }
  });
  return response.data;
}

/**
 * Generate session title from context and queries
 */
export async function generateSessionTitle(sessionId: string): Promise<AnalysisSession> {
  const response = await api.post<AnalysisSession>(`/api/v1/nlp/sessions/${sessionId}/generate-title`);
  return response.data;
}

/**
 * Get full chat history across all sessions
 */
export async function getChatHistory(limit: number = 100, offset: number = 0, sessionId?: string): Promise<SessionMessage[]> {
  const params: any = {
    limit: limit.toString(),
    offset: offset.toString(),
  };

  if (sessionId) {
    params.session_id = sessionId;
  }

  const response = await api.get<SessionMessage[]>('/api/v1/nlp/sessions/chat/history', { params });
  return response.data;
}

/**
 * Search/filter historical chats
 */
export async function searchChatHistory(
  query: string,
  limit: number = 50,
  offset: number = 0,
  sessionId?: string
): Promise<SessionMessage[]> {
  const params: any = {
    q: query,
    limit: limit.toString(),
    offset: offset.toString(),
  };

  if (sessionId) {
    params.session_id = sessionId;
  }

  const response = await api.get<SessionMessage[]>('/api/v1/nlp/sessions/chat/search', { params });
  return response.data;
}

/**
 * Get session telemetry context
 */
export async function getSessionTelemetryContext(sessionId: string, limit: number = 50): Promise<any> {
  const response = await api.get<any>(`/api/v1/nlp/sessions/${sessionId}/context/telemetry`, {
    params: { limit }
  });
  return response.data;
}

/**
 * Get session alarms context
 */
export async function getSessionAlarmsContext(sessionId: string, limit: number = 50): Promise<any> {
  const response = await api.get<any>(`/api/v1/nlp/sessions/${sessionId}/context/alarms`, {
    params: { limit }
  });
  return response.data;
}

/**
 * Get session Kanban context
 */
export async function getSessionKanbanContext(sessionId: string, limit: number = 50): Promise<any> {
  const response = await api.get<any>(`/api/v1/nlp/sessions/${sessionId}/context/kanban`, {
    params: { limit }
  });
  return response.data;
}

/**
 * Get session registries context
 */
export async function getSessionRegistriesContext(sessionId: string, limit: number = 50): Promise<any> {
  const response = await api.get<any>(`/api/v1/nlp/sessions/${sessionId}/context/registries`, {
    params: { limit }
  });
  return response.data;
}

// Export as a single object for convenience
export const analysisSessionsApi = {
  createSession,
  listSessions,
  getSession,
  updateSession,
  deleteSession,
  cleanupOrphanedSessions,
  resumeSession,
  addIntakeData,
  uploadDataToSession,
  listSessionData,
  removeDataSource,
  sessionChat,
  getSessionMessages,
  generateSessionTitle,
  getChatHistory,
  searchChatHistory,
  getSessionTelemetryContext,
  getSessionAlarmsContext,
  getSessionKanbanContext,
  getSessionRegistriesContext,
};
