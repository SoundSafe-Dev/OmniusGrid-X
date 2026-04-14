import { FC } from 'react'
import { Routes, Route } from 'react-router-dom'
import { Layout, ProtectedRoute } from './components'
import { Login } from './pages/auth'

// Existing pages
import Dashboard from './pages/Dashboard'
import Assets from './pages/Assets'
import AssetDetail from './pages/AssetDetail'
import Alarms from './pages/Alarms'
import OEE from './pages/OEE'

// AI Engine pages
import { TacticalEngine, StrategicEngine, MLOpsPipeline, CloudGateway } from './pages/engines'

// Analytics pages
import { TelemetryCharts, AssetHealth, PredictiveMaintenance } from './pages/analytics'

// Fleet pages
import { FleetOverview, OrganizationTree } from './pages/fleet'

// Admin pages
import { Users, Collectors, SystemHealth, Settings } from './pages/admin'

// Logistics pages
import { YardManagement, TransportationManagement } from './pages/logistics'

const App: FC = () => {
  return (
    <Routes>
        {/* Public Routes */}
        <Route path="/login" element={<Login />} />

        {/* Protected Routes */}
        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            {/* Dashboard */}
            <Route path="/" element={<Dashboard />} />

            {/* Assets */}
            <Route path="/assets" element={<Assets />} />
            <Route path="/assets/:id" element={<AssetDetail />} />

            {/* Alarms */}
            <Route path="/alarms" element={<Alarms />} />

            {/* OEE */}
            <Route path="/oee" element={<OEE />} />

            {/* AI Engines */}
            <Route path="/engines/tactical" element={<TacticalEngine />} />
            <Route path="/engines/strategic" element={<StrategicEngine />} />
            <Route path="/engines/mlops" element={<MLOpsPipeline />} />
            <Route path="/engines/cloud" element={<CloudGateway />} />

            {/* Analytics */}
            <Route path="/analytics/telemetry" element={<TelemetryCharts />} />
            <Route path="/analytics/health" element={<AssetHealth />} />
            <Route path="/analytics/maintenance" element={<PredictiveMaintenance />} />

            {/* Fleet */}
            <Route path="/fleet" element={<FleetOverview />} />
            <Route path="/fleet/organization" element={<OrganizationTree />} />

            {/* Logistics - YMS & TMS */}
            <Route path="/logistics/yard" element={<YardManagement />} />
            <Route path="/logistics/transportation" element={<TransportationManagement />} />

            {/* Admin */}
            <Route path="/admin/users" element={<Users />} />
            <Route path="/admin/collectors" element={<Collectors />} />
            <Route path="/admin/health" element={<SystemHealth />} />
            <Route path="/admin/settings" element={<Settings />} />
          </Route>
        </Route>

        {/* 404 */}
        <Route path="*" element={
          <div className="min-h-screen flex items-center justify-center bg-opsgrid-bg">
            <div className="text-center">
              <h1 className="text-4xl font-bold text-opsgrid-text mb-4">404</h1>
              <p className="text-opsgrid-text-secondary mb-4">Page not found</p>
              <a href="/" className="text-opsgrid-primary hover:underline">Go back home</a>
            </div>
          </div>
        } />
      </Routes>
  )
}

export default App
