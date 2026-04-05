import { FC } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { LayoutDashboard, Box, Bell, BarChart3, Settings } from 'lucide-react'

interface LayoutProps {
  children: React.ReactNode
}

const Layout: FC<LayoutProps> = ({ children }) => {
  const location = useLocation()
  
  const navItems = [
    { path: '/', label: 'Dashboard', icon: LayoutDashboard },
    { path: '/assets', label: 'Assets', icon: Box },
    { path: '/alarms', label: 'Alarms', icon: Bell },
    { path: '/oee', label: 'OEE', icon: BarChart3 },
  ]
  
  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside className="w-64 bg-opsgrid-panel border-r border-opsgrid-border flex flex-col">
        <div className="p-4 border-b border-opsgrid-border">
          <h1 className="text-xl font-bold text-opsgrid-primary">OpsGrid</h1>
          <p className="text-xs text-opsgrid-text-secondary">Manufacturing Operations</p>
        </div>
        
        <nav className="flex-1 p-4 space-y-2">
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive = location.pathname === item.path
            
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                  isActive
                    ? 'bg-opsgrid-primary/20 text-opsgrid-primary'
                    : 'text-opsgrid-text-secondary hover:bg-opsgrid-border hover:text-opsgrid-text'
                }`}
              >
                <Icon size={20} />
                <span>{item.label}</span>
              </Link>
            )
          })}
        </nav>
        
        <div className="p-4 border-t border-opsgrid-border">
          <button className="flex items-center gap-3 px-4 py-3 rounded-lg text-opsgrid-text-secondary hover:bg-opsgrid-border hover:text-opsgrid-text w-full">
            <Settings size={20} />
            <span>Settings</span>
          </button>
        </div>
      </aside>
      
      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <header className="bg-opsgrid-panel border-b border-opsgrid-border p-4 sticky top-0 z-10">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">
              {navItems.find((item) => item.path === location.pathname)?.label || 'OpsGrid'}
            </h2>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 text-sm text-opsgrid-text-secondary">
                <span className="w-2 h-2 rounded-full bg-status-running animate-pulse"></span>
                System Online
              </div>
            </div>
          </div>
        </header>
        
        <div className="p-6">
          {children}
        </div>
      </main>
    </div>
  )
}

export default Layout
