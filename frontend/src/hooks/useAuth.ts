import { useCallback } from 'react';
import { useAuthStore } from '../stores';
import { Permission } from '../types';

export function useAuth() {
  const {
    user,
    isAuthenticated,
    isLoading,
    error,
    login,
    logout,
    clearError,
    hasPermission: checkPermission,
  } = useAuthStore();

  const hasPermission = useCallback(
    (resource: string, action: Permission['action']) => {
      return checkPermission(resource, action);
    },
    [checkPermission]
  );

  const isAdmin = user?.role === 'admin';
  const isOperator = user?.role === 'operator' || user?.role === 'admin';
  const isMaintenance = user?.role === 'maintenance' || user?.role === 'admin';

  return {
    user,
    isAuthenticated,
    isLoading,
    error,
    isAdmin,
    isOperator,
    isMaintenance,
    login,
    logout,
    clearError,
    hasPermission,
  };
}
