/**
 * Analysis Sessions API Client
 * 
 * API client for managing analysis sessions, data sources, and session-based chat.
 */

const API_BASE = (import.meta as any).env.VITE_API_BASE_URL || 'http://localhost:8000';

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
  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error('Failed to create session');
  }

  return response.json();
}

/**
 * List user's analysis sessions
 */
export async function listSessions(limit: number = 50, offset: number = 0, status?: string): Promise<SessionListResponse> {
  const params = new URLSearchParams({
    limit: limit.toString(),
    offset: offset.toString(),
  });

  if (status) {
    params.append('status', status);
  }

  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions?${params}`, {
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to list sessions');
  }

  return response.json();
}

/**
 * Get details of a specific analysis session
 */
export async function getSession(sessionId: string): Promise<AnalysisSession> {
  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/${sessionId}`, {
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to get session');
  }

  return response.json();
}

/**
 * Update an analysis session
 */
export async function updateSession(sessionId: string, request: UpdateSessionRequest): Promise<AnalysisSession> {
  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/${sessionId}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error('Failed to update session');
  }

  return response.json();
}

/**
 * Delete an analysis session
 */
export async function deleteSession(sessionId: string): Promise<{ message: string }> {
  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/${sessionId}`, {
    method: 'DELETE',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to delete session');
  }

  return response.json();
}

/**
 * Resume an analysis session
 */
export async function resumeSession(sessionId: string): Promise<AnalysisSession> {
  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/${sessionId}/resume`, {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to resume session');
  }

  return response.json();
}

/**
 * Add data from Intake Inbox to session
 */
export async function addIntakeData(sessionId: string, intakeId: string): Promise<DataSource> {
  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/${sessionId}/data/intake?intake_id=${intakeId}`, {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to add intake data');
  }

  return response.json();
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

  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/${sessionId}/data/upload`, {
    method: 'POST',
    credentials: 'include',
    body: formData,
  });

  if (!response.ok) {
    throw new Error('Failed to upload data');
  }

  return response.json();
}

/**
 * List data sources in a session
 */
export async function listSessionData(sessionId: string): Promise<DataSource[]> {
  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/${sessionId}/data`, {
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to list session data');
  }

  return response.json();
}

/**
 * Remove a data source from session
 */
export async function removeDataSource(sessionId: string, sourceId: string): Promise<{ message: string }> {
  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/${sessionId}/data/${sourceId}`, {
    method: 'DELETE',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to remove data source');
  }

  return response.json();
}

/**
 * Send message in session context
 */
export async function sessionChat(sessionId: string, request: SessionChatRequest): Promise<SessionChatResponse> {
  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/${sessionId}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error('Failed to send chat message');
  }

  return response.json();
}

/**
 * Get messages in a session
 */
export async function getSessionMessages(sessionId: string, limit: number = 100, offset: number = 0): Promise<SessionMessage[]> {
  const params = new URLSearchParams({
    limit: limit.toString(),
    offset: offset.toString(),
  });

  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/${sessionId}/messages?${params}`, {
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to get session messages');
  }

  return response.json();
}

/**
 * Generate session title from context and queries
 */
export async function generateSessionTitle(sessionId: string): Promise<AnalysisSession> {
  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/${sessionId}/generate-title`, {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to generate session title');
  }

  return response.json();
}

/**
 * Get full chat history across all sessions
 */
export async function getChatHistory(limit: number = 100, offset: number = 0, sessionId?: string): Promise<SessionMessage[]> {
  const params = new URLSearchParams({
    limit: limit.toString(),
    offset: offset.toString(),
  });

  if (sessionId) {
    params.append('session_id', sessionId);
  }

  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/chat/history?${params}`, {
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to get chat history');
  }

  return response.json();
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
  const params = new URLSearchParams({
    q: query,
    limit: limit.toString(),
    offset: offset.toString(),
  });

  if (sessionId) {
    params.append('session_id', sessionId);
  }

  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/chat/search?${params}`, {
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to search chat history');
  }

  return response.json();
}

/**
 * Get session telemetry context
 */
export async function getSessionTelemetryContext(sessionId: string, limit: number = 50): Promise<any> {
  const params = new URLSearchParams({
    limit: limit.toString(),
  });

  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/${sessionId}/context/telemetry?${params}`, {
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to get telemetry context');
  }

  return response.json();
}

/**
 * Get session alarms context
 */
export async function getSessionAlarmsContext(sessionId: string, limit: number = 50): Promise<any> {
  const params = new URLSearchParams({
    limit: limit.toString(),
  });

  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/${sessionId}/context/alarms?${params}`, {
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to get alarms context');
  }

  return response.json();
}

/**
 * Get session Kanban context
 */
export async function getSessionKanbanContext(sessionId: string, limit: number = 50): Promise<any> {
  const params = new URLSearchParams({
    limit: limit.toString(),
  });

  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/${sessionId}/context/kanban?${params}`, {
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to get Kanban context');
  }

  return response.json();
}

/**
 * Get session registries context
 */
export async function getSessionRegistriesContext(sessionId: string, limit: number = 50): Promise<any> {
  const params = new URLSearchParams({
    limit: limit.toString(),
  });

  const response = await fetch(`${API_BASE}/api/v1/nlp/sessions/${sessionId}/context/registries?${params}`, {
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to get registries context');
  }

  return response.json();
}

// Export as a single object for convenience
export const analysisSessionsApi = {
  createSession,
  listSessions,
  getSession,
  updateSession,
  deleteSession,
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
