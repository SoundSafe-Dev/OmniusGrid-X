import { FC, lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import { Layout, ProtectedRoute } from './components'
import { Login } from './pages/auth'
import { TooltipProvider } from './components/ui'
import ErrorBoundary from './components/ErrorBoundary'

// Route-level code splitting (task 4): each page is fetched on demand instead of
// being bundled into the initial load. Default-exported pages lazy directly;
// barrel/named exports are mapped to a default for React.lazy.
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Assets = lazy(() => import('./pages/Assets'))
const AssetDetail = lazy(() => import('./pages/AssetDetail'))
const Alarms = lazy(() => import('./pages/Alarms'))
const OEE = lazy(() => import('./pages/OEE'))
const Kanban = lazy(() => import('./pages/Kanban'))

const named = <M, K extends keyof M>(loader: () => Promise<M>, key: K) =>
  lazy(() => loader().then((m) => ({ default: m[key] as any })))

const TacticalEngine = named(() => import('./pages/engines'), 'TacticalEngine')
const StrategicEngine = named(() => import('./pages/engines'), 'StrategicEngine')
const MLOpsPipeline = named(() => import('./pages/engines'), 'MLOpsPipeline')
const CloudGateway = named(() => import('./pages/engines'), 'CloudGateway')

const TelemetryCharts = named(() => import('./pages/analytics'), 'TelemetryCharts')
const AssetHealth = named(() => import('./pages/analytics'), 'AssetHealth')
const PredictiveMaintenance = named(() => import('./pages/analytics'), 'PredictiveMaintenance')

const FleetOverview = named(() => import('./pages/fleet'), 'FleetOverview')
const OrganizationTree = named(() => import('./pages/fleet'), 'OrganizationTree')

const Users = named(() => import('./pages/admin'), 'Users')
const Collectors = named(() => import('./pages/admin'), 'Collectors')
const SystemHealth = named(() => import('./pages/admin'), 'SystemHealth')
const Settings = named(() => import('./pages/admin'), 'Settings')

const YardManagement = named(() => import('./pages/logistics'), 'YardManagement')
const TransportationManagement = named(() => import('./pages/logistics'), 'TransportationManagement')

const CorrelationAIPane = named(() => import('./components/nlp/CorrelationAIPane'), 'CorrelationAIPane')
const IntakeInbox = named(() => import('./pages/intake/IntakeInbox'), 'IntakeInbox')

const RouteFallback = () => (
  <div className="min-h-screen flex items-center justify-center bg-opsgrid-bg" role="status" aria-live="polite">
    <span className="text-opsgrid-text-secondary">Loading…</span>
  </div>
)

const App: FC = () => {
  return (
    <TooltipProvider>
      <ErrorBoundary>
        <Suspense fallback={<RouteFallback />}>
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

                {/* Kanban Board */}
                <Route path="/kanban" element={<Kanban />} />

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

                {/* NLP & Intake */}
                <Route path="/nlp" element={<CorrelationAIPane />} />
                <Route path="/intake" element={<IntakeInbox />} />

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
        </Suspense>
      </ErrorBoundary>
    </TooltipProvider>
  )
}

export default App
