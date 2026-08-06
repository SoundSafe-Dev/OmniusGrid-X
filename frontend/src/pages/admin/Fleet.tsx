import { FC, FormEvent, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  LucideIcon,
  AlertTriangle,
  RefreshCw,
  Rocket,
  ShieldCheck,
  UploadCloud,
} from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  Input,
  Select,
  SkeletonTable,
  Table,
} from '../../components/ui';
import {
  useAgentReleases,
  useAgentRollouts,
  useAgentVersions,
  useCancelAgentRollout,
  useCreateAgentRelease,
  useCreateAgentRollout,
  usePublishAgentRelease,
  useYankAgentRelease,
} from '../../hooks/useFleet';
import {
  AgentReleaseStatus,
  AgentRollout,
  AgentRolloutStatus,
  AgentRolloutTargetStatus,
} from '../../types/fleet';
import { cn, formatDateTime, formatNumber, formatTimeAgo } from '../../utils';

const RELEASE_STATUS_VARIANT: Record<AgentReleaseStatus, 'neutral' | 'success' | 'warning'> = {
  draft: 'neutral',
  published: 'success',
  yanked: 'warning',
};

const ROLLOUT_STATUS_VARIANT: Record<AgentRolloutStatus, 'neutral' | 'info' | 'success' | 'warning' | 'error'> = {
  pending: 'neutral',
  paused: 'warning',
  running: 'info',
  completed: 'success',
  cancelled: 'neutral',
  rolled_back: 'warning',
  failed: 'error',
};

const TARGET_STATUS_VARIANT: Record<AgentRolloutTargetStatus, 'neutral' | 'info' | 'success' | 'warning' | 'error'> = {
  pending: 'neutral',
  updating: 'info',
  success: 'success',
  failed: 'error',
  rolled_back: 'warning',
  cancelled: 'neutral',
  skipped: 'neutral',
};

interface ReleaseFormState {
  version: string;
  channel: string;
  image_tag: string;
  bundle_encoding: 'text' | 'base64';
  config_bundle: string;
  release_notes: string;
}

interface RolloutFormState {
  name: string;
  release_id: string;
  target_mode: 'all' | 'assets';
  asset_ids: string;
  canary_percentage: string;
  wave_size: string;
  health_timeout_seconds: string;
  min_success_ratio: string;
  failure_threshold: string;
  rollback_release_id: string;
}

const emptyReleaseForm: ReleaseFormState = {
  version: '',
  channel: 'stable',
  image_tag: '',
  bundle_encoding: 'text',
  config_bundle: '',
  release_notes: '',
};

const emptyRolloutForm: RolloutFormState = {
  name: '',
  release_id: '',
  target_mode: 'all',
  asset_ids: '',
  canary_percentage: '10',
  wave_size: '',
  health_timeout_seconds: '300',
  min_success_ratio: '1',
  failure_threshold: '1',
  rollback_release_id: '',
};

const SummaryCard: FC<{
  label: string;
  value: string;
  icon: LucideIcon;
  tone?: 'default' | 'danger';
}> = ({ label, value, icon: Icon, tone = 'default' }) => (
  <Card className="h-full">
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-sm text-opsgrid-text-secondary">{label}</p>
        <p
          className={cn(
            'mt-2 text-2xl font-semibold tabular-nums',
            tone === 'danger' ? 'text-status-alarm' : 'text-opsgrid-text'
          )}
        >
          {value}
        </p>
      </div>
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-opsgrid-primary/10 text-opsgrid-primary">
        <Icon size={20} />
      </div>
    </div>
  </Card>
);

