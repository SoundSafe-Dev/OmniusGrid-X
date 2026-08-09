import { FC, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, AlertTriangle, RefreshCw } from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  SkeletonCard,
  SkeletonTable,
  Table,
} from '../../components/ui';
import {
  useAgentRollout,
  useCancelAgentRollout,
  usePauseAgentRollout,
  useResumeAgentRollout,
} from '../../hooks/useFleet';
import { handleApiError } from '../../api';
import {
  AgentRolloutStatus,
  AgentRolloutTarget,
  AgentRolloutTargetStatus,
} from '../../types/fleet';
import { formatDateTime, formatNumber, formatTimeAgo } from '../../utils';

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

const MetaItem: FC<{ label: string; value: string; mono?: boolean }> = ({ label, value, mono }) => (
  <div>
    <dt className="text-xs uppercase tracking-wide text-opsgrid-text-secondary">{label}</dt>
    <dd className={`mt-1 text-sm text-opsgrid-text ${mono ? 'font-mono break-all' : ''}`}>{value}</dd>
  </div>
);

function groupByWave(targets: AgentRolloutTarget[]): Record<number, AgentRolloutTarget[]> {
  return targets.reduce<Record<number, AgentRolloutTarget[]>>((acc, target) => {
    acc[target.wave_index] = acc[target.wave_index] || [];
    acc[target.wave_index].push(target);
    return acc;
  }, {});
}

function progress(targets: AgentRolloutTarget[]) {
  const total = targets.length;
  const terminal = targets.filter((target) =>
    ['success', 'failed', 'rolled_back', 'cancelled', 'skipped'].includes(target.status)
  ).length;
  const success = targets.filter((target) => target.status === 'success').length;
  const failed = targets.filter((target) => ['failed', 'rolled_back'].includes(target.status)).length;
  return { total, terminal, success, failed };
}

