import { FC, FormEvent, useState } from 'react';
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

  const testMutation = useMutation({
    mutationFn: () => notificationsApi.sendTest({ severity: 'warning' }),
    onSuccess: (result) => {
      setTestSummary(
        `Test dispatched — matched ${result.matched} subscription${result.matched === 1 ? '' : 's'}.`
      );
      queryClient.invalidateQueries({ queryKey: ['notification-log'] });
    },
    onError: () => setTestSummary('Test dispatch failed.'),
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
  const deliveries = log ?? [];

  return (
    <div className="space-y-6">
      <Card
        title="Notification Subscriptions"
        subtitle="Route platform events to webhooks, Slack, or email"
        action={
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
        }
      >
        {testSummary && (
          <p className="text-sm text-opsgrid-text-secondary mb-3">{testSummary}</p>
        )}
        {deleteError && (
          <p role="alert" className="text-sm text-status-alarm mb-3">{deleteError}</p>
        )}
        {isError ? (
          <p className="text-status-alarm text-sm py-4">Failed to load subscriptions.</p>
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
                    <td className="py-2 pr-4 font-medium">{sub.name}</td>
                    <td className="py-2 pr-4">
                      <Badge variant="info" size="sm">
                        {sub.channel}
                      </Badge>
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs max-w-[16rem] truncate" title={sub.target}>
                      {sub.target}
                    </td>
                    <td className="py-2 pr-4">
                      <Badge variant={severityVariant(sub.minSeverity)} size="sm">
                        {sub.minSeverity}
                      </Badge>
                    </td>
                    <td className="py-2 pr-4 text-opsgrid-text-secondary">
                      {sub.domain || sub.assetId
                        ? [sub.domain, sub.assetId].filter(Boolean).join(' / ')
                        : 'All events'}
                    </td>
                    <td className="py-2 pr-4">
                      <Badge variant={sub.enabled ? 'success' : 'neutral'} size="sm">
                        {sub.enabled ? 'enabled' : 'disabled'}
                      </Badge>
                    </td>
                    <td className="py-2 text-right">
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
            <p className="text-sm text-status-alarm">Failed to create subscription.</p>
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
        {isLogError ? (
          <p className="text-status-alarm text-sm py-4">Failed to load the delivery log.</p>
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
