import { FC, lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
// Import from the layout module directly, not the top-level ./components barrel:
// that barrel re-exports the fleet map + charts (leaflet/plotly side-effect
// imports that don't tree-shake), and App is the eager root, so going through
// it would pull those heavy libs into the initial bundle.
import { AdminRoute, Layout, ProtectedRoute } from './components/layout'
import { AcceptInvitation, Login } from './pages/auth'
import { TooltipProvider, DialogProvider, ToastProvider } from './components/ui'
import ErrorBoundary from './components/ErrorBoundary'

// Route-level code splitting (task 4): each page is fetched on demand instead of
// being bundled into the initial load. Default-exported pages lazy directly;
// barrel/named exports are mapped to a default for React.lazy.
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Assets = lazy(() => import('./pages/Assets'))
const AssetDetail = lazy(() => import('./pages/AssetDetail'))
const Alarms = lazy(() => import('./pages/Alarms'))
const AlarmRules = lazy(() => import('./pages/AlarmRules'))
const OEE = lazy(() => import('./pages/OEE'))
const Kanban = lazy(() => import('./pages/Kanban'))
const ShopFloor = lazy(() => import('./pages/ShopFloor'))
const Activations = lazy(() => import('./pages/Activations'))

const named = <M, K extends keyof M>(loader: () => Promise<M>, key: K) =>
  lazy(() => loader().then((m) => ({ default: m[key] as any })))

const TacticalEngine = named(() => import('./pages/engines'), 'TacticalEngine')
const StrategicEngine = named(() => import('./pages/engines'), 'StrategicEngine')
const MLOpsPipeline = named(() => import('./pages/engines'), 'MLOpsPipeline')
const CloudGateway = named(() => import('./pages/engines'), 'CloudGateway')

const TelemetryCharts = named(() => import('./pages/analytics'), 'TelemetryCharts')
const AssetHealth = named(() => import('./pages/analytics'), 'AssetHealth')
const PredictiveMaintenance = named(() => import('./pages/analytics'), 'PredictiveMaintenance')

// FS-84: predictive-maintenance (RUL) and historian pages, lazy like the rest.
const PredictiveRUL = named(() => import('./pages/predictive'), 'PredictiveMaintenance')
const Historian = named(() => import('./pages/predictive'), 'Historian')

const FleetOverview = named(() => import('./pages/fleet'), 'FleetOverview')
const OrganizationTree = named(() => import('./pages/fleet'), 'OrganizationTree')

// OTA fleet management (integration), kept lazy like the other admin pages.
const Fleet = named(() => import('./pages/admin'), 'Fleet')
const FleetRolloutDetail = named(() => import('./pages/admin'), 'FleetRolloutDetail')
const FleetTargeting = named(() => import('./pages/admin'), 'FleetTargeting')
const MaintenanceWindows = named(() => import('./pages/admin'), 'MaintenanceWindows')

// Converged from integration: error-triage admin pages, kept lazy.
const ErrorTriage = named(() => import('./pages/admin'), 'ErrorTriage')
const ErrorTriageDetail = named(() => import('./pages/admin'), 'ErrorTriageDetail')

// FS-132: notifications center (subscriptions + delivery log), kept lazy.
const Notifications = named(() => import('./pages/admin'), 'Notifications')

// FS-285. `GET /exports/deliveries` returns a status and an error per scheduled send, and
// no page called it — a report that failed to go out was invisible to the person waiting
// for it. Through the same barrel as the other admin pages, which is the import shape
// `everyRoutedPageHasATest.test.ts` has to follow to see it at all.
const ExportDeliveries = named(() => import('./pages/admin'), 'ExportDeliveries')
const ExportSchedules = named(() => import('./pages/admin'), 'ExportSchedules')

const Users = named(() => import('./pages/admin'), 'Users')
const Collectors = named(() => import('./pages/admin'), 'Collectors')
const SystemHealth = named(() => import('./pages/admin'), 'SystemHealth')
const Settings = named(() => import('./pages/admin'), 'Settings')

const YardManagement = named(() => import('./pages/logistics'), 'YardManagement')
const TransportationManagement = named(() => import('./pages/logistics'), 'TransportationManagement')

const ERPIntegrations = named(() => import('./pages/erp'), 'ERPIntegrations')

// Grounded compliance Q&A over the RAG document corpus — a different surface from
// CorrelationAIPane below, which analyses operational data rather than policy.
const ComplianceAssistant = named(() => import('./pages/compliance'), 'ComplianceAssistant')

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
      <DialogProvider>
      <ToastProvider>
      <ErrorBoundary>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            {/* Public Routes */}
            <Route path="/login" element={<Login />} />
            <Route path="/accept-invite" element={<AcceptInvitation />} />

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
                <Route path="/alarms/rules" element={<AlarmRules />} />

                {/* OEE */}
                <Route path="/oee" element={<OEE />} />

                {/* Kanban Board */}
                <Route path="/kanban" element={<Kanban />} />

                {/* Shop Floor (FS-405): the four floor events and their posting ledger */}
                <Route path="/shop-floor" element={<ShopFloor />} />

                {/* Activated insights (FS-425): the cross-system worklist */}
                <Route path="/activations" element={<Activations />} />

                {/* AI Engines */}
                <Route path="/engines/tactical" element={<TacticalEngine />} />
                <Route path="/engines/strategic" element={<StrategicEngine />} />
                <Route path="/engines/mlops" element={<MLOpsPipeline />} />
                <Route path="/engines/cloud" element={<CloudGateway />} />

                {/* Analytics */}
                <Route path="/analytics/telemetry" element={<TelemetryCharts />} />
                <Route path="/analytics/health" element={<AssetHealth />} />
                <Route path="/analytics/maintenance" element={<PredictiveMaintenance />} />

                {/* Predictive maintenance (RUL) & Historian (FS-84) */}
                <Route path="/predictive/rul" element={<PredictiveRUL />} />
                <Route path="/predictive/historian" element={<Historian />} />

                {/* Fleet */}
                <Route path="/fleet" element={<FleetOverview />} />
                <Route path="/fleet/organization" element={<OrganizationTree />} />

                {/* Logistics - YMS & TMS */}
                <Route path="/logistics/yard" element={<YardManagement />} />
                <Route path="/logistics/transportation" element={<TransportationManagement />} />

                {/* ERP integrations (its data feeds Correlation AI on interaction) */}
                <Route path="/erp" element={<ERPIntegrations />} />

                {/* Compliance Assistant (RAG Q&A over the policy corpus) */}
                <Route path="/compliance" element={<ComplianceAssistant />} />

                {/* NLP & Intake */}
                <Route path="/nlp" element={<CorrelationAIPane />} />
                <Route path="/intake" element={<IntakeInbox />} />

                {/* Admin — AdminRoute exists and was exported but was wired to
                    no route, so every page below sat behind ProtectedRoute
                    alone and any authenticated user could reach it. */}
                <Route element={<AdminRoute />}>
                  <Route path="/admin/users" element={<Users />} />
                  <Route path="/admin/collectors" element={<Collectors />} />
                  <Route path="/admin/health" element={<SystemHealth />} />
                  <Route path="/admin/settings" element={<Settings />} />
                  <Route path="/admin/notifications" element={<Notifications />} />
                  <Route path="/admin/export-deliveries" element={<ExportDeliveries />} />
                  <Route path="/admin/export-schedules" element={<ExportSchedules />} />
                  <Route path="/admin/errors" element={<ErrorTriage />} />
                  <Route path="/admin/errors/:fingerprint" element={<ErrorTriageDetail />} />
                  <Route path="/admin/fleet" element={<Fleet />} />
                  <Route path="/admin/fleet/targeting" element={<FleetTargeting />} />
                  <Route path="/admin/fleet/maintenance" element={<MaintenanceWindows />} />
                  <Route path="/admin/fleet/rollouts/:rolloutId" element={<FleetRolloutDetail />} />
                </Route>
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
      </ToastProvider>
      </DialogProvider>
    </TooltipProvider>
  )
}

export default App
