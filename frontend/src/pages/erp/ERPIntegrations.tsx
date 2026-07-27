import { FC, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Brain, Plus, RefreshCw, Trash2, Zap, X, Database } from 'lucide-react'
import { Card, Badge, Button, Input, Select, Table, SkeletonTable } from '../../components'
import { erpApi, ERPIntegration, ERPIntegrationCreate } from '../../api/erp'
import { platformCorrelationApi } from '../../api/platformCorrelation'
import { analysisSessionsApi } from '../../api/analysisSessions'

const EMPTY_FORM: ERPIntegrationCreate = {
  integration_name: '',
  erp_type: 'sap',
  auth_type: 'oauth2',
  base_url: '',
  auth_config: {},
}

export const ERPIntegrationsPage: FC = () => {
  const qc = useQueryClient()
  const { data: integrations, isLoading } = useQuery({ queryKey: ['erp-integrations'], queryFn: () => erpApi.listIntegrations() })
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm] = useState<ERPIntegrationCreate>(EMPTY_FORM)
  const [authConfigText, setAuthConfigText] = useState('{}')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<Record<string, string>>({})

  const createMut = useMutation({
    mutationFn: (body: ERPIntegrationCreate) => erpApi.createIntegration(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['erp-integrations'] })
      setShowAdd(false)
      setForm(EMPTY_FORM)
      setAuthConfigText('{}')
    },
  })
  const deleteMut = useMutation({
    mutationFn: (id: string) => erpApi.deleteIntegration(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['erp-integrations'] }),
  })
  const testMut = useMutation({
    mutationFn: (id: string) => erpApi.testConnection(id),
    onSuccess: (res, id) => setTestResult((p) => ({ ...p, [id]: `${res.status}: ${res.message}` })),
  })
  const syncMut = useMutation({
    mutationFn: (id: string) => erpApi.triggerSync(id),
    onSuccess: (res, id) => setTestResult((p) => ({ ...p, [id]: res.message })),
  })

  // "Analyze": this integration's synced data becomes a Correlation AI source —
  // creates an analysis session and attaches the ERP entities; the session then
  // appears in the Correlation AI page where sensor/yard/transport sources can
  // be added and correlated against it.
  const analyzeMut = useMutation({
    mutationFn: async (it: ERPIntegration) => {
      const session = await analysisSessionsApi.createSession({
        title: `ERP analysis — ${it.integration_name}`,
      })
      const attached = await platformCorrelationApi.attach(session.id, 'erp', {
        integration_id: it.id,
      })
      return { session, attached }
    },
    onSuccess: ({ session, attached }, it) =>
      setTestResult((p) => ({
        ...p,
        [it.id]: `Attached ${attached.row_count} synced records to session "${session.title}" — open Correlation AI to analyze against sensors, yard, and shipments.`,
      })),
    onError: (e: any, it) =>
      setTestResult((p) => ({
        ...p,
        [it.id]: e?.response?.data?.detail || 'Failed to start analysis session',
      })),
  })

  const submit = () => {
    let auth_config: Record<string, any> = {}
    try {
      auth_config = JSON.parse(authConfigText || '{}')
    } catch {
      setTestResult((p) => ({ ...p, __form: 'auth_config is not valid JSON' }))
      return
    }
    createMut.mutate({ ...form, auth_config })
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-opsgrid-text">ERP Integrations</h1>
          <p className="text-opsgrid-text-secondary text-sm">
            Configure and monitor connections to SAP, Oracle, NetSuite, Dynamics, Odoo, Infor, Epicor.
          </p>
        </div>
        <Button onClick={() => setShowAdd(true)}>
          <Plus className="w-4 h-4 mr-1" /> Add Integration
        </Button>
      </div>

      {isLoading ? (
        <p className="text-opsgrid-text-secondary">Loading…</p>
      ) : (
        <div className="grid gap-4">
          {(integrations ?? []).map((it: ERPIntegration) => (
            <Card key={it.id} className="p-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <Database className="w-4 h-4 text-opsgrid-primary" />
                    <span className="font-semibold text-opsgrid-text">{it.integration_name}</span>
                    <Badge variant="info">{it.erp_type?.toUpperCase()}</Badge>
                    {it.is_active && <Badge variant="success">active</Badge>}
                  </div>
                  <div className="text-xs text-opsgrid-text-secondary mt-1">{it.base_url}</div>
                  <div className="text-xs text-opsgrid-text-secondary mt-1">
                    Last sync: {it.last_successful_sync ? new Date(it.last_successful_sync).toLocaleString() : 'never'}
                    {' · '}every {it.sync_frequency_minutes}m
                  </div>
                  {testResult[it.id] && (
                    <div className="text-xs mt-1 text-opsgrid-accent">{testResult[it.id]}</div>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => testMut.mutate(it.id)} disabled={testMut.isPending}>
                    <Zap className="w-3 h-3 mr-1" /> Test
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => syncMut.mutate(it.id)} disabled={syncMut.isPending}>
                    <RefreshCw className="w-3 h-3 mr-1" /> Sync
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => analyzeMut.mutate(it)} disabled={analyzeMut.isPending}>
                    <Brain className="w-3 h-3 mr-1" /> Analyze
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setSelectedId(selectedId === it.id ? null : it.id)}>
                    Status
                  </Button>
                  <Button size="sm" variant="danger" onClick={() => deleteMut.mutate(it.id)}>
                    <Trash2 className="w-3 h-3" />
                  </Button>
                </div>
              </div>
              {selectedId === it.id && <SyncStatusPanel id={it.id} />}
            </Card>
          ))}
          {(integrations ?? []).length === 0 && (
            <p className="text-opsgrid-text-secondary">No ERP integrations yet. Add one to get started.</p>
          )}
        </div>
      )}

      {showAdd && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" role="dialog" aria-modal="true">
          <Card className="w-[520px] max-w-[92vw] p-6 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-opsgrid-text">Add ERP Integration</h2>
              <button onClick={() => setShowAdd(false)} aria-label="Close"><X className="w-5 h-5" /></button>
            </div>
            <Input label="Name" value={form.integration_name}
              onChange={(e) => setForm({ ...form, integration_name: e.target.value })} />
            <div className="grid grid-cols-2 gap-3">
              <Select label="ERP type" value={form.erp_type}
                onChange={(e) => setForm({ ...form, erp_type: e.target.value })}
                options={erpApi.supportedTypes().map((t) => ({ value: t, label: t.toUpperCase() }))} />
              <Select label="Auth type" value={form.auth_type}
                onChange={(e) => setForm({ ...form, auth_type: e.target.value })}
                options={['oauth2', 'api_key', 'token', 'basic', 'certificate'].map((t) => ({ value: t, label: t }))} />
            </div>
            <Input label="Base URL" value={form.base_url}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
            <div>
              <label className="block text-sm font-medium text-opsgrid-text mb-1">Auth config (JSON)</label>
              <textarea className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-opsgrid-text font-mono text-xs"
                rows={4} value={authConfigText} onChange={(e) => setAuthConfigText(e.target.value)} />
            </div>
            {testResult.__form && <div className="text-xs text-status-alarm">{testResult.__form}</div>}
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowAdd(false)}>Cancel</Button>
              <Button onClick={submit} loading={createMut.isPending}>Create</Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}

