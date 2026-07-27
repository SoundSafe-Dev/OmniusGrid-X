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
  isActive: value.isActive ?? value.is_active ?? true,
  lastLoginAt: value.lastLoginAt ?? value.last_login_at ?? value.last_login,
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

  updateUser: async (
    userId: string,
    userData: { name?: string; email?: string; role?: UserRole }
  ): Promise<User> => {
    const response = await api.patch<RawUser>(
      `/api/v1/auth/users/${userId}`,
      userData
    );
    return normalizeUser(response.data);
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
