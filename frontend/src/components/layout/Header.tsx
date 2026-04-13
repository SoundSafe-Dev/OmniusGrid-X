import { FC, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Menu, Bell, X } from 'lucide-react';
import { useUIStore } from '../../stores';
import { useActiveAlarms, useWebSocket } from '../../hooks';
import { ConnectionStatus } from '../common';
import { cn } from '../../utils';
import { Sidebar } from './Sidebar';

export const Header: FC = () => {
  const location = useLocation();
  const { mobileSidebarOpen, setMobileSidebarOpen } = useUIStore();
  const { connected } = useWebSocket();
  const { data: activeAlarms } = useActiveAlarms();

  // Get page title from current route
  const getPageTitle = () => {
    const path = location.pathname;
    if (path === '/') return 'Dashboard';
    if (path.startsWith('/assets')) return 'Assets';
    if (path.startsWith('/alarms')) return 'Alarms';
    if (path.startsWith('/oee')) return 'OEE';
    if (path.startsWith('/engines/tactical')) return 'Tactical Engine';
    if (path.startsWith('/engines/strategic')) return 'Strategic Engine';
    if (path.startsWith('/engines/mlops')) return 'MLOps Pipeline';
    if (path.startsWith('/engines/cloud')) return 'Cloud Gateway';
    if (path.startsWith('/engines')) return 'AI Engines';
    if (path.startsWith('/analytics')) return 'Analytics';
    if (path.startsWith('/fleet')) return 'Fleet Management';
    if (path.startsWith('/admin')) return 'Administration';
    return 'OpsGrid';
  };

  const activeAlarmsCount = activeAlarms?.count || 0;

  return (
    <>
      <header className="bg-opsgrid-panel border-b border-opsgrid-border p-4 sticky top-0 z-30">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            {/* Mobile menu button */}
            <button
              onClick={() => setMobileSidebarOpen(!mobileSidebarOpen)}
              className="lg:hidden p-2 rounded-lg hover:bg-opsgrid-border text-opsgrid-text-secondary"
            >
              {mobileSidebarOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
            <h2 className="text-lg font-semibold text-opsgrid-text">{getPageTitle()}</h2>
          </div>

          <div className="flex items-center gap-4">
            {/* Connection Status */}
            <ConnectionStatus connected={connected} />

            {/* Active Alarms Badge */}
            {activeAlarmsCount > 0 && (
              <div className="relative">
                <Bell size={20} className="text-opsgrid-text-secondary" />
                <span className="absolute -top-1 -right-1 w-4 h-4 bg-status-alarm text-white text-xs rounded-full flex items-center justify-center">
                  {activeAlarmsCount > 9 ? '9+' : activeAlarmsCount}
                </span>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Mobile Sidebar Overlay */}
      {mobileSidebarOpen && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-40 lg:hidden"
            onClick={() => setMobileSidebarOpen(false)}
          />
          <div className="fixed left-0 top-0 h-full z-50 lg:hidden">
            <Sidebar mobile onClose={() => setMobileSidebarOpen(false)} />
          </div>
        </>
      )}
    </>
  );
};