type DetailTab = 'status' | 'entities' | 'events' | 'ai'

const TABS: { key: DetailTab; label: string }[] = [
  { key: 'status', label: 'Status' },
  { key: 'entities', label: 'Entities' },
  { key: 'events', label: 'Events' },
  { key: 'ai', label: 'AI' },
]

/**
 * Shown when more rows exist than were returned.
 *
 * These endpoints return at most `limit` rows, so a full page is indistinguishable from
 * the complete set — the shape that silently truncated three ERP connectors. The API
 * reports it in `X-Result-Truncated` and the client surfaces it as `truncated`; this is
 * where a person finally sees it. Without this the table below is a confident, partial
 * answer.
 */
const TruncationNotice: FC<{ shown: number; limit: number }> = ({ shown, limit }) => (
  <p className="text-xs text-opsgrid-warning mt-2" role="status">
    Showing the most recent {shown} of more than {limit}. Narrow the filter to see the rest.
  </p>
)

const EmptyOrError: FC<{ isError: boolean; empty: boolean; what: string }> = ({
  isError,
  empty,
  what,
}) =>
  isError ? (
    <p className="text-xs text-opsgrid-danger">Could not load {what}.</p>
  ) : empty ? (
    <p className="text-xs text-opsgrid-text-secondary">No {what} yet.</p>
  ) : null

