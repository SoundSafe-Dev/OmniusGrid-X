import { FC, FormEvent, useState } from 'react';
import { ErrorState } from '../../components/ui'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BellRing, Plus, Send, Trash2 } from 'lucide-react';
import { Badge, Button, Card, Input, Select, SkeletonCard } from '../../components';
import {
  notificationsApi,
  NOTIFICATION_CHANNELS,
  NOTIFICATION_SEVERITIES,
  type NotificationChannel,
  type NotificationSeverity,
} from '../../api/notifications';
import { formatDateTime } from '../../utils';

const severityVariant = (
  severity: string
): 'success' | 'warning' | 'error' | 'info' | 'neutral' => {
  switch (severity?.toLowerCase()) {
    case 'critical':
      return 'error';
    case 'error':
      return 'error';
    case 'warning':
      return 'warning';
    case 'info':
      return 'info';
    default:
      return 'neutral';
  }
};

const CHANNEL_OPTIONS = NOTIFICATION_CHANNELS.map((c) => ({ value: c, label: c }));
const SEVERITY_OPTIONS = NOTIFICATION_SEVERITIES.map((s) => ({ value: s, label: s }));

export const Notifications: FC = () => {
  const queryClient = useQueryClient();

  const { data: subscriptions, isLoading, isError } = useQuery({
    queryKey: ['notification-subscriptions'],
    queryFn: () => notificationsApi.listSubscriptions(),
  });

  const { data: log, isError: isLogError } = useQuery({
    queryKey: ['notification-log'],
    queryFn: () => notificationsApi.deliveryLog(100),
    refetchInterval: 30000,
  });

  const [name, setName] = useState('');
  const [channel, setChannel] = useState<NotificationChannel>('webhook');
  const [target, setTarget] = useState('');
  const [minSeverity, setMinSeverity] = useState<NotificationSeverity>('warning');
  const [domain, setDomain] = useState('');
  const [assetId, setAssetId] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [testSummary, setTestSummary] = useState<string | null>(null);
  const [testSeverity, setTestSeverity] = useState<NotificationSeverity>('warning');
  // Editing a subscription in place (P11). Before the PATCH route existed, a wrong URL
  // or severity meant delete-and-recreate — losing the id every delivery log entry
  // refers to.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<{ name: string; target: string; minSeverity: string }>({
    name: '',
    target: '',
    minSeverity: 'warning',
  });
  const [rowError, setRowError] = useState<string | null>(null);
  // Whether that summary is bad news, so it can be told apart from the good kind at a
  // glance rather than by reading it (FS-487).
  const [testMatchedNone, setTestMatchedNone] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: () =>
      notificationsApi.createSubscription({
        name: name.trim(),
        channel,
        target: target.trim(),
        minSeverity,
        domain: domain.trim() || null,
        assetId: assetId.trim() || null,
      }),
    onSuccess: () => {
      setName('');
      setTarget('');
      setDomain('');
      setAssetId('');
      setFormError(null);
      queryClient.invalidateQueries({ queryKey: ['notification-subscriptions'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (subscriptionId: string) => notificationsApi.deleteSubscription(subscriptionId),
    // Found by the mutation sweep AFTER this page had been read for the query defects and
    // declared clean — the two panels' failure handling was correct and the delete button
    // beside them said nothing at all. A failed delete leaves the row exactly where it
    // was, which is what a successful one looks like until the list refetches, so an
    // admin who thinks they have stopped a webhook has not.
    onError: () =>
      setDeleteError(
        'Could not remove that subscription — it is still active and will keep sending.',
      ),
    onSuccess: () => {
      setDeleteError(null);
      queryClient.invalidateQueries({ queryKey: ['notification-subscriptions'] });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown>; label: string }) =>
      notificationsApi.updateSubscription(id, body),
    onSuccess: () => {
      setRowError(null);
      setEditingId(null);
      queryClient.invalidateQueries({ queryKey: ['notification-subscriptions'] });
    },
    onError: (_error, variables) =>
      setRowError(`Could not update "${variables.label}" — it is unchanged.`),
  });

  const testMutation = useMutation({
    // SEVERITY CHOSEN, NOT HARDCODED (P11, page-enhancement review). This always sent
    // `warning`, so a critical-only subscription could never match a test and every
    // check of one reported "matched 0" — the exact failure the FS-487 copy below was
    // written to make legible, arriving from the test button itself.
    mutationFn: () => notificationsApi.sendTest({ severity: testSeverity }),
    onSuccess: (result) => {
      // MATCHED ZERO IS NOT A SUCCESS (FS-487). The request succeeded and nothing was
      // delivered — which is the one thing pressing Test is meant to find out. It used to
      // read "Test dispatched — matched 0 subscriptions" in the same grey as every other
      // outcome, so the sentence a user skims says "dispatched" either way.
      setTestSummary(
        result.matched === 0
          ? `Nothing was sent — no subscription matches a ${testSeverity}-severity test event. ` +
            'Check the minimum severity, domain and asset filters below.'
          : `Test dispatched — matched ${result.matched} subscription${result.matched === 1 ? '' : 's'}.`
      );
      setTestMatchedNone(result.matched === 0);
      queryClient.invalidateQueries({ queryKey: ['notification-log'] });
    },
    onError: () => {
      setTestSummary('Test dispatch failed.');
      setTestMatchedNone(true);
    },
  });

  const handleCreate = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setFormError('Name is required.');
      return;
    }
    if (!target.trim()) {
      setFormError('Target is required (webhook URL, Slack webhook, or email address).');
      return;
    }
    setFormError(null);
    createMutation.mutate();
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={6} />
      </div>
    );
  }

  const subs = subscriptions ?? [];
  const deliveries = log?.items ?? [];

  return (
    <div className="space-y-6">
      <Card
        title="Notification Subscriptions"
        subtitle="Route platform events to webhooks, Slack, or email"
        action={
          <div className="flex items-center gap-2">
            <select
              aria-label="Test severity"
              value={testSeverity}
              onChange={(e) => setTestSeverity(e.target.value as NotificationSeverity)}
              className="bg-opsgrid-bg border border-opsgrid-border rounded px-2 py-1.5 text-sm"
            >
              {['info', 'warning', 'error', 'critical'].map((level) => (
                <option key={level} value={level}>{level}</option>
              ))}
            </select>
            <Button
              variant="secondary"
              size="sm"
              loading={testMutation.isPending}
              disabled={testMutation.isPending || subs.length === 0}
              onClick={() => testMutation.mutate()}
            >
              <Send size={16} className="mr-1" />
              Send Test
            </Button>
          </div>
        }
      >
        {testSummary && (
          <p
            role={testMatchedNone ? 'alert' : 'status'}
            className={`text-sm mb-3 ${testMatchedNone ? 'text-status-warning' : 'text-opsgrid-text-secondary'}`}
          >
            {testSummary}
          </p>
        )}
        {deleteError && (
          <p role="alert" className="text-sm text-status-alarm mb-3">{deleteError}</p>
        )}
        {rowError && (
          <p role="alert" className="text-sm text-status-alarm mb-3">{rowError}</p>
        )}
        {isError ? (
          <ErrorState message="Failed to load subscriptions." />
        ) : subs.length === 0 ? (
          <p className="text-opsgrid-text-secondary text-center py-8">
            No subscriptions yet. Create one below to start receiving alerts.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-opsgrid-text-secondary border-b border-opsgrid-border">
                  <th className="py-2 pr-4 font-medium">Name</th>
                  <th className="py-2 pr-4 font-medium">Channel</th>
                  <th className="py-2 pr-4 font-medium">Target</th>
                  <th className="py-2 pr-4 font-medium">Min Severity</th>
                  <th className="py-2 pr-4 font-medium">Scope</th>
                  <th className="py-2 pr-4 font-medium">Enabled</th>
                  <th className="py-2 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-opsgrid-border">
                {subs.map((sub) => (
                  <tr key={sub.id}>
                    <td className="py-2 pr-4 font-medium">
                      {editingId === sub.id ? (
                        <input
                          aria-label="Subscription name"
                          value={editForm.name}
                          onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                          className="bg-opsgrid-bg border border-opsgrid-border rounded px-2 py-1 text-sm w-36"
                        />
                      ) : (
                        sub.name
                      )}
                    </td>
                    <td className="py-2 pr-4">
                      <Badge variant="info" size="sm">
                        {sub.channel}
                      </Badge>
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs max-w-[16rem] truncate" title={sub.target}>
                      {editingId === sub.id ? (
                        <input
                          aria-label="Target"
                          value={editForm.target}
                          onChange={(e) => setEditForm({ ...editForm, target: e.target.value })}
                          className="bg-opsgrid-bg border border-opsgrid-border rounded px-2 py-1 text-xs w-full font-mono"
                        />
                      ) : (
                        sub.target
                      )}
                    </td>
                    <td className="py-2 pr-4">
                      {editingId === sub.id ? (
                        <select
                          aria-label="Minimum severity"
                          value={editForm.minSeverity}
                          onChange={(e) =>
                            setEditForm({ ...editForm, minSeverity: e.target.value })
                          }
                          className="bg-opsgrid-bg border border-opsgrid-border rounded px-2 py-1 text-sm"
                        >
                          {['info', 'warning', 'error', 'critical'].map((level) => (
                            <option key={level} value={level}>{level}</option>
                          ))}
                        </select>
                      ) : (
                        <Badge variant={severityVariant(sub.minSeverity)} size="sm">
                          {sub.minSeverity}
                        </Badge>
                      )}
                    </td>
                    <td className="py-2 pr-4 text-opsgrid-text-secondary">
                      {sub.domain || sub.assetId
                        ? [sub.domain, sub.assetId].filter(Boolean).join(' / ')
                        : 'All events'}
                    </td>
                    {/* THE BADGE BECOMES A CONTROL (P11). `enabled` has always been
                        displayed and could be written only at creation, so the one action
                        an operator most wants during an incident — stop paging this
                        channel — meant deleting the subscription and rebuilding it
                        afterwards from memory. */}
                    <td className="py-2 pr-4">
                      <button
                        type="button"
                        onClick={() => {
                          setRowError(null);
                          updateMutation.mutate({
                            id: sub.id,
                            body: { enabled: !sub.enabled },
                            label: sub.name,
                          });
                        }}
                        disabled={updateMutation.isPending}
                        aria-label={`${sub.enabled ? 'Disable' : 'Enable'} subscription ${sub.name}`}
                        title={sub.enabled ? 'Stop sending to this target' : 'Resume sending'}
                      >
                        <Badge variant={sub.enabled ? 'success' : 'neutral'} size="sm">
                          {sub.enabled ? 'enabled' : 'disabled'}
                        </Badge>
                      </button>
                    </td>
                    <td className="py-2 text-right whitespace-nowrap">
                      {editingId === sub.id ? (
                        <>
                          <Button
                            size="sm"
                            className="mr-2"
                            disabled={updateMutation.isPending}
                            onClick={() => {
                              setRowError(null);
                              updateMutation.mutate({
                                id: sub.id,
                                body: {
                                  name: editForm.name,
                                  target: editForm.target,
                                  minSeverity: editForm.minSeverity,
                                },
                                label: sub.name,
                              });
                            }}
                          >
                            Save
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            className="mr-2"
                            onClick={() => setEditingId(null)}
                          >
                            Cancel
                          </Button>
                        </>
                      ) : (
                        <Button
                          variant="secondary"
                          size="sm"
                          className="mr-2"
                          onClick={() => {
                            setRowError(null);
                            setEditingId(sub.id);
                            setEditForm({
                              name: sub.name,
                              target: sub.target,
                              minSeverity: sub.minSeverity,
                            });
                          }}
                          aria-label={`Edit subscription ${sub.name}`}
                        >
                          Edit
                        </Button>
                      )}
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={deleteMutation.isPending}
                        onClick={() => deleteMutation.mutate(sub.id)}
                        aria-label={`Delete subscription ${sub.name}`}
                      >
                        <Trash2 size={14} />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="New Subscription" subtitle="Deliver matching events to a channel target">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Input
              label="Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Ops Slack — criticals"
            />
            <Select
              label="Channel"
              value={channel}
              onChange={(e) => setChannel(e.target.value as NotificationChannel)}
              options={CHANNEL_OPTIONS}
            />
            <Select
              label="Min Severity"
              value={minSeverity}
              onChange={(e) => setMinSeverity(e.target.value as NotificationSeverity)}
              options={SEVERITY_OPTIONS}
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Input
              label="Target"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder={channel === 'email' ? 'ops@example.com' : 'https://…'}
              helperText={
                channel === 'email'
                  ? 'Recipient email address'
                  : channel === 'slack'
                    ? 'Slack incoming-webhook URL'
                    : 'Webhook URL to POST events to'
              }
            />
            <Input
              label="Domain (optional)"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="e.g. maintenance"
              helperText="Limit to one event domain"
            />
            <Input
              label="Asset ID (optional)"
              value={assetId}
              onChange={(e) => setAssetId(e.target.value)}
              placeholder="e.g. asset-alpha"
              helperText="Limit to one asset"
            />
          </div>
          {formError && <p className="text-sm text-status-alarm">{formError}</p>}
          {createMutation.isError && !formError && (
            <ErrorState message="Failed to create subscription." />
          )}
          <Button
            type="submit"
            variant="primary"
            size="sm"
            loading={createMutation.isPending}
            disabled={createMutation.isPending}
          >
            <Plus size={16} className="mr-1" />
            Create Subscription
          </Button>
        </form>
      </Card>

      <Card title="Delivery Log" subtitle="Most recent notification dispatch attempts">
        {/* Say so when this is a page of the log rather than the log (FS-485). It is ordered
            newest first, so what is missing is the OLDEST attempts — and the question this
            card answers is "was that alert delivered?". An absent row read off a list
            presented as complete says the alert was never sent. */}
        {log?.truncated && (
          <p role="status" className="pb-2 text-xs text-status-warning">
            Showing the {log.limit} most recent attempts. Older deliveries exist and are not
            listed — an alert missing from this page may still have been sent.
          </p>
        )}
        {isLogError ? (
          <ErrorState message="Failed to load the delivery log." />
        ) : deliveries.length === 0 ? (
          <div className="flex flex-col items-center text-opsgrid-text-secondary py-8">
            <BellRing className="w-8 h-8 mb-2" />
            <p>No deliveries yet.</p>
          </div>
        ) : (
          <div className="overflow-x-auto max-h-96">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-opsgrid-text-secondary border-b border-opsgrid-border">
                  <th className="py-2 pr-4 font-medium">Time</th>
                  <th className="py-2 pr-4 font-medium">Channel</th>
                  <th className="py-2 pr-4 font-medium">Severity</th>
                  <th className="py-2 pr-4 font-medium">Title</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 font-medium">Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-opsgrid-border">
                {deliveries.map((entry) => (
                  <tr key={entry.id}>
                    <td className="py-2 pr-4 text-opsgrid-text-secondary whitespace-nowrap">
                      {entry.createdAt ? formatDateTime(entry.createdAt) : '—'}
                    </td>
                    <td className="py-2 pr-4">{entry.channel}</td>
                    <td className="py-2 pr-4">
                      <Badge variant={severityVariant(entry.severity)} size="sm">
                        {entry.severity}
                      </Badge>
                    </td>
                    <td className="py-2 pr-4">{entry.title}</td>
                    <td className="py-2 pr-4">
                      <Badge variant={entry.delivered ? 'success' : 'error'} size="sm">
                        {entry.delivered ? 'success' : 'failed'}
                      </Badge>
                    </td>
                    <td className="py-2 text-opsgrid-text-secondary">{entry.detail ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
};
