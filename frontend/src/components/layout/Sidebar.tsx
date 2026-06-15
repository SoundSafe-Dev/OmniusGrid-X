import { FC } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard,
  Box,
  Bell,
  BarChart3,
  Brain,
  LineChart,
  Globe,
  Settings,
  Users,
  ChevronLeft,
  ChevronRight,
  LogOut,
  Warehouse,
  Truck,
  Sun,
  Moon,
  Kanban as KanbanIcon,
  MessageSquare,
  Inbox,
  Bug,
} from 'lucide-react';
import { useUIStore, useAuthStore } from '../../stores';
import { cn } from '../../utils';
import { useAuth } from '../../hooks';
import { Tooltip, TooltipTrigger, TooltipContent } from '../ui';

interface NavItem {
  path: string;
  label: string;
  icon: typeof LayoutDashboard;
  children?: NavItem[];
  adminOnly?: boolean;
  description?: string;
}

const navItems: NavItem[] = [
  { path: '/', label: 'Dashboard', icon: LayoutDashboard, description: 'Overview of fleet status, assets, and active alarms' },
  { path: '/assets', label: 'Assets', icon: Box, description: 'Manage and monitor manufacturing equipment' },
  { path: '/alarms', label: 'Alarms', icon: Bell, description: 'View and acknowledge system alarms' },
  { path: '/oee', label: 'OEE', icon: BarChart3, description: 'Overall Equipment Effectiveness analytics' },
  { path: '/kanban', label: 'Kanban Board', icon: KanbanIcon, description: 'Task management and workflow tracking' },
  { path: '/nlp', label: 'Correlation AI', icon: MessageSquare, description: 'AI-powered cross-domain analysis' },
  { path: '/intake', label: 'Intake Inbox', icon: Inbox, description: 'Upload operational data for AI analysis' },
  {
    path: '/engines',
    label: 'AI Engines',
    icon: Brain,
    description: 'Tactical, Strategic, MLOps, and Cloud Gateway',
    children: [
      { path: '/engines/tactical', label: 'Tactical', icon: Brain, description: 'Edge inference engine for real-time control' },
      { path: '/engines/strategic', label: 'Strategic', icon: Brain, description: 'Cloud-based optimization and scenario analysis' },
      { path: '/engines/mlops', label: 'MLOps', icon: Brain, description: 'Model lifecycle management and deployment' },
      { path: '/engines/cloud', label: 'Cloud Gateway', icon: Globe, description: 'Secure edge-to-cloud communication' },
    ],
  },
  {
    path: '/analytics',
    label: 'Analytics',
    icon: LineChart,
    description: 'Operational data visualization',
    children: [
      { path: '/analytics/telemetry', label: 'Telemetry', icon: LineChart, description: 'Real-time sensor data charts' },
      { path: '/analytics/health', label: 'Asset Health', icon: LineChart, description: 'Equipment performance metrics' },
      { path: '/analytics/maintenance', label: 'Maintenance', icon: LineChart, description: 'Predictive maintenance analytics' },
    ],
  },
  {
    path: '/fleet',
    label: 'Fleet',
    icon: Globe,
    description: 'Fleet management and tracking',
    children: [
      { path: '/fleet', label: 'Overview', icon: Globe, description: 'Fleet-wide status summary' },
      { path: '/fleet/organization', label: 'Organization', icon: Globe, description: 'Organizational hierarchy view' },
    ],
  },
  {
    path: '/logistics',
    label: 'Logistics',
    icon: Truck,
    description: 'Yard and transportation management',
    children: [
      { path: '/logistics/yard', label: 'Yard (YMS)', icon: Warehouse, description: 'Yard Management System for trailers' },
      { path: '/logistics/transportation', label: 'Transportation (TMS)', icon: Truck, description: 'Transportation Management System' },
    ],
  },
  {
    path: '/admin',
    label: 'Admin',
    icon: Settings,
    description: 'System administration',
    adminOnly: true,
    children: [
      { path: '/admin/users', label: 'Users', icon: Users, description: 'User and role management' },
      { path: '/admin/collectors', label: 'Collectors', icon: Box, description: 'Data collector configuration' },
      { path: '/admin/health', label: 'System Health', icon: LayoutDashboard, description: 'Infrastructure status monitoring' },
      { path: '/admin/errors', label: 'Error Triage', icon: Bug, description: 'Production error monitoring' },
      { path: '/admin/settings', label: 'Settings', icon: Settings, description: 'System configuration' },
    ],
  },
];

interface SidebarProps {
  mobile?: boolean;
  onClose?: () => void;
}

