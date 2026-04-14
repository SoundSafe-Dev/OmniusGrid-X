import { FC } from 'react';
import { Outlet } from 'react-router-dom';
import { useUIStore } from '../../stores';
import { Sidebar } from './Sidebar';
import { Header } from './Header';

export const Layout: FC = () => {
  const { sidebarCollapsed } = useUIStore();

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
          <Outlet />
        </div>
      </main>
    </div>
  );
};
