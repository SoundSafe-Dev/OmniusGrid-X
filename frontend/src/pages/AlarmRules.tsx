import { FC, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Pencil, Trash2, SlidersHorizontal } from 'lucide-react'
import { alarmRulesApi } from '../api/alarmRules'
import { assetsApi, workcellsApi } from '../api'
import { Button, Input, Modal, Select, useDialog } from '../components/ui'
import {
  AlarmComparator,
  AlarmRule,
  AlarmRuleCreate,
  AlarmSeverity,
} from '../types'

/**
 * Alarm rule management (FS-220).
 *
 * This page is the reason the alarm widgets elsewhere mean anything. Severity used
 * to be whatever the edge agent sent, and nothing on the server evaluated
 * telemetry, so "alert when temperature is over 80 for 5 minutes" could not be
 * expressed at all. Rules defined here are evaluated in the ingestion path.
 */

const COMPARATORS: { value: AlarmComparator; label: string }[] = [
  { value: 'gt', label: 'is above (>)' },
  { value: 'gte', label: 'is at or above (>=)' },
  { value: 'lt', label: 'is below (<)' },
  { value: 'lte', label: 'is at or below (<=)' },
  { value: 'eq', label: 'equals (==)' },
  { value: 'ne', label: 'does not equal (!=)' },
]

