import { FC, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from 'react-query'
import { Link } from 'react-router-dom'
import {
  Brain, Database, FileText, GitMerge, RefreshCw, Settings, Zap,
} from 'lucide-react'
import { Badge, Button, Card } from '../../components'
import { erpApi, ERPEntity, ERPIntegration } from '../../api/erp'
import { platformCorrelationApi } from '../../api/platformCorrelation'
import { analysisSessionsApi } from '../../api/analysisSessions'

// ERP Hub (top-level page): the operational ERP surface. Config lives in
// /admin/erp; this page is about the DATA — synced business entities, the
// live event feed, and first-class wiring into the AI correlation engine
// (attach ERP entities to an analysis session and correlate them against
// sensor / yard / transportation data).

type Tab = 'overview' | 'entities' | 'events' | 'ai'

export const ERPHubPage: FC = () => {
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('overview')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [status, setStatus] = useState<Record<string, string>>({})

  const { data: integrations } = useQuery('erp-integrations', () => erpApi.listIntegrations())
  const active = integrations?.find((i) => i.id === selectedId) ?? integrations?.[0]

  const testMut = useMutation((id: string) => erpApi.testConnection(id), {
    onSuccess: (res, id) => setStatus((p) => ({ ...p, [id]: `${res.status}: ${res.message}` })),
  })
  const syncMut = useMutation((id: string) => erpApi.triggerSync(id), {
    onSuccess: (res, id) => {
      setStatus((p) => ({ ...p, [id]: res.message }))
      qc.invalidateQueries(['erp-entities'])
    },
  })

  const TABS: Array<{ id: Tab; label: string; icon: any }> = [
    { id: 'overview', label: 'Overview', icon: Database },
    { id: 'entities', label: 'Entities', icon: FileText },
    { id: 'events', label: 'Events', icon: Zap },
    { id: 'ai', label: 'AI & Correlation', icon: Brain },
  ]

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-opsgrid-text">ERP</h1>
          <p className="text-opsgrid-text-secondary text-sm">
            Synced business data from your ERP systems, wired into correlation and analysis.
          </p>
        </div>
        <Link to="/admin/erp"
          className="flex items-center gap-2 px-3 py-2 text-sm border border-opsgrid-border rounded-lg text-opsgrid-text-secondary hover:text-opsgrid-text">
          <Settings className="w-4 h-4" /> Configure integrations
        </Link>
      </div>

      {/* Tabs */}
      <div className="border-b border-opsgrid-border flex gap-1">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 px-4 py-2 border-b-2 transition-colors ${
              tab === t.id ? 'border-opsgrid-primary text-opsgrid-primary'
                : 'border-transparent text-opsgrid-text-secondary hover:text-opsgrid-text'
            }`}>
            <t.icon className="w-4 h-4" /> {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <OverviewTab
          integrations={integrations ?? []}
          status={status}
          onTest={(id) => testMut.mutate(id)}
          onSync={(id) => syncMut.mutate(id)}
          busy={testMut.isLoading || syncMut.isLoading}
        />
      )}
      {tab === 'entities' && active && <EntitiesTab integration={active} onPick={setSelectedId} integrations={integrations ?? []} />}
      {tab === 'events' && active && <EventsTab integration={active} />}
      {tab === 'ai' && <AICorrelationTab integrations={integrations ?? []} />}
      {(tab === 'entities' || tab === 'events') && !active && (
        <p className="text-opsgrid-text-secondary text-sm">
          No ERP integrations yet — <Link to="/admin/erp" className="text-opsgrid-primary hover:underline">configure one</Link>.
        </p>
      )}
    </div>
  )
}

const OverviewTab: FC<{
  integrations: ERPIntegration[]
  status: Record<string, string>
  onTest: (id: string) => void
  onSync: (id: string) => void
  busy: boolean
}> = ({ integrations, status, onTest, onSync, busy }) => (
  <div className="grid gap-4">
    {integrations.map((it) => (
      <Card key={it.id} className="p-4" data-testid={`erp-card-${it.id}`}>
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Database className="w-4 h-4 text-opsgrid-primary" />
              <span className="font-semibold text-opsgrid-text">{it.integration_name}</span>
              <Badge variant="info">{it.erp_type.toUpperCase()}</Badge>
              {it.is_active && <Badge variant="success">active</Badge>}
            </div>
            <div className="text-xs text-opsgrid-text-secondary mt-1">
              Last sync: {it.last_successful_sync ? new Date(it.last_successful_sync).toLocaleString() : 'never'}
              {' · '}every {it.sync_frequency_minutes}m
            </div>
            {status[it.id] && <div className="text-xs mt-1 text-opsgrid-accent">{status[it.id]}</div>}
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => onTest(it.id)} disabled={busy}>
              <Zap className="w-3 h-3 mr-1" /> Test
            </Button>
            <Button size="sm" variant="outline" onClick={() => onSync(it.id)} disabled={busy}>
              <RefreshCw className="w-3 h-3 mr-1" /> Sync now
            </Button>
          </div>
        </div>
      </Card>
    ))}
    {integrations.length === 0 && (
      <p className="text-opsgrid-text-secondary text-sm">
        No ERP integrations yet — <Link to="/admin/erp" className="text-opsgrid-primary hover:underline">configure one</Link>.
      </p>
    )}
  </div>
)

const EntitiesTab: FC<{
  integration: ERPIntegration
  integrations: ERPIntegration[]
  onPick: (id: string) => void
}> = ({ integration, integrations, onPick }) => {
  const [entityType, setEntityType] = useState('')
  const { data: entities, isLoading } = useQuery(
    ['erp-entities', integration.id, entityType],
    () => erpApi.listEntities(integration.id, entityType || undefined)
  )
  const types = Array.from(new Set((entities ?? []).map((e) => e.entity_type)))

  return (
    <div className="space-y-3">
      <div className="flex gap-2 items-center">
        <select aria-label="Integration" value={integration.id} onChange={(e) => onPick(e.target.value)}
          className="text-sm px-2 py-1.5 bg-opsgrid-panel border border-opsgrid-border rounded text-opsgrid-text">
          {integrations.map((i) => <option key={i.id} value={i.id}>{i.integration_name}</option>)}
        </select>
        <select aria-label="Entity type" value={entityType} onChange={(e) => setEntityType(e.target.value)}
          className="text-sm px-2 py-1.5 bg-opsgrid-panel border border-opsgrid-border rounded text-opsgrid-text">
          <option value="">All entity types</option>
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      {isLoading ? <p className="text-sm text-opsgrid-text-secondary">Loading…</p> : (
        <div className="grid gap-2">
          {(entities ?? []).map((e: ERPEntity) => (
            <Card key={e.id} className="p-3" data-testid={`entity-${e.entity_id}`}>
              <div className="flex items-center gap-2 text-sm">
                <Badge variant="info">{e.entity_type}</Badge>
                <span className="font-semibold text-opsgrid-text">{e.entity_id}</span>
                <span className="text-xs text-opsgrid-text-secondary">via {e.source_system}</span>
                <span className="ml-auto text-xs text-opsgrid-text-secondary">
                  {e.updated_at ? new Date(e.updated_at).toLocaleString() : ''}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-opsgrid-text-secondary">
                {Object.entries(e.entity_data).slice(0, 6).map(([k, v]) => (
                  <span key={k}><span className="opacity-70">{k}:</span> {String(v)}</span>
                ))}
              </div>
            </Card>
          ))}
          {(entities ?? []).length === 0 && (
            <p className="text-sm text-opsgrid-text-secondary">No synced entities yet — run a sync from Overview.</p>
          )}
        </div>
      )}
    </div>
  )
}

const EventsTab: FC<{ integration: ERPIntegration }> = ({ integration }) => {
  const { data: events, isLoading } = useQuery(['erp-events', integration.id], () => erpApi.listEvents(integration.id))
  return isLoading ? <p className="text-sm text-opsgrid-text-secondary">Loading…</p> : (
    <div className="grid gap-2">
      {(events ?? []).map((ev) => (
        <Card key={ev.id} className="p-3 flex items-center gap-3 text-sm" data-testid={`event-${ev.event_id}`}>
          <Badge variant={ev.processing_status === 'completed' ? 'success' : ev.processing_status === 'failed' ? 'error' : 'default'}>
            {ev.processing_status}
          </Badge>
          <span className="font-semibold text-opsgrid-text">{ev.event_type}</span>
          <span className="text-opsgrid-text-secondary">{ev.entity_type} {ev.entity_id ?? ''}</span>
          <span className="ml-auto text-xs text-opsgrid-text-secondary">
            {ev.created_at ? new Date(ev.created_at).toLocaleString() : ''}
          </span>
        </Card>
      ))}
      {(events ?? []).length === 0 && (
        <p className="text-sm text-opsgrid-text-secondary">No events received yet (webhooks land here).</p>
      )}
    </div>
  )
}

const AICorrelationTab: FC<{ integrations: ERPIntegration[] }> = ({ integrations }) => {
  const [entityType, setEntityType] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const { data: correlations } = useQuery('erp-correlations', () => erpApi.listCorrelations())

  // One-click: create an analysis session seeded with ERP entities as a
  // correlation source — the session then shows up in the Correlation AI page
  // where sensor/yard/transport sources can be added and correlated.
  const sendToCorrelation = async () => {
    setBusy(true)
    setResult(null)
    try {
      const session = await analysisSessionsApi.createSession({
        title: `ERP analysis — ${entityType || 'all entities'}`,
      })
      const attached = await platformCorrelationApi.attach(
        session.id, 'erp', entityType ? { entity_type: entityType } : {}
      )
      setResult(`Created session "${session.title}" with ${attached.row_count} ERP records attached. Open Correlation AI to add sensor/yard/transport sources and correlate.`)
    } catch (e: any) {
      setResult(e?.response?.data?.detail || 'Failed to create analysis session')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <Card className="p-4" data-testid="erp-ai-panel">
        <h3 className="font-semibold text-opsgrid-text flex items-center gap-2 mb-2">
          <Brain className="w-4 h-4 text-opsgrid-primary" /> Analyze ERP data with Correlation AI
        </h3>
        <p className="text-sm text-opsgrid-text-secondary mb-3">
          Attach synced ERP entities (orders, invoices, work orders) to an analysis session as a
          correlation source. The engine auto-detects shared keys against sensor telemetry, yard
          inventory, and shipments — linking business events to what physically happened.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            aria-label="Entity type filter"
            placeholder="entity type (optional, e.g. PurchaseOrder)"
            className="text-sm px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-opsgrid-text w-72"
            value={entityType}
            onChange={(e) => setEntityType(e.target.value)}
          />
          <Button onClick={sendToCorrelation} loading={busy}>
            <GitMerge className="w-4 h-4 mr-1" /> Send to Correlation AI
          </Button>
          <Link to="/nlp" className="text-sm text-opsgrid-primary hover:underline">Open Correlation AI →</Link>
        </div>
        {result && <p className="text-sm mt-3 text-opsgrid-accent" data-testid="ai-result">{result}</p>}
        <p className="text-xs text-opsgrid-text-secondary mt-3">
          ERP data also feeds the platform's predictive surfaces: work orders and PO timing become
          correlation dimensions for asset health, predictive maintenance, and what-if simulation.
        </p>
      </Card>

      <div>
        <h3 className="font-semibold text-opsgrid-text mb-2">Recorded ERP ↔ sensor correlations</h3>
        <div className="grid gap-2">
          {(correlations ?? []).map((c) => (
            <Card key={c.id} className="p-3 flex items-center gap-3 text-sm">
              <Badge variant="info">{c.correlation_type}</Badge>
              <span className="text-opsgrid-text-secondary">{c.sensor_event_id}</span>
              {c.correlation_score != null && (
                <span className="ml-auto font-semibold text-opsgrid-text">
                  score {(c.correlation_score * 100).toFixed(0)}%
                </span>
              )}
            </Card>
          ))}
          {(correlations ?? []).length === 0 && (
            <p className="text-sm text-opsgrid-text-secondary">
              No ERP↔sensor correlations recorded yet — they appear here as syncs/webhooks land and
              the correlation engine links them to telemetry.
            </p>
          )}
        </div>
      </div>

      {integrations.length === 0 && (
        <p className="text-sm text-opsgrid-text-secondary">
          Configure an ERP integration first — <Link to="/admin/erp" className="text-opsgrid-primary hover:underline">/admin/erp</Link>.
        </p>
      )}
    </div>
  )
}

export default ERPHubPage
