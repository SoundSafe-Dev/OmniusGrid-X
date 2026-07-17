import { FC } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuthStore } from '../../stores';
import { isConsoleAdminUser } from '../../types/auth';

/**
 * Guards admin-only pages (/admin/*).
 */
export const AdminRoute: FC = () => {
  const location = useLocation();
  const { user, isAuthenticated, isLoading } = useAuthStore();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-opsgrid-bg">
        <div className="animate-pulse text-opsgrid-primary">Loading...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (!isConsoleAdminUser(user)) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
};
