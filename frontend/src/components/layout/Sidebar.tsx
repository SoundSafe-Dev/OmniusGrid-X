import { FC, ReactNode } from 'react';
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
} from 'lucide-react';
import { useUIStore, useAuthStore } from '../../stores';
import { cn } from '../../utils';
import { useAuth } from '../../hooks';

interface NavItem {
  path: string;
  label: string;
  icon: typeof LayoutDashboard;
  children?: NavItem[];
  adminOnly?: boolean;
}

const navItems: NavItem[] = [
  { path: '/', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/assets', label: 'Assets', icon: Box },
  { path: '/alarms', label: 'Alarms', icon: Bell },
  { path: '/oee', label: 'OEE', icon: BarChart3 },
  { path: '/kanban', label: 'Kanban Board', icon: KanbanIcon },
  {
    path: '/engines',
    label: 'AI Engines',
    icon: Brain,
    adminOnly: true,
    children: [
      { path: '/engines/tactical', label: 'Tactical', icon: Brain },
      { path: '/engines/strategic', label: 'Strategic', icon: Brain },
      { path: '/engines/mlops', label: 'MLOps', icon: Brain },
      { path: '/engines/cloud', label: 'Cloud Gateway', icon: Globe },
    ],
  },
  {
    path: '/analytics',
    label: 'Analytics',
    icon: LineChart,
    children: [
      { path: '/analytics/telemetry', label: 'Telemetry', icon: LineChart },
      { path: '/analytics/health', label: 'Asset Health', icon: LineChart },
      { path: '/analytics/maintenance', label: 'Maintenance', icon: LineChart },
    ],
  },
  {
    path: '/fleet',
    label: 'Fleet',
    icon: Globe,
    children: [
      { path: '/fleet', label: 'Overview', icon: Globe },
      { path: '/fleet/organization', label: 'Organization', icon: Globe },
    ],
  },
  {
    path: '/logistics',
    label: 'Logistics',
    icon: Truck,
    children: [
      { path: '/logistics/yard', label: 'Yard (YMS)', icon: Warehouse },
      { path: '/logistics/transportation', label: 'Transportation (TMS)', icon: Truck },
    ],
  },
  {
    path: '/admin',
    label: 'Admin',
    icon: Settings,
    adminOnly: true,
    children: [
      { path: '/admin/users', label: 'Users', icon: Users },
      { path: '/admin/collectors', label: 'Collectors', icon: Box },
      { path: '/admin/health', label: 'System Health', icon: LayoutDashboard },
      { path: '/admin/settings', label: 'Settings', icon: Settings },
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
            <div className="px-4 py-2 text-xs font-medium text-opsgrid-text-secondary uppercase tracking-wider">
              {item.label}
            </div>
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
              <Icon size={18} />
              {!sidebarCollapsed && <span className="text-sm">{child.label}</span>}
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
        <Icon size={20} />
        {!sidebarCollapsed && <span>{item.label}</span>}
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
            <p className="text-xs text-opsgrid-text-secondary">Universal Data Feed</p>
          </div>
        ) : (
          <div className="w-8 h-8 bg-opsgrid-primary rounded-lg flex items-center justify-center mx-auto">
            <span className="text-white font-bold text-lg">O</span>
          </div>
        )}
        {!mobile && (
          <button
            onClick={toggleSidebar}
            className="p-1 rounded hover:bg-opsgrid-border text-opsgrid-text-secondary"
          >
            {sidebarCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </button>
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
            <div className="flex items-center gap-2">
              <button
                onClick={toggleTheme}
                className="flex items-center gap-2 flex-1 px-3 py-2 rounded-lg text-opsgrid-text-secondary hover:bg-opsgrid-hover hover:text-opsgrid-text transition-colors"
                title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
              >
                {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
                <span className="text-sm">{theme === 'dark' ? 'Light' : 'Dark'}</span>
              </button>
              <button
                onClick={handleLogout}
                className="flex items-center justify-center p-2 rounded-lg text-opsgrid-text-secondary hover:bg-opsgrid-hover hover:text-opsgrid-text transition-colors"
                title="Logout"
              >
                <LogOut size={16} />
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <button
              onClick={toggleTheme}
              className="flex items-center justify-center w-full p-2 rounded-lg text-opsgrid-text-secondary hover:bg-opsgrid-hover hover:text-opsgrid-text transition-colors"
              title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
            >
              {theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
            </button>
            <button
              onClick={handleLogout}
              className="flex items-center justify-center w-full p-2 rounded-lg text-opsgrid-text-secondary hover:bg-opsgrid-hover hover:text-opsgrid-text transition-colors"
              title="Logout"
            >
              <LogOut size={20} />
            </button>
          </div>
        )}
      </div>
    </aside>
  );
};