const SEVERITIES: { value: AlarmSeverity; label: string }[] = [
  { value: 'critical', label: 'Critical' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
  { value: 'info', label: 'Info' },
]

const COMPARATOR_SYMBOL: Record<AlarmComparator, string> = {
  gt: '>',
  gte: '>=',
  lt: '<',
  lte: '<=',
  eq: '==',
  ne: '!=',
}

const RULES_QUERY_KEY = 'alarm-rules'

// Severity chips reuse the same tokens as the Alarms page so one severity never
// reads as two different colours across the product.
function severityClass(severity: string): string {
  switch (severity) {
    case 'critical':
      return 'bg-status-alarm text-white'
    case 'high':
      return 'bg-status-warning text-opsgrid-bg'
    case 'medium':
      return 'bg-packml-held text-opsgrid-bg'
    default:
      return 'bg-opsgrid-text-secondary text-opsgrid-bg'
  }
}

function formatDuration(seconds: number): string {
  if (!seconds) return 'immediately'
  if (seconds % 3600 === 0) return `for ${seconds / 3600}h`
  if (seconds % 60 === 0) return `for ${seconds / 60}m`
  return `for ${seconds}s`
}

type ScopeKind = 'org' | 'asset' | 'assetType' | 'workcell'

/** Which scope a stored rule carries. A rule can only have one in practice — the form
 *  enforces that — but the read is defensive: a rule written before this UI existed, or
 *  by the API directly, could name more than one. */
const scopeOf = (rule: { assetId?: string | null; assetTypeId?: string | null; workcellId?: string | null }): ScopeKind =>
  rule.assetId ? 'asset' : rule.assetTypeId ? 'assetType' : rule.workcellId ? 'workcell' : 'org'

/** What a rule's scope should READ as in the table. Falls back to the raw id when the
 *  name lists have not loaded or the target has since been deleted — an id is ugly and
 *  true, where a blank cell would read as "applies everywhere", which is the one thing
 *  it definitely does not mean. */
const scopeLabel = (
  rule: { assetId?: string | null; assetTypeId?: string | null; workcellId?: string | null },
  assets?: Array<{ id: string; name: string }>,
  assetTypes?: Array<{ id: string; name: string }>,
  workcells?: Array<{ id: string; name: string }>,
): string => {
  const named = (id: string, list?: Array<{ id: string; name: string }>) =>
    list?.find((entry) => entry.id === id)?.name ?? id
  if (rule.assetId) return named(rule.assetId, assets)
  if (rule.assetTypeId) return `All ${named(rule.assetTypeId, assetTypes)}`
  if (rule.workcellId) return `Workcell: ${named(rule.workcellId, workcells)}`
  return 'Every asset'
}

const EMPTY_FORM: AlarmRuleCreate = {
  name: '',
  description: null,
  metricName: '',
  comparator: 'gt',
  threshold: 0,
  durationSeconds: 0,
  hysteresis: 0,
  severity: 'high',
  alarmCode: '',
  messageTemplate: null,
  assetId: null,
  assetTypeId: null,
  workcellId: null,
  isEnabled: true,
}

const AlarmRules: FC = () => {
  const queryClient = useQueryClient()
  const { confirm, alert } = useDialog()

  const [severityFilter, setSeverityFilter] = useState<string>('')
  const [enabledFilter, setEnabledFilter] = useState<string>('')
  const [editing, setEditing] = useState<AlarmRule | null>(null)
  const [isFormOpen, setFormOpen] = useState(false)
  const [form, setForm] = useState<AlarmRuleCreate>(EMPTY_FORM)
  const [scopeKind, setScopeKind] = useState<ScopeKind>('org')
  const [formError, setFormError] = useState<string | null>(null)

  // Scope options. Loaded once for the modal; a rule's scope is chosen from what the
  // organization actually has, not typed as a UUID.
  const { data: assets } = useQuery({
    queryKey: ['alarm-rule-assets'],
    queryFn: () => assetsApi.list({ limit: 200 }),
  })
  const { data: assetTypes } = useQuery({
    queryKey: ['alarm-rule-asset-types'],
    queryFn: () => assetsApi.getTypes(),
  })
  const { data: workcells } = useQuery({
    queryKey: ['alarm-rule-workcells'],
    queryFn: () => workcellsApi.list(),
  })

  const filters = useMemo(
    () => ({
      severity: (severityFilter || undefined) as AlarmSeverity | undefined,
      isEnabled: enabledFilter === '' ? undefined : enabledFilter === 'true',
    }),
    [severityFilter, enabledFilter],
  )

  const { data, isLoading, isError } = useQuery({
    queryKey: [RULES_QUERY_KEY, filters],
    queryFn: () => alarmRulesApi.list(filters),
  })

  const rules = data?.items ?? []

  const invalidate = () => queryClient.invalidateQueries({ queryKey: [RULES_QUERY_KEY] })

  const createMutation = useMutation({
    mutationFn: (payload: AlarmRuleCreate) => alarmRulesApi.create(payload),
    onSuccess: () => {
      invalidate()
      setFormOpen(false)
    },
    onError: (err: Error) => setFormError(err.message || 'Could not save the rule'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<AlarmRuleCreate> }) =>
      alarmRulesApi.update(id, payload),
    onSuccess: () => {
      invalidate()
      setFormOpen(false)
    },
    onError: (err: Error) => setFormError(err.message || 'Could not save the rule'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => alarmRulesApi.remove(id),
    onSuccess: invalidate,
  })

  const openCreate = () => {
    setEditing(null)
    setForm(EMPTY_FORM)
    setScopeKind('org')
    setFormError(null)
    setFormOpen(true)
  }

  const openEdit = (rule: AlarmRule) => {
    setEditing(rule)
    setScopeKind(scopeOf(rule))
    setForm({
      name: rule.name,
      description: rule.description ?? null,
      metricName: rule.metricName,
      comparator: rule.comparator,
      threshold: rule.threshold,
      durationSeconds: rule.durationSeconds,
      hysteresis: rule.hysteresis,
      severity: rule.severity,
      alarmCode: rule.alarmCode,
      messageTemplate: rule.messageTemplate ?? null,
      assetId: rule.assetId ?? null,
      assetTypeId: rule.assetTypeId ?? null,
      workcellId: rule.workcellId ?? null,
      isEnabled: rule.isEnabled,
    })
    setFormError(null)
    setFormOpen(true)
  }

  const submit = () => {
    // Validated here as well as server-side so the operator gets the message next
    // to the field instead of a 422 they have to interpret.
    if (!form.name.trim()) return setFormError('Name is required')
    if (!form.metricName.trim()) return setFormError('Metric is required')
    if (!form.alarmCode.trim()) return setFormError('Alarm code is required')
    if (Number.isNaN(form.threshold)) return setFormError('Threshold must be a number')
    setFormError(null)

    if (editing) {
      updateMutation.mutate({ id: editing.id, payload: form })
    } else {
      createMutation.mutate(form)
    }
  }

  const toggleEnabled = (rule: AlarmRule) => {
    // Only isEnabled is sent: PATCH semantics mean the rest of the rule is left
    // untouched rather than reset to whatever this page last rendered.
    updateMutation.mutate({ id: rule.id, payload: { isEnabled: !rule.isEnabled } })
  }

  const remove = async (rule: AlarmRule) => {
    const ok = await confirm({
      title: `Delete "${rule.name}"?`,
      message:
        'The rule stops being evaluated. Alarms it already raised are kept — they are separate records.',
      destructive: true,
      confirmLabel: 'Delete rule',
    })
    if (!ok) return
    try {
      await deleteMutation.mutateAsync(rule.id)
    } catch (err) {
      await alert({
        title: 'Could not delete the rule',
        message: err instanceof Error ? err.message : 'Unexpected error',
      })
    }
  }

  return (
    <div className="p-6">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-opsgrid-text">Alarm Rules</h1>
          <p className="text-sm text-opsgrid-text-secondary mt-1">
            Thresholds evaluated against incoming telemetry. A rule with a duration
            only fires once the breach has persisted for that long.
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus size={16} className="mr-1" aria-hidden="true" />
          New rule
        </Button>
      </div>

      <div className="flex flex-wrap gap-3 mb-4 items-end">
        <Select
          label="Severity"
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          placeholder="All severities"
          options={SEVERITIES}
        />
        <Select
          label="State"
          value={enabledFilter}
          onChange={(e) => setEnabledFilter(e.target.value)}
          placeholder="All states"
          options={[
            { value: 'true', label: 'Enabled' },
            { value: 'false', label: 'Disabled' },
          ]}
        />
      </div>

      {isLoading && (
        <div className="text-opsgrid-text-secondary" role="status">
          Loading rules…
        </div>
      )}

      {isError && !isLoading && (
        <div
          role="alert"
          className="bg-opsgrid-panel border border-status-alarm rounded-lg p-4 text-opsgrid-text"
        >
          Could not load alarm rules. Retry, or check that the backend is reachable.
        </div>
      )}

      {!isLoading && !isError && rules.length === 0 && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-8 text-center">
          <SlidersHorizontal
            className="mx-auto mb-3 text-opsgrid-text-secondary"
            size={28}
            aria-hidden="true"
          />
          <p className="text-opsgrid-text font-medium">No alarm rules yet</p>
          <p className="text-sm text-opsgrid-text-secondary mt-1">
            Without a rule, alarms only appear when an edge agent decides to send
            one. Add a threshold to have the server raise them from telemetry.
          </p>
        </div>
      )}

      {!isLoading && !isError && rules.length > 0 && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Configured alarm rules</caption>
            <thead>
              <tr className="text-left text-opsgrid-text-secondary border-b border-opsgrid-border">
                <th scope="col" className="px-4 py-3">Name</th>
                <th scope="col" className="px-4 py-3">Condition</th>
                <th scope="col" className="px-4 py-3">Scope</th>
                <th scope="col" className="px-4 py-3">Severity</th>
                <th scope="col" className="px-4 py-3">Code</th>
                <th scope="col" className="px-4 py-3">State</th>
                <th scope="col" className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr key={rule.id} className="border-b border-opsgrid-border last:border-0">
                  <td className="px-4 py-3">
                    <div className="text-opsgrid-text font-medium">{rule.name}</div>
                    {rule.description && (
                      <div className="text-opsgrid-text-secondary text-xs mt-0.5">
                        {rule.description}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-opsgrid-text">
                    <span className="font-mono">
                      {rule.metricName} {COMPARATOR_SYMBOL[rule.comparator]} {rule.threshold}
                    </span>
                    <span className="text-opsgrid-text-secondary">
                      {' '}
                      {formatDuration(rule.durationSeconds)}
                    </span>
                  </td>
                  {/* SCOPE, VISIBLE WITHOUT OPENING THE RULE (P10). Every rule was
                      org-wide before the form could set a scope, so a column would have
                      read "Everything" all the way down; now that rules can be targeted,
                      a list that hides the target is a list of rules you have to open one
                      by one to understand. */}
                  <td className="px-4 py-3 text-opsgrid-text-secondary">
                    {scopeLabel(rule, assets?.items, assetTypes, workcells)}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium ${severityClass(rule.severity)}`}
                    >
                      {rule.severity}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-opsgrid-text-secondary">
                    {rule.alarmCode}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      onClick={() => toggleEnabled(rule)}
                      className="text-xs underline text-opsgrid-text-secondary hover:text-opsgrid-text"
                    >
                      {rule.isEnabled ? 'Enabled' : 'Disabled'}
                    </button>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => openEdit(rule)}
                        aria-label={`Edit ${rule.name}`}
                        className="p-1 text-opsgrid-text-secondary hover:text-opsgrid-text"
                      >
                        <Pencil size={16} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        onClick={() => remove(rule)}
                        aria-label={`Delete ${rule.name}`}
                        className="p-1 text-opsgrid-text-secondary hover:text-status-alarm"
                      >
                        <Trash2 size={16} aria-hidden="true" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        isOpen={isFormOpen}
        onClose={() => setFormOpen(false)}
        title={editing ? `Edit ${editing.name}` : 'New alarm rule'}
      >
        <div className="space-y-4">
          {formError && (
            <div role="alert" className="text-sm text-status-alarm">
              {formError}
            </div>
          )}

          <Input
            label="Name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />

          <div className="grid grid-cols-3 gap-3">
            <Input
              label="Metric"
              value={form.metricName}
              onChange={(e) => setForm({ ...form, metricName: e.target.value })}
              helperText="e.g. temperature"
            />
            <Select
              label="Condition"
              value={form.comparator}
              onChange={(e) =>
                setForm({ ...form, comparator: e.target.value as AlarmComparator })
              }
              options={COMPARATORS}
            />
            <Input
              label="Threshold"
              type="number"
              value={String(form.threshold)}
              onChange={(e) => setForm({ ...form, threshold: Number(e.target.value) })}
            />
          </div>

          {/* SCOPE (P10, page-enhancement review). `assetId`, `assetTypeId` and
              `workcellId` have been in EMPTY_FORM and copied on edit since this page was
              written, and NO INPUT EVER SET THEM — so every rule was org-wide and the
              backend's `_validate_targets` (which exists to reject another tenant's
              asset id) was unreachable from the UI. A threshold that suits a press is
              rarely the one that suits an oven, so the practical effect was rules
              written for the loosest machine on the floor.

              One scope at a time, and the backend agrees: `_validate_targets` checks
              each independently, but a rule naming both an asset and a workcell reads
              as an intersection nobody defines. Choosing one clears the others. */}
          <div className="grid grid-cols-2 gap-3">
            <Select
              label="Applies to"
              value={scopeKind}
              onChange={(e) => {
                const kind = e.target.value as ScopeKind
                setScopeKind(kind)
                setForm({ ...form, assetId: null, assetTypeId: null, workcellId: null })
              }}
              options={[
                { value: 'org', label: 'Every asset in the organization' },
                { value: 'asset', label: 'One asset' },
                { value: 'assetType', label: 'An asset type' },
                { value: 'workcell', label: 'A workcell' },
              ]}
            />
            {scopeKind === 'asset' && (
              <Select
                label="Asset"
                value={form.assetId ?? ''}
                onChange={(e) => setForm({ ...form, assetId: e.target.value || null })}
                options={[
                  { value: '', label: 'Select an asset…' },
                  ...(assets?.items ?? []).map((asset: any) => ({
                    value: asset.id,
                    label: asset.name,
                  })),
                ]}
              />
            )}
            {scopeKind === 'assetType' && (
              <Select
                label="Asset type"
                value={form.assetTypeId ?? ''}
                onChange={(e) => setForm({ ...form, assetTypeId: e.target.value || null })}
                options={[
                  { value: '', label: 'Select a type…' },
                  ...(assetTypes ?? []).map((assetType: any) => ({
                    value: assetType.id,
                    label: assetType.name,
                  })),
                ]}
              />
            )}
            {scopeKind === 'workcell' && (
              <Select
                label="Workcell"
                value={form.workcellId ?? ''}
                onChange={(e) => setForm({ ...form, workcellId: e.target.value || null })}
                options={[
                  { value: '', label: 'Select a workcell…' },
                  ...(workcells ?? []).map((workcell: any) => ({
                    value: workcell.id,
                    label: workcell.name,
                  })),
                ]}
              />
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Duration (seconds)"
              type="number"
              min={0}
              value={String(form.durationSeconds)}
              onChange={(e) =>
                setForm({ ...form, durationSeconds: Number(e.target.value) })
              }
              helperText="0 fires on the first breaching reading"
            />
            <Input
              label="Hysteresis"
              type="number"
              min={0}
              value={String(form.hysteresis)}
              onChange={(e) => setForm({ ...form, hysteresis: Number(e.target.value) })}
              helperText="Clear band — stops flapping on the threshold"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Select
              label="Severity"
              value={form.severity}
              onChange={(e) =>
                setForm({ ...form, severity: e.target.value as AlarmSeverity })
              }
              options={SEVERITIES}
            />
            <Input
              label="Alarm code"
              value={form.alarmCode}
              onChange={(e) => setForm({ ...form, alarmCode: e.target.value })}
              helperText="Stamped on alarms this rule raises"
            />
          </div>

          <Input
            label="Message template (optional)"
            value={form.messageTemplate ?? ''}
            onChange={(e) =>
              setForm({ ...form, messageTemplate: e.target.value || null })
            }
            helperText="Supports {metricName}, {value}, {threshold}"
          />

          <label className="flex items-center gap-2 text-sm text-opsgrid-text">
            <input
              type="checkbox"
              checked={form.isEnabled}
              onChange={(e) => setForm({ ...form, isEnabled: e.target.checked })}
            />
            Enabled
          </label>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setFormOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={submit}
              disabled={createMutation.isPending || updateMutation.isPending}
            >
              {editing ? 'Save changes' : 'Create rule'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

export default AlarmRules
