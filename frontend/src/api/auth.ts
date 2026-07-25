import { api } from './client';
import {
  AuthResponse,
  LoginCredentials,
  User,
  PaginatedResponse,
} from '../types';

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
    const userResponse = await api.get<User>('/api/v1/auth/me', {
      headers: {
        'Authorization': `Bearer ${response.data.access_token}`,
      },
    });
    
    return {
      accessToken: response.data.access_token,
      refreshToken: (response.data as any).refresh_token,
      user: userResponse.data,
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
    const response = await api.get<User>('/api/v1/auth/me');
    return response.data;
  },

  getUsers: async (params?: { skip?: number; limit?: number }): Promise<PaginatedResponse<User>> => {
    const response = await api.get<PaginatedResponse<User>>('/api/v1/auth/users', { params });
    return response.data;
  },

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
};
