import { api } from './client';
import {
  AuthResponse,
  LoginCredentials,
  User,
  PaginatedResponse,
} from '../types';

export const authApi = {
  login: async (credentials: LoginCredentials): Promise<{
    accessToken: string;
    refreshToken: string;
    user: User;
  }> => {
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
      refreshToken: response.data.refresh_token,
      user: userResponse.data,
    };
  },

  logout: async (refreshToken?: string | null): Promise<void> => {
    await api.post('/api/v1/auth/logout', {
      refreshToken: refreshToken ?? undefined,
    });
  },

  refreshToken: async (refreshToken: string): Promise<{
    accessToken: string;
    refreshToken: string;
  }> => {
    const response = await api.post<AuthResponse>('/api/v1/auth/refresh', {
      refreshToken,
    });
    return {
      accessToken: response.data.access_token,
      refreshToken: response.data.refresh_token,
    };
  },

  getMe: async (): Promise<User> => {
    const response = await api.get<User>('/api/v1/auth/me');
    return response.data;
  },

  getUsers: async (params?: { skip?: number; limit?: number }): Promise<PaginatedResponse<User>> => {
    const response = await api.get<PaginatedResponse<User>>('/api/v1/auth/users', { params });
    return response.data;
  },

  createUser: async (userData: Omit<User, 'id' | 'createdAt' | 'updatedAt'> & { password: string }): Promise<User> => {
    const response = await api.post<User>('/api/v1/auth/users', userData);
    return response.data;
  },

  updateUser: async (userId: string, userData: Partial<User>): Promise<User> => {
    const response = await api.put<User>(`/api/v1/auth/users/${userId}`, userData);
    return response.data;
  },

  deleteUser: async (userId: string): Promise<void> => {
    await api.delete(`/api/v1/auth/users/${userId}`);
  },
};
