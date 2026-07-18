import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { User, LoginCredentials, hasPermission, Permission } from '../types';
import { authApi } from '../api';

interface AuthState {
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;

  // Actions
  login: (credentials: LoginCredentials) => Promise<void>;
  logout: () => Promise<void>;
  refreshAccessToken: () => Promise<boolean>;
  setUser: (user: User) => void;
  devLogin: (user: User, token: string) => void;
  clearError: () => void;
  hasPermission: (resource: string, action: Permission['action']) => boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,

      login: async (credentials) => {
        set({ isLoading: true, error: null });
        try {
          const response = await authApi.login(credentials);
          const { accessToken, refreshToken, user } = response;

          localStorage.setItem('accessToken', accessToken);
          if (refreshToken) localStorage.setItem('refreshToken', refreshToken);
          localStorage.setItem('user', JSON.stringify(user));
          // FS-128: cache the org id so stateless API clients (transportation/
          // geotab) can send it as the required organization_id query param.
          // /auth/me returns snake organization_id; the User type uses
          // organizationId — read whichever is present.
          const orgId = (user as any).organizationId ?? (user as any).organization_id;
          if (orgId) localStorage.setItem('organizationId', orgId);

          set({
            user,
            accessToken,
            refreshToken: refreshToken ?? null,
            isAuthenticated: true,
            isLoading: false,
          });
        } catch (error: any) {
          set({
            error: error.message || 'Login failed',
            isLoading: false,
            isAuthenticated: false,
          });
          throw error;
        }
      },

      logout: async () => {
        try {
          await authApi.logout();
        } catch {
          // Ignore logout errors
        }

        localStorage.removeItem('accessToken');
        localStorage.removeItem('refreshToken');
        localStorage.removeItem('devToken');
        localStorage.removeItem('user');
        localStorage.removeItem('organizationId');

        set({
          user: null,
          accessToken: null,
          refreshToken: null,
          isAuthenticated: false,
          error: null,
        });
      },

      refreshAccessToken: async () => {
        const { refreshToken } = get();
        if (!refreshToken) {
          set({ isAuthenticated: false });
          return false;
        }

        try {
          const response = await authApi.refreshToken(refreshToken);
          localStorage.setItem('accessToken', response.accessToken);
          set({ accessToken: response.accessToken });
          return true;
        } catch {
          // Refresh failed, logout
          get().logout();
          return false;
        }
      },

      setUser: (user) => {
        set({ user });
        localStorage.setItem('user', JSON.stringify(user));
      },

      devLogin: (user: User, token: string) => {
        localStorage.setItem('accessToken', token);
        localStorage.setItem('devToken', token);
        localStorage.setItem('user', JSON.stringify(user));
        const devOrgId = (user as any).organizationId ?? (user as any).organization_id;
        if (devOrgId) localStorage.setItem('organizationId', devOrgId);
        set({
          user,
          accessToken: token,
          isAuthenticated: true,
          isLoading: false,
        });
      },

      clearError: () => set({ error: null }),

      hasPermission: (resource, action) => {
        const { user } = get();
        if (!user) return false;
        return hasPermission(user, resource, action);
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({
        user: state.user,
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
);
