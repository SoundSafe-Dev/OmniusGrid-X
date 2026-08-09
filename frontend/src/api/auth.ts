import { api } from './client';
import {
  AuthResponse,
  InvitationValidation,
  LoginCredentials,
  User,
  UserInvitation,
  UserInvitationStatus,
  UserRole,
  PaginatedResponse,
} from '../types';

type RawUser = Partial<User> & {
  full_name?: string;
  organization_id?: string;
  is_active?: boolean;
  last_login?: string;
  last_login_at?: string;
  created_at?: string;
  updated_at?: string;
};

const normalizeUser = (value: RawUser): User => ({
  id: String(value.id ?? ''),
  email: value.email ?? '',
  name: value.name ?? value.full_name ?? '',
  role: value.role ?? 'viewer',
  organizationId: value.organizationId ?? value.organization_id,
  // FALSE, not true. `UserResponse` always sends `is_active`, so this branch is dead —
  // but if it ever fires, showing a user as ACTIVE is claiming access we did not observe,
  // and showing them as inactive merely prompts a reactivation nobody needed. FS-482:
  // when a failure has to default somewhere, default away from the irreversible side.
  isActive: value.isActive ?? value.is_active ?? false,
  // FS-442: the wire field is `last_login`. `lastLoginAt` was declared once and
  // nothing ever sent it, so the type carries `lastLogin` — the fallbacks stay.
  lastLogin: value.lastLogin ?? value.last_login_at ?? value.last_login,
  createdAt: value.createdAt ?? value.created_at ?? '',
  updatedAt: value.updatedAt ?? value.updated_at ?? '',
});

export const authApi = {
  login: async (credentials: LoginCredentials): Promise<{ accessToken: string; refreshToken?: string; user: User }> => {
    const formData = new URLSearchParams();
    formData.append('username', credentials.email);
    formData.append('password', credentials.password);

    const response = await api.post<AuthResponse>('/api/v1/auth/login', formData, {
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
    });
    
    // Fetch user info after login
    const userResponse = await api.get<RawUser>('/api/v1/auth/me', {
      headers: {
        'Authorization': `Bearer ${response.data.access_token}`,
      },
    });
    
    return {
      accessToken: response.data.access_token,
      refreshToken: response.data.refresh_token,
      user: normalizeUser(userResponse.data),
    };
  },

  logout: async (): Promise<void> => {
    await api.post('/api/v1/auth/logout');
  },

  refreshToken: async (refreshToken: string): Promise<{ accessToken: string }> => {
    const response = await api.post<{ access_token: string }>('/api/v1/auth/refresh', {
      refreshToken,
    });
    return { accessToken: response.data.access_token };
  },

  getMe: async (): Promise<User> => {
    const response = await api.get<RawUser>('/api/v1/auth/me');
    return normalizeUser(response.data);
  },

  getUsers: async (params?: { skip?: number; limit?: number }): Promise<PaginatedResponse<User>> => {
    const response = await api.get<PaginatedResponse<User>>('/api/v1/auth/users', { params });
    return {
      ...response.data,
      items: response.data.items.map(normalizeUser),
    };
  },

  inviteUser: async (invitation: {
    email: string;
    role: UserRole;
  }): Promise<UserInvitation> => {
    const response = await api.post<UserInvitation>(
      '/api/v1/auth/users/invitations',
      invitation
    );
    return response.data;
  },

  // MERGED 2026-08-08. Ours (FS-221) targets /api/v1/users; Hridyansh's invitation methods
  // target /api/v1/auth/users, and BOTH routers are mounted, so both resolve. His
  // `updateUser` is the one thing dropped: ours is a strict superset — it also maps
  // `isActive`, which his signature cannot express — and two methods of one name cannot
  // coexist. Nothing else of his was removed.
  // The write methods target /api/v1/users (the admin router added in FS-221),
  // NOT /api/v1/auth/users. Those auth paths never existed — only GET did — so
  // these three 404'd, which is why AdminPages hard-coded USER_MGMT_ENABLED=false
  // rather than shipping buttons that failed. `getUsers` stays on the auth path
  // because that endpoint returns the exact `{name, isActive}` shape the table
  // renders; the admin list endpoint returns full_name and would need the table
  // reworked, which is not what enabling these buttons requires.
  createUser: async (userData: Omit<User, 'id' | 'createdAt' | 'updatedAt'> & { password: string }): Promise<User> => {
    // Mapped explicitly rather than through the casing seam: the difference is the
    // field NAME, not its casing. The admin form carries `name`; the server field
    // is `full_name`, and it rejects unknown keys, so passing the form object
    // straight through would 422. `isActive` is not settable at creation — new
    // users are always active — so it is dropped here instead of silently ignored.
    const response = await api.post<User>('/api/v1/users/', {
      email: userData.email,
      full_name: userData.name,
      password: userData.password,
      role: userData.role,
    });
    return response.data;
  },

  // PATCH, not PUT: the server distinguishes an omitted field from a reset one, so
  // editing a name cannot silently reactivate a deactivated account.
  updateUser: async (userId: string, userData: Partial<User>): Promise<User> => {
    // Only the keys actually present are sent, so PATCH semantics survive the
    // client: including `is_active: undefined` would serialise and could flip a
    // field the caller never touched.
    const body: Record<string, unknown> = {};
    if (userData.name !== undefined) body.full_name = userData.name;
    if (userData.role !== undefined) body.role = userData.role;
    if (userData.isActive !== undefined) body.is_active = userData.isActive;
    const response = await api.patch<User>(`/api/v1/users/${userId}`, body);
    return response.data;
  },

  // Deactivates rather than destroys — the server never hard-deletes a user,
  // because alarms.acknowledged_by and alarm_rules.created_by reference them.
  deleteUser: async (userId: string): Promise<void> => {
    await api.delete(`/api/v1/users/${userId}`);
  },

  getInvitations: async (params?: {
    skip?: number;
    limit?: number;
    invitation_status?: UserInvitationStatus;
  }): Promise<PaginatedResponse<UserInvitation>> => {
    const response = await api.get<PaginatedResponse<UserInvitation>>(
      '/api/v1/auth/users/invitations',
      { params }
    );
    return response.data;
  },

  resendInvitation: async (invitationId: string): Promise<UserInvitation> => {
    const response = await api.post<UserInvitation>(
      `/api/v1/auth/users/invitations/${invitationId}/resend`
    );
    return response.data;
  },

  revokeInvitation: async (invitationId: string): Promise<UserInvitation> => {
    const response = await api.delete<UserInvitation>(
      `/api/v1/auth/users/invitations/${invitationId}`
    );
    return response.data;
  },


  deactivateUser: async (userId: string): Promise<User> => {
    const response = await api.delete<RawUser>(`/api/v1/auth/users/${userId}`);
    return normalizeUser(response.data);
  },

  reactivateUser: async (userId: string): Promise<User> => {
    const response = await api.post<RawUser>(
      `/api/v1/auth/users/${userId}/reactivate`
    );
    return normalizeUser(response.data);
  },

  validateInvitation: async (token: string): Promise<InvitationValidation> => {
    const response = await api.post<InvitationValidation>(
      '/api/v1/auth/invitations/validate',
      { token }
    );
    return response.data;
  },

  acceptInvitation: async (data: {
    token: string;
    name: string;
    password: string;
  }): Promise<User> => {
    const response = await api.post<{ message: string; user: RawUser }>(
      '/api/v1/auth/invitations/accept',
      data
    );
    return normalizeUser(response.data.user);
  },
};