const EntitiesTab: FC<{ id: string }> = ({ id }) => {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['erp-entities', id],
    queryFn: () => erpApi.listEntities(id),
  })
  if (isLoading) return <SkeletonTable />
  const items = data?.items ?? []
  return (
    <>
      <EmptyOrError isError={isError} empty={items.length === 0} what="synced entities" />
      {items.length > 0 && (
        <div className="overflow-x-auto">
          <Table>
            <Table.Head>
              <Table.Row>
                <Table.Header>Type</Table.Header>
                <Table.Header>ID</Table.Header>
                <Table.Header>Source</Table.Header>
                <Table.Header>Updated</Table.Header>
              </Table.Row>
            </Table.Head>
            <Table.Body>
              {items.map((e) => (
                <Table.Row key={e.id}>
                  <Table.Cell>{e.entity_type}</Table.Cell>
                  <Table.Cell>{e.entity_id}</Table.Cell>
                  <Table.Cell>{e.source_system}</Table.Cell>
                  <Table.Cell>{e.updated_at ? new Date(e.updated_at).toLocaleString() : '—'}</Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
        </div>
      )}
      {data?.truncated && <TruncationNotice shown={items.length} limit={data.limit} />}
    </>
  )
}

const EventsTab: FC<{ id: string }> = ({ id }) => {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['erp-events', id],
    queryFn: () => erpApi.listEvents(id),
  })
  if (isLoading) return <SkeletonTable />
  const items = data?.items ?? []
  return (
    <>
      <EmptyOrError isError={isError} empty={items.length === 0} what="inbound webhook events" />
      {items.map((ev) => (
        <div key={ev.id} className="text-xs flex justify-between py-1 border-b border-opsgrid-border">
          <span className="text-opsgrid-text">{ev.event_type}</span>
          <span className="text-opsgrid-text-secondary">
            <Badge variant={ev.processing_status === 'completed' ? 'success' : 'info'}>
              {ev.processing_status}
            </Badge>{' '}
            {ev.created_at ? new Date(ev.created_at).toLocaleString() : '—'}
          </span>
        </div>
      ))}
      {data?.truncated && <TruncationNotice shown={items.length} limit={data.limit} />}
    </>
  )
}

const CorrelationsTab: FC = () => {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['erp-correlations'],
    queryFn: () => erpApi.listCorrelations(),
  })
  if (isLoading) return <SkeletonTable />
  const items = data?.items ?? []
  return (
    <>
      <EmptyOrError isError={isError} empty={items.length === 0} what="correlations" />
      {items.map((c) => (
        <div key={c.id} className="text-xs flex justify-between py-1 border-b border-opsgrid-border">
          <span className="text-opsgrid-text">{c.correlation_type}</span>
          <span className="text-opsgrid-text-secondary">
            {c.correlation_score !== null && c.correlation_score !== undefined
              ? c.correlation_score.toFixed(2)
              : '—'}{' '}
            · {c.created_at ? new Date(c.created_at).toLocaleString() : '—'}
          </span>
        </div>
      ))}
      {data?.truncated && <TruncationNotice shown={items.length} limit={data.limit} />}
    </>
  )
}

const StatusTab: FC<{ id: string }> = ({ id }) => {
  const { data: statuses } = useQuery({ queryKey: ['erp-sync-status', id], queryFn: () => erpApi.getSyncStatus(id) })
  const { data: mappings } = useQuery({ queryKey: ['erp-mappings', id], queryFn: () => erpApi.listFieldMappings(id) })
  return (
    <div className="grid md:grid-cols-2 gap-4">
      <div>
        <h3 className="text-sm font-semibold text-opsgrid-text mb-2">Sync status</h3>
        {(statuses ?? []).length === 0 ? (
          <p className="text-xs text-opsgrid-text-secondary">No syncs recorded yet.</p>
        ) : (
          (statuses ?? []).map((s) => (
            <div key={s.entity_type} className="text-xs flex justify-between py-1">
              <span className="text-opsgrid-text">{s.entity_type}</span>
              <span className="text-opsgrid-text-secondary">
                <Badge variant={s.last_sync_status === 'success' ? 'success' : 'error'}>{s.last_sync_status}</Badge>
                {' '}{s.records_synced ?? 0}✓ {s.records_failed ?? 0}✗
              </span>
            </div>
          ))
        )}
      </div>
      <div>
        <h3 className="text-sm font-semibold text-opsgrid-text mb-2">Field mappings</h3>
        {(mappings ?? []).length === 0 ? (
          <p className="text-xs text-opsgrid-text-secondary">No mappings configured.</p>
        ) : (
          (mappings ?? []).map((m) => (
            <div key={m.id} className="text-xs text-opsgrid-text-secondary py-1">
              {m.source_entity}.{m.source_field} → {m.target_entity}.{m.target_field}
            </div>
          ))
        )}
      </div>
    </div>
  )
}

const SyncStatusPanel: FC<{ id: string }> = ({ id }) => {
  const [tab, setTab] = useState<DetailTab>('status')
  return (
    <div className="mt-4 border-t border-opsgrid-border pt-3">
      <div className="flex gap-1 mb-3" role="tablist" aria-label="Integration detail">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-1 text-xs rounded ${
              tab === t.key
                ? 'bg-opsgrid-primary text-white'
                : 'text-opsgrid-text-secondary hover:text-opsgrid-text'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === 'status' && <StatusTab id={id} />}
        {tab === 'entities' && <EntitiesTab id={id} />}
        {tab === 'events' && <EventsTab id={id} />}
        {tab === 'ai' && <CorrelationsTab />}
      </div>
    </div>
  )
}

export default ERPIntegrationsPage
