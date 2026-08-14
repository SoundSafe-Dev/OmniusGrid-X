import { FC, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, HardDrive } from 'lucide-react';
import { Badge, Button, Card, Input, Select, SkeletonCard } from '../../components';
import { Tooltip, TooltipContent, TooltipTrigger } from '../../components/ui';
import { api } from '../../api';
import { formatDateTime, formatNumber } from '../../utils/formatters';

interface EdgeAgent {
  agent_id: string;
  liveness: string;
  last_seen: string | null;
  buffer_pending: number;
  dead_lettered: number;
  /** TELEMETRY THE AGENT DISCARDED — and this interface omitted it (P12).
   *
   *  FS-591 traced this figure the whole way: the agent counts dropped readings, sends
   *  them every heartbeat, the handler writes `edge_agent_status.dropped`, and
   *  `AgentStatusOut` was given the field precisely so a fleet view could show it. The
   *  fleet view then declared an interface without it, so the number arrived and was
   *  discarded one layer later — the same omission, one boundary further on.
   *
   *  Of the three buffer figures it is the only unrecoverable one: `buffer_pending` is
   *  waiting to send, `dead_lettered` is replayable, this is gone. */
  dropped: number;
  active_collectors: number;
  total_collectors: number;
  cert_expires_in_seconds: number | null;
}

/** Certificate expiry thresholds, matching the alert rules so the page and the pager
 *  agree: EdgeAgentCertExpiringSoon fires under 2 days (high),
 *  EdgeAgentCertExpiryApproaching under 14 (warning). A cert that expires stops an
 *  agent dead, and this was previously visible only on hover. */
const CERT_CRITICAL_DAYS = 2;
const CERT_WARNING_DAYS = 14;