export const FleetRolloutDetail: FC = () => {
  const { rolloutId = '' } = useParams();
  const rollout = useAgentRollout(rolloutId);
  const pauseRollout = usePauseAgentRollout();
  const resumeRollout = useResumeAgentRollout();
  const cancelRollout = useCancelAgentRollout();
  // Narrowed once, here. `rollout.data!` appeared three times below because TypeScript
  // re-widens a property access inside a closure — a local binding it can narrow says
  // the same thing without telling the compiler to stop checking.
  const rolloutRow = rollout.data;
  const [actionError, setActionError] = useState<string | null>(null);

  const waveGroups = useMemo(
    () => groupByWave(rollout.data?.targets ?? []),
    [rollout.data?.targets]
  );
  const overall = progress(rollout.data?.targets ?? []);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <Link
            to="/admin/fleet"
            className="mb-2 inline-flex items-center gap-1 text-sm text-opsgrid-primary hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-opsgrid-primary rounded"
          >
            <ArrowLeft size={16} /> Fleet OTA
          </Link>
          <h1 className="text-2xl font-bold text-opsgrid-text">Rollout Detail</h1>
          <p className="text-sm text-opsgrid-text-secondary">Per-device state, command IDs, and rollout events.</p>
        </div>
      {actionError && (
        <p className="text-xs text-status-alarm" role="alert">
          {actionError}
        </p>
      )}
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" onClick={() => rollout.refetch()}>
            <RefreshCw size={16} className="mr-2" />
            Refresh
          </Button>
          {rolloutRow &&
            (['pending', 'running'].includes(rollout.data.status) ||
              (rollout.data.status === 'paused' &&
                rollout.data.pause_reason === 'maintenance_window')) && (
            <Button
              variant="secondary"
              onClick={() => pauseRollout.mutate(rolloutRow.id)}
              loading={pauseRollout.isPending}
            >
              {rollout.data.pause_reason === 'maintenance_window'
                ? 'Hold manually'
                : 'Pause'}
            </Button>
          )}
          {rolloutRow?.status === 'paused' && (
            <Button
              variant="secondary"
              onClick={() =>
                resumeRollout.mutate(rolloutRow.id, {
                  // A resume that fails leaves the rollout PAUSED while the button that
                  // was just pressed reports nothing — the fleet sits waiting for an
                  // update the operator believes they released.
                  onError: (e: unknown) => setActionError(handleApiError(e).message),
                })
              }
              loading={resumeRollout.isPending}
            >
              Resume
            </Button>
          )}
          {rolloutRow && ['pending', 'running', 'paused'].includes(rolloutRow.status) && (
            <Button
              variant="danger"
              onClick={() => cancelRollout.mutate(rolloutRow.id)}
              loading={cancelRollout.isPending}
            >
              Cancel
            </Button>
          )}
        </div>
      </div>

      {/* PAUSE AND CANCEL SAY WHEN THEY FAIL (FS-480).
      
          Both read only `isPending` before this. An operator cancelling a rollout that is
          going wrong saw the spinner stop and the badge still read "running" — which is
          exactly what it looks like a moment before the refetch, so the reasonable reading
          is that it worked. On an OTA rollout that is a fleet still taking a bad release
          while somebody believes they stopped it.
      
          The mutations live in `useFleet.ts`; the sweep that catches this class everywhere
          else scans `.tsx` only, so neither it nor the hand-rolled sweep could see them. */}
      {(pauseRollout.isError || cancelRollout.isError) && (
        <Card className="p-4">
          <p role="alert" className="text-sm text-status-alarm">
            {cancelRollout.isError
              ? 'Could not cancel this rollout — it is still running. Try again, or check the fleet service.'
              : 'Could not pause this rollout — it is still running. Try again, or check the fleet service.'}
          </p>
        </Card>
      )}

      {rollout.isLoading ? (
        <Card noPadding><SkeletonCard lines={4} /></Card>
      ) : rollout.isError || !rollout.data ? (
        <Card>
          <div role="alert" className="flex items-center gap-2 text-status-alarm">
            <AlertTriangle size={18} /> Rollout not found or failed to load.
          </div>
        </Card>
      ) : (
        <>
          <Card>
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-semibold text-opsgrid-text">{rollout.data.name}</h2>
              <Badge variant={ROLLOUT_STATUS_VARIANT[rollout.data.status]}>{rollout.data.status}</Badge>
            </div>
            <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4 xl:grid-cols-8">
              <MetaItem label="Release" value={rollout.data.release_id} mono />
              <MetaItem label="Targets" value={formatNumber(overall.total, 0)} />
              <MetaItem label="Completed" value={`${overall.terminal}/${overall.total}`} />
              <MetaItem label="Success" value={formatNumber(overall.success, 0)} />
              <MetaItem label="Failed / rolled back" value={formatNumber(overall.failed, 0)} />
              <MetaItem
                label="Not before"
                value={
                  rollout.data.scheduled_start_at
                    ? formatDateTime(rollout.data.scheduled_start_at)
                    : 'Immediate'
                }
              />
              <MetaItem
                label="Window policy"
                value={
                  rollout.data.enforce_maintenance_windows
                    ? 'Enforced'
                    : 'Not enforced'
                }
              />
              <MetaItem
                label="Next eligible"
                value={
                  rollout.data.next_eligible_at
                    ? formatDateTime(rollout.data.next_eligible_at)
                    : '—'
                }
              />
              <MetaItem label="Updated" value={rollout.data.updated_at ? formatTimeAgo(rollout.data.updated_at) : 'Unknown'} />
            </dl>
            {rollout.data.pause_reason && (
              <div className="mt-4 rounded-lg border border-status-warning/40 bg-status-warning/10 p-3 text-sm text-opsgrid-text">
                Paused by{' '}
                {rollout.data.pause_reason === 'manual'
                  ? 'an administrator'
                  : 'the maintenance-window scheduler'}
                {rollout.data.next_eligible_at
                  ? ` until approximately ${formatDateTime(
                      rollout.data.next_eligible_at
                    )}`
                  : '.'}
              </div>
            )}
          </Card>

          <Card title="Wave progress" subtitle="Targets grouped by wave" noPadding>
            {Object.keys(waveGroups).length === 0 ? (
              <div className="p-8 text-center text-sm text-opsgrid-text-secondary">No targets were resolved for this rollout.</div>
            ) : (
              <div className="divide-y divide-opsgrid-border">
                {Object.entries(waveGroups).map(([waveIndex, targets]) => {
                  const waveProgress = progress(targets);
                  return (
                    <div key={waveIndex} className="p-4">
                      <div className="mb-3 flex items-center justify-between gap-4">
                        <div>
                          <h3 className="font-semibold text-opsgrid-text">Wave {waveIndex}</h3>
                          <p className="text-sm text-opsgrid-text-secondary">
                            {waveProgress.terminal}/{waveProgress.total} terminal · {waveProgress.success} success · {waveProgress.failed} failed
                          </p>
                        </div>
                        <div className="h-2 w-36 overflow-hidden rounded-full bg-opsgrid-border">
                          <div
                            className="h-full bg-opsgrid-primary"
                            style={{
                              width: waveProgress.total
                                ? `${Math.round((waveProgress.terminal / waveProgress.total) * 100)}%`
                                : '0%',
                            }}
                          />
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {targets.map((target) => (
                          <Badge key={target.id} variant={TARGET_STATUS_VARIANT[target.status]} tooltip={target.asset_id}>
                            {target.status}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>

          <Card title="Targets" subtitle="Per-device rollout state" noPadding>
            {rollout.isFetching && !rollout.data ? (
              <SkeletonTable rows={6} columns={9} />
            ) : rollout.data.targets.length === 0 ? (
              <div className="p-8 text-center text-sm text-opsgrid-text-secondary">No targets.</div>
            ) : (
              <Table>
                <Table.Head>
                  <Table.Row>
                    <Table.Header>Status</Table.Header>
                    <Table.Header>Asset</Table.Header>
                    <Table.Header>Site</Table.Header>
                    <Table.Header>Wave</Table.Header>
                    <Table.Header>Attempts</Table.Header>
                    <Table.Header>Command</Table.Header>
                    <Table.Header>Rollback</Table.Header>
                    <Table.Header>Failure</Table.Header>
                    <Table.Header>Completed</Table.Header>
                  </Table.Row>
                </Table.Head>
                <Table.Body>
                  {rollout.data.targets.map((target) => (
                    <Table.Row key={target.id}>
                      <Table.Cell><Badge variant={TARGET_STATUS_VARIANT[target.status]}>{target.status}</Badge></Table.Cell>
                      <Table.Cell className="font-mono text-xs">{target.asset_id}</Table.Cell>
                      <Table.Cell className="font-mono text-xs">
                        {target.site_id || 'Organization default'}
                      </Table.Cell>
                      <Table.Cell className="tabular-nums">{target.wave_index}</Table.Cell>
                      <Table.Cell className="tabular-nums">{target.attempts}</Table.Cell>
                      <Table.Cell className="max-w-[12rem] truncate font-mono text-xs" title={target.command_id || undefined}>
                        {target.command_id || '—'}
                      </Table.Cell>
                      <Table.Cell className="max-w-[12rem] truncate font-mono text-xs" title={target.rollback_command_id || undefined}>
                        {target.rollback_command_id || '—'}
                      </Table.Cell>
                      <Table.Cell className="max-w-xs truncate" title={target.failure_reason || undefined}>
                        {target.failure_reason || '—'}
                      </Table.Cell>
                      <Table.Cell title={target.completed_at ? formatDateTime(target.completed_at) : undefined}>
                        {target.completed_at ? formatTimeAgo(target.completed_at) : '—'}
                      </Table.Cell>
                    </Table.Row>
                  ))}
                </Table.Body>
              </Table>
            )}
          </Card>

          <Card title="Events" subtitle="Append-only rollout timeline" noPadding>
            {rollout.data.events.length === 0 ? (
              <div className="p-8 text-center text-sm text-opsgrid-text-secondary">No rollout events recorded.</div>
            ) : (
              <Table>
                <Table.Head>
                  <Table.Row>
                    <Table.Header>Event</Table.Header>
                    <Table.Header>Asset</Table.Header>
                    <Table.Header>Detail</Table.Header>
                    <Table.Header>Time</Table.Header>
                  </Table.Row>
                </Table.Head>
                <Table.Body>
                  {rollout.data.events.map((event) => (
                    <Table.Row key={event.id}>
                      <Table.Cell className="font-medium">{event.event_type}</Table.Cell>
                      <Table.Cell className="font-mono text-xs">{event.asset_id || '—'}</Table.Cell>
                      <Table.Cell className="max-w-xl truncate font-mono text-xs" title={JSON.stringify(event.detail)}>
                        {JSON.stringify(event.detail)}
                      </Table.Cell>
                      <Table.Cell title={event.created_at ? formatDateTime(event.created_at) : undefined}>
                        {event.created_at ? formatTimeAgo(event.created_at) : 'Unknown'}
                      </Table.Cell>
                    </Table.Row>
                  ))}
                </Table.Body>
              </Table>
            )}
          </Card>
        </>
      )}
    </div>
  );
};

export default FleetRolloutDetail;