export const Sidebar: FC<SidebarProps> = ({ mobile = false, onClose }) => {
  const { sidebarCollapsed, toggleSidebar, theme, setTheme } = useUIStore();
  const { user, logout } = useAuthStore();
  const { isAdmin } = useAuth();
  const navigate = useNavigate();

  const toggleTheme = () => {
    setTheme(theme === 'dark' ? 'light' : 'dark');
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const filteredNavItems = navItems.filter((item) => !item.adminOnly || isAdmin);

  const NavItemComponent: FC<{ item: NavItem; depth?: number }> = ({
    item,
    depth = 0,
  }) => {
    const Icon = item.icon;
    const hasChildren = item.children && item.children.length > 0;

    if (hasChildren) {
      return (
        <div className="space-y-1">
          {!sidebarCollapsed && (
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="px-4 py-2 text-xs font-medium text-opsgrid-text-secondary uppercase tracking-wider">
                  {item.label}
                </div>
              </TooltipTrigger>
              <TooltipContent side="right">{item.description}</TooltipContent>
            </Tooltip>
          )}
          {item.children?.map((child) => (
            <NavLink
              key={child.path}
              to={child.path}
              onClick={() => mobile && onClose?.()}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 px-4 py-2 rounded-lg transition-colors',
                  isActive
                    ? 'bg-opsgrid-primary/20 text-opsgrid-primary'
                    : 'text-opsgrid-text-secondary hover:bg-opsgrid-border hover:text-opsgrid-text',
                  sidebarCollapsed && 'justify-center',
                  depth > 0 && 'ml-4'
                )
              }
            >
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex items-center gap-3 w-full">
                    <Icon size={18} />
                    {!sidebarCollapsed && <span className="text-sm">{child.label}</span>}
                  </div>
                </TooltipTrigger>
                <TooltipContent side="right">{child.description}</TooltipContent>
              </Tooltip>
            </NavLink>
          ))}
        </div>
      );
    }

    return (
      <NavLink
        to={item.path}
        onClick={() => mobile && onClose?.()}
        className={({ isActive }) =>
          cn(
            'flex items-center gap-3 px-4 py-3 rounded-lg transition-colors',
            isActive
              ? 'bg-opsgrid-primary/20 text-opsgrid-primary'
              : 'text-opsgrid-text-secondary hover:bg-opsgrid-border hover:text-opsgrid-text',
            sidebarCollapsed && 'justify-center'
          )
        }
      >
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center gap-3 w-full">
              <Icon size={20} />
              {!sidebarCollapsed && <span>{item.label}</span>}
            </div>
          </TooltipTrigger>
          <TooltipContent side="right">{item.description}</TooltipContent>
        </Tooltip>
      </NavLink>
    );
  };

  return (
    <aside
      className={cn(
        'bg-opsgrid-panel border-r border-opsgrid-border flex flex-col h-screen sticky top-0',
        sidebarCollapsed ? 'w-16' : 'w-64',
        mobile && 'w-64'
      )}
    >
      {/* Logo */}
      <div className="p-4 border-b border-opsgrid-border flex items-center justify-between">
        {!sidebarCollapsed || mobile ? (
          <div>
            <h1 className="text-xl font-bold text-opsgrid-primary">OmniusGrid</h1>
            <p className="text-xs text-opsgrid-text-secondary">Data Correlation for Industry 4.0</p>
          </div>
        ) : (
          <div className="w-8 h-8 bg-opsgrid-primary rounded-lg flex items-center justify-center mx-auto">
            <span className="text-white font-bold text-lg">O</span>
          </div>
        )}
        {!mobile && (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={toggleSidebar}
                className="p-1 rounded hover:bg-opsgrid-border text-opsgrid-text-secondary"
              >
                {sidebarCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">{sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}</TooltipContent>
          </Tooltip>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-2 overflow-y-auto">
        {filteredNavItems.map((item) => (
          <NavItemComponent key={item.path} item={item} />
        ))}
      </nav>

      {/* User Info */}
      <div className="p-4 border-t border-opsgrid-border">
        {!sidebarCollapsed || mobile ? (
          <div className="space-y-3">
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-opsgrid-primary/20 flex items-center justify-center">
                    <span className="text-opsgrid-primary font-medium">
                      {user?.name?.charAt(0).toUpperCase() || 'U'}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-opsgrid-text truncate">{user?.name}</p>
                    <p className="text-xs text-opsgrid-text-secondary capitalize">{user?.role}</p>
                  </div>
                </div>
              </TooltipTrigger>
              <TooltipContent side="right">Current user: {user?.name} ({user?.role})</TooltipContent>
            </Tooltip>
            <div className="flex items-center gap-2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={toggleTheme}
                    className="flex items-center gap-2 flex-1 px-3 py-2 rounded-lg text-opsgrid-text-secondary hover:bg-opsgrid-hover hover:text-opsgrid-text transition-colors"
                  >
                    {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
                    <span className="text-sm">{theme === 'dark' ? 'Light' : 'Dark'}</span>
                  </button>
                </TooltipTrigger>
                <TooltipContent side="right">{theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={handleLogout}
                    className="flex items-center justify-center p-2 rounded-lg text-opsgrid-text-secondary hover:bg-opsgrid-hover hover:text-opsgrid-text transition-colors"
                  >
                    <LogOut size={16} />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="right">Sign out of OmniusGrid</TooltipContent>
              </Tooltip>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={toggleTheme}
                  className="flex items-center justify-center w-full p-2 rounded-lg text-opsgrid-text-secondary hover:bg-opsgrid-hover hover:text-opsgrid-text transition-colors"
                >
                  {theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
                </button>
              </TooltipTrigger>
              <TooltipContent side="right">{theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={handleLogout}
                  className="flex items-center justify-center w-full p-2 rounded-lg text-opsgrid-text-secondary hover:bg-opsgrid-hover hover:text-opsgrid-text transition-colors"
                >
                  <LogOut size={20} />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right">Sign out of OmniusGrid</TooltipContent>
            </Tooltip>
          </div>
        )}
      </div>
    </aside>
  );
};
