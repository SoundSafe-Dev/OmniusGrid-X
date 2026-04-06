import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { Theme, TimeRange, TIME_RANGES } from '../types';

interface UIState {
  // Sidebar
  sidebarCollapsed: boolean;
  mobileSidebarOpen: boolean;

  // Theme
  theme: Theme;

  // Preferences
  timezone: string;
  dateFormat: string;
  timeFormat: '12h' | '24h';
  defaultTimeRange: TimeRange;

  // Dashboard
  dashboardRefreshInterval: number; // seconds

  // Actions
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setMobileSidebarOpen: (open: boolean) => void;
  setTheme: (theme: Theme) => void;
  setTimezone: (timezone: string) => void;
  setDateFormat: (format: string) => void;
  setTimeFormat: (format: '12h' | '24h') => void;
  setDefaultTimeRange: (range: TimeRange) => void;
  setDashboardRefreshInterval: (seconds: number) => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      mobileSidebarOpen: false,
      theme: 'dark',
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      dateFormat: 'MM/dd/yyyy',
      timeFormat: '12h',
      defaultTimeRange: TIME_RANGES[2], // Last 24 Hours
      dashboardRefreshInterval: 30,

      toggleSidebar: () =>
        set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),

      setSidebarCollapsed: (collapsed) =>
        set({ sidebarCollapsed: collapsed }),

      setMobileSidebarOpen: (open) =>
        set({ mobileSidebarOpen: open }),

      setTheme: (theme) => {
        set({ theme });
        // Apply theme to document
        if (theme === 'dark') {
          document.documentElement.classList.add('dark');
        } else {
          document.documentElement.classList.remove('dark');
        }
      },

      setTimezone: (timezone) => set({ timezone }),

      setDateFormat: (format) => set({ dateFormat: format }),

      setTimeFormat: (format) => set({ timeFormat: format }),

      setDefaultTimeRange: (range) => set({ defaultTimeRange: range }),

      setDashboardRefreshInterval: (seconds) =>
        set({ dashboardRefreshInterval: seconds }),
    }),
    {
      name: 'ui-storage',
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        theme: state.theme,
        timezone: state.timezone,
        dateFormat: state.dateFormat,
        timeFormat: state.timeFormat,
        defaultTimeRange: state.defaultTimeRange,
        dashboardRefreshInterval: state.dashboardRefreshInterval,
      }),
    }
  )
);
