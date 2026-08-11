import { FC } from 'react';
import { useLocation } from 'react-router-dom';
import { Menu, Bell, X } from 'lucide-react';
import { useUIStore } from '../../stores';
import { useActiveAlarms, useWebSocket } from '../../hooks';
import { ConnectionStatus } from '../common';
import { Sidebar } from './Sidebar';
import { Tooltip, TooltipTrigger, TooltipContent } from '../ui';

export const Header: FC = () => {
  const location = useLocation();
  const { mobileSidebarOpen, setMobileSidebarOpen } = useUIStore();
  const { connected, connectionState, pollingFallback } = useWebSocket();
  // `isError` is read, not just `data`. The query polls every TEN SECONDS, and react-query
  // keeps the last successful `data` across a failure — so without this a dead alarm feed
  // showed the last count it managed to fetch, indefinitely. Worse on a cold start: with no
  // data yet, `activeAlarms?.count || 0` is 0, the badge is hidden by `> 0`, and **an alarm
  // feed that has never answered renders as a plant with no active alarms.** On an industrial
  // monitoring product that is the one indicator that must never quietly read "all clear".
  const { data: activeAlarms, isError: alarmsUnavailable } = useActiveAlarms();

  // Get page title from current route
  const getPageTitle = () => {
    const path = location.pathname;
    if (path === '/') return 'Dashboard';
    if (path.startsWith('/assets')) return 'Assets';
    if (path.startsWith('/alarms')) return 'Alarms';
    if (path.startsWith('/oee')) return 'OEE';
    if (path.startsWith('/kanban')) return 'Kanban Board';
    if (path.startsWith('/engines/tactical')) return 'Tactical Engine';
    if (path.startsWith('/engines/strategic')) return 'Strategic Engine';
    if (path.startsWith('/engines/mlops')) return 'MLOps Pipeline';
    if (path.startsWith('/engines/cloud')) return 'Cloud Gateway';
    if (path.startsWith('/engines')) return 'AI Engines';
    if (path.startsWith('/analytics')) return 'Analytics';
    if (path.startsWith('/fleet')) return 'Fleet Management';
    if (path.startsWith('/logistics/yard')) return 'Yard Management';
    if (path.startsWith('/logistics/transportation')) return 'Transportation Management';
    if (path.startsWith('/logistics')) return 'Logistics';
    if (path.startsWith('/admin')) return 'Administration';
    return 'OmniusGrid';
  };

  // Get page description for tooltip
  const getPageDescription = () => {
    const path = location.pathname;
    if (path === '/') return 'Overview of fleet status, assets, and active alarms';
    if (path.startsWith('/assets')) return 'Manage and monitor manufacturing equipment';
    if (path.startsWith('/alarms')) return 'View and acknowledge system alarms';
    if (path.startsWith('/oee')) return 'Overall Equipment Effectiveness analytics';
    if (path.startsWith('/kanban')) return 'Task management and workflow tracking';
    if (path.startsWith('/engines/tactical')) return 'Edge inference engine for real-time control';
    if (path.startsWith('/engines/strategic')) return 'Cloud-based optimization and scenario analysis';
    if (path.startsWith('/engines/mlops')) return 'Model lifecycle management and deployment';
    if (path.startsWith('/engines/cloud')) return 'Secure edge-to-cloud communication';
    if (path.startsWith('/engines')) return 'AI Engines: Tactical, Strategic, MLOps, and Cloud Gateway';
    if (path.startsWith('/analytics')) return 'Operational data visualization and analytics';
    if (path.startsWith('/fleet')) return 'Fleet management and tracking';
    if (path.startsWith('/logistics/yard')) return 'Yard Management System for trailers';
    if (path.startsWith('/logistics/transportation')) return 'Transportation Management System';
    if (path.startsWith('/logistics')) return 'Yard and transportation management';
    if (path.startsWith('/admin')) return 'System administration and configuration';
    return 'Universal Manufacturing Data Feed Dashboard';
  };

  const activeAlarmsCount = activeAlarms?.count || 0;

  return (
    <>
      <header className="bg-opsgrid-panel border-b border-opsgrid-border p-4 sticky top-0 z-30">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            {/* Mobile menu button */}
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={() => setMobileSidebarOpen(!mobileSidebarOpen)}
                  className="lg:hidden p-2 rounded-lg hover:bg-opsgrid-border text-opsgrid-text-secondary"
                >
                  {mobileSidebarOpen ? <X size={20} /> : <Menu size={20} />}
                </button>
              </TooltipTrigger>
              <TooltipContent>Toggle mobile sidebar navigation</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <h2 className="text-lg font-semibold text-opsgrid-text">{getPageTitle()}</h2>
              </TooltipTrigger>
              <TooltipContent>{getPageDescription()}</TooltipContent>
            </Tooltip>
          </div>

          <div className="flex items-center gap-4">
            {/* Connection Status */}
            <Tooltip>
              <TooltipTrigger asChild>
                <div>
                  <ConnectionStatus
                    connected={connected}
                    state={connectionState}
                    pollingFallback={pollingFallback}
                  />
                </div>
              </TooltipTrigger>
              <TooltipContent>Real-time WebSocket connection status</TooltipContent>
            </Tooltip>

            {/* Alarm status unknown — deliberately rendered BEFORE the count badge, and
                shown whether or not a stale count survives, because "we cannot tell you"
                outranks a number nobody can date. */}
            {alarmsUnavailable && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="relative" role="status" aria-label="Alarm status unavailable">
                    <Bell size={20} className="text-status-warning" />
                    <span className="absolute -top-1 -right-1 w-4 h-4 bg-status-warning text-white text-xs rounded-full flex items-center justify-center">
                      ?
                    </span>
                  </div>
                </TooltipTrigger>
                <TooltipContent>
                  Alarm status unavailable — the alarm feed is not answering, so this is not a
                  report that there are no alarms.
                </TooltipContent>
              </Tooltip>
            )}

            {/* Active Alarms Badge */}
            {!alarmsUnavailable && activeAlarmsCount > 0 && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="relative">
                    <Bell size={20} className="text-opsgrid-text-secondary" />
                    <span className="absolute -top-1 -right-1 w-4 h-4 bg-status-alarm text-white text-xs rounded-full flex items-center justify-center">
                      {activeAlarmsCount > 9 ? '9+' : activeAlarmsCount}
                    </span>
                  </div>
                </TooltipTrigger>
                <TooltipContent>Active alarms notification badge - {activeAlarmsCount} alarms requiring attention</TooltipContent>
              </Tooltip>
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