function asNumber(value: string): number | undefined {
  if (value.trim() === '') return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function rolloutProgress(rollout: AgentRollout): { done: number; total: number } {
  const total = rollout.targets.length;
  const done = rollout.targets.filter((target) =>
    ['success', 'failed', 'rolled_back', 'cancelled', 'skipped'].includes(target.status)
  ).length;
  return { done, total };
}

export const Fleet: FC = () => {
  const versions = useAgentVersions();
  const releases = useAgentReleases();
  const rollouts = useAgentRollouts();
  const createRelease = useCreateAgentRelease();
  const publishRelease = usePublishAgentRelease();
  const yankRelease = useYankAgentRelease();
  const createRollout = useCreateAgentRollout();
  const cancelRollout = useCancelAgentRollout();

  const [showReleaseForm, setShowReleaseForm] = useState(false);
  const [showRolloutForm, setShowRolloutForm] = useState(false);
  const [releaseForm, setReleaseForm] = useState(emptyReleaseForm);
  const [rolloutForm, setRolloutForm] = useState(emptyRolloutForm);
  const [formError, setFormError] = useState('');

  const versionItems = versions.data?.items ?? [];
  const releaseItems = releases.data ?? [];
  const rolloutItems = rollouts.data ?? [];
  const publishedReleases = releaseItems.filter((release) => release.status === 'published');
  const activeRollouts = rolloutItems.filter((rollout) =>
    ['pending', 'running', 'paused'].includes(rollout.status)
  );
  const failedTargets = rolloutItems.reduce(
    (sum, rollout) =>
      sum + rollout.targets.filter((target) => ['failed', 'rolled_back'].includes(target.status)).length,
    0
  );
  const totalAgents = versionItems.reduce((sum, item) => sum + item.agent_count, 0);

  const releaseOptions = useMemo(
    () =>
      publishedReleases.map((release) => ({
        value: release.id,
        label: `${release.version} (${release.channel})`,
      })),
    [publishedReleases]
  );

  const refreshAll = () => {
    versions.refetch();
    releases.refetch();
    rollouts.refetch();
  };

  const submitRelease = (event: FormEvent) => {
    event.preventDefault();
    setFormError('');
    if (!releaseForm.version || !releaseForm.image_tag || !releaseForm.config_bundle) {
      setFormError('Version, image tag, and config bundle are required.');
      return;
    }
    createRelease.mutate(
      {
        version: releaseForm.version.trim(),
        channel: releaseForm.channel.trim() || 'stable',
        image_tag: releaseForm.image_tag.trim(),
        bundle_encoding: releaseForm.bundle_encoding,
        config_bundle: releaseForm.config_bundle,
        release_notes: releaseForm.release_notes.trim() || undefined,
      },
      {
        onSuccess: () => {
          setReleaseForm(emptyReleaseForm);
          setShowReleaseForm(false);
        },
        onError: (error) => setFormError(error.message),
      }
    );
  };

  const submitRollout = (event: FormEvent) => {
    event.preventDefault();
    setFormError('');
    if (!rolloutForm.name || !rolloutForm.release_id) {
      setFormError('Rollout name and release are required.');
      return;
    }

    const strategy: Record<string, unknown> = {};
    const canary = asNumber(rolloutForm.canary_percentage);
    const waveSize = asNumber(rolloutForm.wave_size);
    const healthTimeout = asNumber(rolloutForm.health_timeout_seconds);
    const minSuccessRatio = asNumber(rolloutForm.min_success_ratio);
    const failureThreshold = asNumber(rolloutForm.failure_threshold);
    if (waveSize) strategy.wave_size = waveSize;
    else if (canary) strategy.canary_percentage = canary;
    if (healthTimeout !== undefined) strategy.health_timeout_seconds = healthTimeout;
    if (minSuccessRatio !== undefined) strategy.min_success_ratio = minSuccessRatio;
    if (failureThreshold !== undefined) strategy.failure_threshold = failureThreshold;
    if (rolloutForm.rollback_release_id) strategy.rollback_release_id = rolloutForm.rollback_release_id;

    const assetIds = rolloutForm.asset_ids
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
    if (rolloutForm.target_mode === 'assets' && assetIds.length === 0) {
      setFormError('Enter at least one asset ID for explicit targeting.');
      return;
    }

    createRollout.mutate(
      {
        name: rolloutForm.name.trim(),
        release_id: rolloutForm.release_id,
        target_selector:
          rolloutForm.target_mode === 'all'
            ? { all: true }
            : { asset_ids: assetIds },
        strategy,
      },
      {
        onSuccess: () => {
          setRolloutForm(emptyRolloutForm);
          setShowRolloutForm(false);
        },
        onError: (error) => setFormError(error.message),
      }
    );
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-opsgrid-text">Fleet OTA</h1>
          <p className="text-sm text-opsgrid-text-secondary">
            Edge-agent releases, staged rollouts, and version distribution. Auto-refreshes every 30s.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" onClick={refreshAll}>
            <RefreshCw size={16} className="mr-2" />
            Refresh
          </Button>
          <Button variant="secondary" onClick={() => setShowReleaseForm((value) => !value)}>
            <UploadCloud size={16} className="mr-2" />
            Release
          </Button>
          <Button onClick={() => setShowRolloutForm((value) => !value)}>
            <Rocket size={16} className="mr-2" />
            Rollout
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard label="Reporting agents" value={formatNumber(totalAgents, 0)} icon={ShieldCheck} />
        <SummaryCard label="Published releases" value={formatNumber(publishedReleases.length, 0)} icon={UploadCloud} />
        <SummaryCard label="Active rollouts" value={formatNumber(activeRollouts.length, 0)} icon={Rocket} />
        <SummaryCard label="Failed / rolled back targets" value={formatNumber(failedTargets, 0)} icon={AlertTriangle} tone={failedTargets > 0 ? 'danger' : 'default'} />
      </div>

      {/* THE FOUR OTA MUTATIONS SAY WHEN THEY FAIL (FS-480).
      
          All four read only `isPending` before this. `yankRelease` is the sharpest: it is
          the safety action — pulling a release that is going badly — and a failed yank left
          the release listed exactly as it was, which is what a successful one looks like
          for the moment before the list refetches.
      
          They are defined in `useFleet.ts`, and the mutation-failure sweep scans `.tsx`
          only, so it could not see them. */}
      {(createRelease.isError ||
        publishRelease.isError ||
        yankRelease.isError ||
        createRollout.isError) && (
        <Card className="p-4">
          <p role="alert" className="text-sm text-status-alarm">
            {yankRelease.isError
              ? 'Could not yank that release — it is still published.'
              : publishRelease.isError
                ? 'Could not publish that release — it is unchanged.'
                : createRollout.isError
                  ? 'Could not create the rollout — nothing was started.'
                  : 'Could not create the release — nothing was saved.'}
          </p>
        </Card>
      )}

      {(showReleaseForm || showRolloutForm) && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {showReleaseForm && (
            <Card title="Create release" subtitle="Signed config-bundle release metadata">
              <form className="space-y-4" onSubmit={submitRelease}>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <Input label="Version" value={releaseForm.version} onChange={(e) => setReleaseForm({ ...releaseForm, version: e.target.value })} placeholder="1.2.3" />
                  <Input label="Channel" value={releaseForm.channel} onChange={(e) => setReleaseForm({ ...releaseForm, channel: e.target.value })} placeholder="stable" />
                  <Input label="Image tag" className="sm:col-span-2" value={releaseForm.image_tag} onChange={(e) => setReleaseForm({ ...releaseForm, image_tag: e.target.value })} placeholder="registry.local/opsgrid-agent:1.2.3" />
                  <Select
                    label="Bundle encoding"
                    value={releaseForm.bundle_encoding}
                    onChange={(e) => setReleaseForm({ ...releaseForm, bundle_encoding: e.target.value as 'text' | 'base64' })}
                    options={[
                      { value: 'text', label: 'Text' },
                      { value: 'base64', label: 'Base64' },
                    ]}
                  />
                  <Input label="Release notes" value={releaseForm.release_notes} onChange={(e) => setReleaseForm({ ...releaseForm, release_notes: e.target.value })} placeholder="Optional" />
                </div>
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-opsgrid-text">Config bundle</span>
                  <textarea
                    className="min-h-[9rem] w-full rounded-lg border border-opsgrid-border bg-opsgrid-bg px-3 py-2 font-mono text-sm text-opsgrid-text placeholder:text-opsgrid-text-secondary focus:border-transparent focus:outline-none focus:ring-2 focus:ring-opsgrid-primary"
                    value={releaseForm.config_bundle}
                    onChange={(e) => setReleaseForm({ ...releaseForm, config_bundle: e.target.value })}
                    placeholder="collectors:&#10;  - asset_id: asset-1&#10;    type: mqtt&#10;    config: {}"
                  />
                </label>
                {formError && <p className="text-sm text-status-alarm">{formError}</p>}
                <div className="flex justify-end gap-2">
                  <Button type="button" variant="ghost" onClick={() => setShowReleaseForm(false)}>Cancel</Button>
                  <Button type="submit" loading={createRelease.isPending}>Create release</Button>
                </div>
              </form>
            </Card>
          )}

          {showRolloutForm && (
            <Card title="Create rollout" subtitle="Staged deployment with health gates">
              <form className="space-y-4" onSubmit={submitRollout}>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <Input label="Name" value={rolloutForm.name} onChange={(e) => setRolloutForm({ ...rolloutForm, name: e.target.value })} placeholder="Canary rollout" />
                  <Select
                    label="Release"
                    value={rolloutForm.release_id}
                    onChange={(e) => setRolloutForm({ ...rolloutForm, release_id: e.target.value })}
                    options={releaseOptions}
                    placeholder={releaseOptions.length ? 'Select release' : 'No published releases'}
                  />
                  <Select
                    label="Targets"
                    value={rolloutForm.target_mode}
                    onChange={(e) => setRolloutForm({ ...rolloutForm, target_mode: e.target.value as 'all' | 'assets' })}
                    options={[
                      { value: 'all', label: 'All active assets' },
                      { value: 'assets', label: 'Explicit asset IDs' },
                    ]}
                  />
                  <Input label="Asset IDs" disabled={rolloutForm.target_mode === 'all'} value={rolloutForm.asset_ids} onChange={(e) => setRolloutForm({ ...rolloutForm, asset_ids: e.target.value })} placeholder="uuid-1, uuid-2" />
                  <Input label="Canary %" type="number" min="1" max="99" value={rolloutForm.canary_percentage} onChange={(e) => setRolloutForm({ ...rolloutForm, canary_percentage: e.target.value })} />
                  <Input label="Wave size" type="number" min="1" value={rolloutForm.wave_size} onChange={(e) => setRolloutForm({ ...rolloutForm, wave_size: e.target.value })} placeholder="Overrides canary" />
                  <Input label="Health timeout (s)" type="number" min="0" value={rolloutForm.health_timeout_seconds} onChange={(e) => setRolloutForm({ ...rolloutForm, health_timeout_seconds: e.target.value })} />
                  <Input label="Min success ratio" type="number" min="0" max="1" step="0.01" value={rolloutForm.min_success_ratio} onChange={(e) => setRolloutForm({ ...rolloutForm, min_success_ratio: e.target.value })} />
                  <Input label="Failure threshold" type="number" min="0" value={rolloutForm.failure_threshold} onChange={(e) => setRolloutForm({ ...rolloutForm, failure_threshold: e.target.value })} />
                  <Select
                    label="Rollback release"
                    value={rolloutForm.rollback_release_id}
                    onChange={(e) => setRolloutForm({ ...rolloutForm, rollback_release_id: e.target.value })}
                    options={releaseOptions}
                    placeholder="None"
                  />
                </div>
                {formError && <p className="text-sm text-status-alarm">{formError}</p>}
                <div className="flex justify-end gap-2">
                  <Button type="button" variant="ghost" onClick={() => setShowRolloutForm(false)}>Cancel</Button>
                  <Button type="submit" loading={createRollout.isPending}>Create rollout</Button>
                </div>
              </form>
            </Card>
          )}
        </div>
      )}

      <Card title="Version distribution" subtitle="Agents grouped by reported version" noPadding>
        {versions.isLoading && !versions.data ? (
          <SkeletonTable rows={4} columns={4} />
        ) : versions.isError ? (
          <div role="alert" className="p-6 text-status-alarm">Failed to load version distribution.</div>
        ) : versionItems.length === 0 ? (
          <div className="p-8 text-center text-sm text-opsgrid-text-secondary">No agent heartbeats have been recorded.</div>
        ) : (
          <Table>
            <Table.Head>
              <Table.Row>
                <Table.Header>Version</Table.Header>
                <Table.Header className="text-right">Agents</Table.Header>
                <Table.Header className="text-right">Assets</Table.Header>
                <Table.Header>Latest heartbeat</Table.Header>
              </Table.Row>
            </Table.Head>
            <Table.Body>
              {versionItems.map((item) => (
                <Table.Row key={item.agent_version}>
                  <Table.Cell className="font-mono">{item.agent_version}</Table.Cell>
                  <Table.Cell className="text-right tabular-nums">{formatNumber(item.agent_count, 0)}</Table.Cell>
                  <Table.Cell className="text-right tabular-nums">{formatNumber(item.asset_count, 0)}</Table.Cell>
                  <Table.Cell title={item.latest_heartbeat ? formatDateTime(item.latest_heartbeat) : undefined}>
                    {item.latest_heartbeat ? formatTimeAgo(item.latest_heartbeat) : 'Never'}
                  </Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card title="Releases" subtitle="Signed config bundles and pinned image tags" noPadding>
          {releases.isLoading && !releases.data ? (
            <SkeletonTable rows={5} columns={5} />
          ) : releases.isError ? (
            <div role="alert" className="p-6 text-status-alarm">Failed to load releases.</div>
          ) : releaseItems.length === 0 ? (
            <div className="p-8 text-center text-sm text-opsgrid-text-secondary">No releases created yet.</div>
          ) : (
            <Table>
              <Table.Head>
                <Table.Row>
                  <Table.Header>Status</Table.Header>
                  <Table.Header>Version</Table.Header>
                  <Table.Header>Image</Table.Header>
                  <Table.Header>Created</Table.Header>
                  <Table.Header>Actions</Table.Header>
                </Table.Row>
              </Table.Head>
              <Table.Body>
                {releaseItems.map((release) => (
                  <Table.Row key={release.id}>
                    <Table.Cell>
                      <Badge variant={RELEASE_STATUS_VARIANT[release.status]}>{release.status}</Badge>
                    </Table.Cell>
                    <Table.Cell>
                      <div className="font-mono text-sm">{release.version}</div>
                      <div className="text-xs text-opsgrid-text-secondary">{release.channel}</div>
                    </Table.Cell>
                    <Table.Cell className="max-w-xs truncate font-mono text-xs" title={release.image_tag}>{release.image_tag}</Table.Cell>
                    <Table.Cell title={release.created_at ? formatDateTime(release.created_at) : undefined}>
                      {release.created_at ? formatTimeAgo(release.created_at) : 'Unknown'}
                    </Table.Cell>
                    <Table.Cell>
                      <div className="flex flex-wrap gap-2">
                        {release.status === 'draft' && (
                          <Button size="sm" variant="secondary" onClick={() => publishRelease.mutate(release.id)} loading={publishRelease.isPending}>
                            Publish
                          </Button>
                        )}
                        {release.status === 'published' && (
                          <Button size="sm" variant="outline" onClick={() => yankRelease.mutate(release.id)} loading={yankRelease.isPending}>
                            Yank
                          </Button>
                        )}
                      </div>
                    </Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table>
          )}
        </Card>

        <Card title="Rollouts" subtitle="Wave progress and target health" noPadding>
          {rollouts.isLoading && !rollouts.data ? (
            <SkeletonTable rows={5} columns={5} />
          ) : rollouts.isError ? (
            <div role="alert" className="p-6 text-status-alarm">Failed to load rollouts.</div>
          ) : rolloutItems.length === 0 ? (
            <div className="p-8 text-center text-sm text-opsgrid-text-secondary">No rollouts created yet.</div>
          ) : (
            <Table>
              <Table.Head>
                <Table.Row>
                  <Table.Header>Status</Table.Header>
                  <Table.Header>Name</Table.Header>
                  <Table.Header>Progress</Table.Header>
                  <Table.Header>Updated</Table.Header>
                  <Table.Header>Actions</Table.Header>
                </Table.Row>
              </Table.Head>
              <Table.Body>
                {rolloutItems.map((rollout) => {
                  const progress = rolloutProgress(rollout);
                  return (
                    <Table.Row key={rollout.id}>
                      <Table.Cell>
                        <Badge variant={ROLLOUT_STATUS_VARIANT[rollout.status]}>{rollout.status}</Badge>
                      </Table.Cell>
                      <Table.Cell>
                        <Link className="text-opsgrid-primary hover:underline" to={`/admin/fleet/rollouts/${rollout.id}`}>
                          {rollout.name}
                        </Link>
                        <div className="text-xs text-opsgrid-text-secondary">{rollout.id.slice(0, 8)}</div>
                      </Table.Cell>
                      <Table.Cell>
                        <div className="text-sm tabular-nums">{progress.done}/{progress.total}</div>
                        <div className="mt-1 h-1.5 w-24 overflow-hidden rounded-full bg-opsgrid-border">
                          <div
                            className="h-full bg-opsgrid-primary"
                            style={{ width: progress.total ? `${Math.round((progress.done / progress.total) * 100)}%` : '0%' }}
                          />
                        </div>
                      </Table.Cell>
                      <Table.Cell title={rollout.updated_at ? formatDateTime(rollout.updated_at) : undefined}>
                        {rollout.updated_at ? formatTimeAgo(rollout.updated_at) : 'Unknown'}
                      </Table.Cell>
                      <Table.Cell>
                        <div className="flex flex-wrap gap-2">
                          {['pending', 'running'].includes(rollout.status) && (
                            <Button size="sm" variant="secondary" onClick={() => cancelRollout.mutate(rollout.id)} loading={cancelRollout.isPending}>
                              Cancel
                            </Button>
                          )}
                          <Link to={`/admin/fleet/rollouts/${rollout.id}`} className="inline-flex items-center rounded-lg border border-opsgrid-border px-3 py-1.5 text-sm text-opsgrid-text hover:bg-opsgrid-panel">
                            Open
                          </Link>
                        </div>
                      </Table.Cell>
                    </Table.Row>
                  );
                })}
              </Table.Body>
            </Table>
          )}
        </Card>
      </div>

      {rolloutItems.some((rollout) => rollout.targets.length > 0) && (
        <Card title="Recent targets" subtitle="Latest per-device rollout states" noPadding>
          <Table>
            <Table.Head>
              <Table.Row>
                <Table.Header>Status</Table.Header>
                <Table.Header>Rollout</Table.Header>
                <Table.Header>Asset</Table.Header>
                <Table.Header>Wave</Table.Header>
                <Table.Header>Command</Table.Header>
                <Table.Header>Last event</Table.Header>
              </Table.Row>
            </Table.Head>
            <Table.Body>
              {rolloutItems.flatMap((rollout) =>
                rollout.targets.slice(0, 6).map((target) => (
                  <Table.Row key={`${rollout.id}-${target.id}`}>
                    <Table.Cell><Badge variant={TARGET_STATUS_VARIANT[target.status]}>{target.status}</Badge></Table.Cell>
                    <Table.Cell><Link className="text-opsgrid-primary hover:underline" to={`/admin/fleet/rollouts/${rollout.id}`}>{rollout.name}</Link></Table.Cell>
                    <Table.Cell className="font-mono text-xs">{target.asset_id}</Table.Cell>
                    <Table.Cell className="tabular-nums">{target.wave_index}</Table.Cell>
                    <Table.Cell className="font-mono text-xs">{target.command_id || target.rollback_command_id || '—'}</Table.Cell>
                    <Table.Cell title={target.last_event_at ? formatDateTime(target.last_event_at) : undefined}>
                      {target.last_event_at ? formatTimeAgo(target.last_event_at) : 'Never'}
                    </Table.Cell>
                  </Table.Row>
                ))
              )}
            </Table.Body>
          </Table>
        </Card>
      )}
    </div>
  );
};

export default Fleet;