export const CollectorsPage: FC = () => {
  const { data: agents, isLoading, isError } = useQuery({
    queryKey: ['edge-fleet'],
    queryFn: async () => {
      const res = await api.get<EdgeAgent[]>('/api/v1/edge/fleet');
      return res.data;
    },
    refetchInterval: 30_000, // liveness must refresh, not freeze at mount
  });

  const livenessVariant = (l: string): 'success' | 'warning' | 'error' =>
    l === 'live' || l === 'online' ? 'success' : l === 'stale' ? 'warning' : 'error';

  // WORST FIRST (P12). A fleet list in arbitrary order makes the offline agent the
  // reader's job to find; the one an admin opened this page for should be at the top.
  // Offline before stale before online, then by cert urgency, then by name so the
  // order is stable between refreshes rather than reshuffling every 30 seconds.
  const rank = (agent: EdgeAgent): number => {
    if (agent.liveness === 'offline') return 0;
    if (agent.liveness === 'stale') return 1;
    return 2;
  };
  const certDays = (agent: EdgeAgent): number =>
    agent.cert_expires_in_seconds == null
      ? Number.POSITIVE_INFINITY
      : agent.cert_expires_in_seconds / 86400;
  const ordered = [...(agents ?? [])].sort(
    (a, b) =>
      rank(a) - rank(b) ||
      certDays(a) - certDays(b) ||
      a.agent_id.localeCompare(b.agent_id),
  );

  return (
    <div className="space-y-6">
      <Card title="Edge Agents" subtitle="Live data-collection agents reporting via heartbeat">
        {isLoading ? (
          <SkeletonCard />
        ) : isError ? (
          /* The empty state below EXPLAINS itself — "agents appear here once they enroll
             and send a heartbeat" — which is a confident account of why the list is
             empty, and simply wrong when the request failed. On error `agents` is
             undefined, so `!agents` sent every failure straight into that sentence. */
          <p className="text-sm text-status-alarm" role="alert">
            Couldn’t load the agent fleet — this is a loading failure, not an empty fleet.
          </p>
        ) : !agents || agents.length === 0 ? (
          <p className="text-sm text-opsgrid-text-secondary">
            No edge agents have reported yet. Agents appear here once they enroll and send a heartbeat.
          </p>
        ) : (
          <div className="space-y-2">
            {ordered.map((a) => (
              <Tooltip key={a.agent_id}>
                <TooltipTrigger asChild>
                  <div className="flex items-center justify-between p-3 bg-opsgrid-bg rounded-lg">
                    <div className="flex items-center gap-3">
                      <HardDrive className="text-opsgrid-primary" size={20} />
                      <div>
                        <p className="font-medium">{a.agent_id}</p>
                        <p className="text-sm text-opsgrid-text-secondary">
                          {a.active_collectors}/{a.total_collectors} collectors
                          {a.buffer_pending > 0 && ` • ${a.buffer_pending} buffered`}
                          {a.dead_lettered > 0 && ` • ${a.dead_lettered} dead-lettered`}
                        </p>
                        {/* DATA THAT NO LONGER EXISTS ANYWHERE, said in its own colour
                            rather than as one clause in a grey run-on. Buffered is
                            waiting, dead-lettered is replayable; dropped is gone. */}
                        {a.dropped > 0 && (
                          <p className="text-sm text-status-alarm">
                            {formatNumber(a.dropped, 0)} readings dropped — not recoverable
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {/* Cert expiry OUT OF THE TOOLTIP (P12): an expiring certificate
                          stops an agent dead, and it was visible only to someone who
                          happened to hover the right row. */}
                      {a.cert_expires_in_seconds != null &&
                        certDays(a) < CERT_WARNING_DAYS && (
                          <Badge
                            variant={certDays(a) < CERT_CRITICAL_DAYS ? 'error' : 'warning'}
                            size="sm"
                          >
                            cert {Math.max(0, Math.round(certDays(a)))}d
                          </Badge>
                        )}
                      <Badge variant={livenessVariant(a.liveness)} size="sm">{a.liveness}</Badge>
                    </div>
                  </div>
                </TooltipTrigger>
                <TooltipContent>
                  Last seen: {a.last_seen ? new Date(a.last_seen).toLocaleString() : 'never'}
                  {a.cert_expires_in_seconds != null &&
                    ` • cert expires in ${Math.round(a.cert_expires_in_seconds / 86400)}d`}
                </TooltipContent>
              </Tooltip>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
};

export const SystemHealthPage: FC = () => {
  // P2 (page-enhancement review): `details` and `checked_at` were FETCHED AND DISCARDED —
  // the endpoint has carried per-component payloads (consecutive-failure counts, running
  // flags, error strings) since the FS-693 arc gave every background service a check, and
  // this page typed them away. The tiles now expand into their details, and the header
  // says when the report was taken and what the overall verdict is.
  const { data: health } = useQuery({
    queryKey: ['health-detailed'],
    queryFn: async () => {
      const res = await api.get<{
        status: string;
        checks: Record<string, string>;
        details?: Record<string, Record<string, unknown>>;
        checked_at?: string;
      }>('/health/detailed');
      return res.data;
    },
    refetchInterval: 15000,
  });
  const [expanded, setExpanded] = useState<string | null>(null);
  const { data: sys } = useQuery({
    queryKey: ['health-system'],
    queryFn: async () => {
      const res = await api.get<{ available: boolean; cpu_percent: number | null; memory_percent: number | null; disk_percent: number | null }>('/health/system');
      return res.data;
    },
    refetchInterval: 15000,
  });

  const checks = health?.checks ?? {};
  const details = health?.details ?? {};
  const healthy = (s: string) => s === 'healthy' || s === 'ok' || s === 'up' || s === 'ready';
  // "disabled" and "skipped" are deployment postures, not faults — the old two-state
  // badge painted an instance with exports switched off as a red error, which teaches
  // admins to ignore red. Neutral gets its own colour.
  const neutral = (s: string) => s === 'disabled' || s === 'skipped' || s === 'not_running';
  const badgeVariant = (s: string) => (healthy(s) ? 'success' : neutral(s) ? 'default' : 'error');
  const label = (k: string) => k.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v)}%`);
  const detailValue = (v: unknown) =>
    typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v);

  const overall = health?.status;
  const anyBroken = Object.values(checks).some((s) => !healthy(s) && !neutral(s));

  return (
    <div className="space-y-6">
      {/* The overall verdict and its timestamp, so a degraded report is visible without
          scanning fifteen tiles — and a stale report is visibly stale. */}
      {overall && (
        <div
          className={`rounded border px-3 py-2 text-sm flex items-center justify-between ${
            anyBroken || (overall !== 'ready' && overall !== 'ok' && overall !== 'healthy')
              ? 'border-status-alarm/40 bg-status-alarm/10 text-status-alarm'
              : 'border-status-running/40 bg-status-running/10 text-status-running'
          }`}
        >
          <span className="font-medium">Overall: {overall}</span>
          {health?.checked_at && (
            <span className="text-opsgrid-text-secondary">
              checked {formatDateTime(health.checked_at)}
            </span>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {Object.entries(checks).map(([name, status]) => {
          const componentDetails = details[name] ?? {};
          const hasDetails = Object.keys(componentDetails).length > 0;
          const isOpen = expanded === name;
          return (
            <Card key={name} className="p-4">
              <button
                onClick={() => hasDetails && setExpanded(isOpen ? null : name)}
                className={`w-full flex items-center justify-between text-left ${
                  hasDetails ? '' : 'cursor-default'
                }`}
                aria-expanded={isOpen}
                aria-label={`${label(name)} health`}
              >
                <div className="flex items-center gap-3">
                  <Activity className="w-5 h-5 text-opsgrid-primary" />
                  <span className="font-medium">{label(name)}</span>
                </div>
                <Badge variant={badgeVariant(status)} size="sm">{status}</Badge>
              </button>
              {isOpen && (
                <dl className="mt-3 pt-3 border-t border-opsgrid-border space-y-1">
                  {Object.entries(componentDetails).map(([key, value]) => (
                    <div key={key} className="flex justify-between gap-2 text-sm">
                      <dt className="text-opsgrid-text-secondary">{label(key)}</dt>
                      <dd className="font-mono text-right break-all">{detailValue(value)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </Card>
          );
        })}
        {Object.keys(checks).length === 0 && (
          <p className="text-sm text-opsgrid-text-secondary">Loading component health…</p>
        )}
      </div>

      <Card title="System Metrics" subtitle={sys?.available ? 'Live host resource utilization' : 'Host metrics unavailable'}>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {[
            { label: 'CPU', value: pct(sys?.cpu_percent) },
            { label: 'Memory', value: pct(sys?.memory_percent) },
            { label: 'Disk', value: pct(sys?.disk_percent) },
          ].map((metric) => (
            <div key={metric.label} className="p-3 bg-opsgrid-bg rounded-lg text-center">
              <p className="text-xl font-bold">{metric.value}</p>
              <p className="text-sm text-opsgrid-text-secondary">{metric.label}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};

// camelCase: /api/v1/organizations is registered with the transform seam
// (src/api/assets.ts), which camelizes responses and snake_cases the PUT body.
interface OrgSettings {
  timezone?: string;
  dateFormat?: string;
  notifyEmail?: boolean;
  notifySms?: boolean;
  notifyWebhook?: boolean;
}

const SETTING_DEFAULTS: Required<OrgSettings> = {
  timezone: 'America/Chicago',
  dateFormat: 'MM/dd/yyyy',
  notifyEmail: true,
  notifySms: true,
  notifyWebhook: true,
};

export const SettingsPage: FC = () => {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({
    queryKey: ['org-settings'],
    queryFn: async () => {
      const res = await api.get<OrgSettings>('/api/v1/organizations/settings/current');
      return res.data;
    },
  });

  const [draft, setDraft] = useState<OrgSettings>({});
  // Explicit defaults first, stored values over them, unsaved edits on top.
  const current = { ...SETTING_DEFAULTS, ...settings, ...draft };

  const save = useMutation({
    // Send only the edited keys: the server merges, and re-sending the full
    // snapshot would clobber concurrent edits from another admin/tab.
    mutationFn: (patch: OrgSettings) => api.put('/api/v1/organizations/settings/current', patch),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['org-settings'] }); setDraft({}); },
  });
  // `draft` survives a failure, so the edited values stay in the fields — which reads
  // exactly like a save that worked. The banner below is what distinguishes them.

  const set = (key: keyof OrgSettings, value: any) => setDraft((d) => ({ ...d, [key]: value }));
  const dirty = Object.keys(draft).length > 0;

  return (
    <div className="space-y-6">
      <Card title="General Settings" subtitle="Organization preferences">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Input
            label="Timezone"
            value={current.timezone}
            onChange={(e) => set('timezone', e.target.value)}
          />
          <Select
            label="Date Format"
            value={current.dateFormat}
            onChange={(e) => set('dateFormat', e.target.value)}
            options={[
              { value: 'MM/dd/yyyy', label: 'MM/DD/YYYY' },
              { value: 'dd/MM/yyyy', label: 'DD/MM/YYYY' },
              { value: 'yyyy-MM-dd', label: 'YYYY-MM-DD' },
            ]}
          />
        </div>
      </Card>

      <Card title="Notifications" subtitle="Alert preferences">
        <div className="space-y-3">
          {([
            ['notifyEmail', 'Email alerts'],
            ['notifySms', 'SMS notifications'],
            ['notifyWebhook', 'Webhook events'],
          ] as [keyof OrgSettings, string][]).map(([key, label]) => (
            <label key={key} className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                className="w-4 h-4 rounded border-opsgrid-border"
                checked={Boolean(current[key])}
                onChange={(e) => set(key, e.target.checked)}
              />
              <span className="text-sm">{label}</span>
            </label>
          ))}
        </div>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={() => save.mutate(draft)} disabled={!dirty || save.isPending}>
          {save.isPending ? 'Saving…' : 'Save changes'}
        </Button>
        {save.isSuccess && !dirty && <span className="text-sm text-status-success">Saved</span>}
        {save.isError && (
          <span role="alert" className="text-sm text-status-alarm">
            Could not save these settings — your edits are still here and have not been
            applied.
          </span>
        )}
      </div>
    </div>
  );
};
