import { FC } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import ErrorBoundary from '../ErrorBoundary';

const RouteError: FC = () => (
  <div className="flex items-center justify-center h-full py-12" role="alert">
    <div className="text-center">
      <p className="text-status-alarm">This page hit an unexpected error.</p>
      <p className="text-sm text-opsgrid-text-secondary mt-1">
        Try another page from the sidebar, or reload.
      </p>
    </div>
  </div>
);

export const Layout: FC = () => {
  const location = useLocation();
  return (
    <div className="min-h-screen bg-opsgrid-bg flex">
      {/* Desktop Sidebar */}
      <div className="hidden lg:block">
        <Sidebar />
      </div>

      {/* Main Content */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Header />
        <div className="flex-1 overflow-auto p-6">
          {/* Per-route boundary: a render crash in one page shows this fallback
              while the sidebar/header shell stays usable, instead of the
              app-root boundary blanking the whole app (the failure mode that
              made e.g. the geofence-map crash so severe). Keyed by path so
              navigating to another page remounts it and clears the error. */}
          <ErrorBoundary key={location.pathname} fallback={<RouteError />}>
            <Outlet />
          </ErrorBoundary>
        </div>
      </main>
    </div>
  );
};
