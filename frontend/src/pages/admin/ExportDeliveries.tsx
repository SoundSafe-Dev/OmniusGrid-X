import { FC } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Mail, RefreshCw } from 'lucide-react';
import { Card, Button, Badge, Table, SkeletonTable } from '../../components/ui';
import { exportDeliveriesApi, ExportDelivery } from '../../api/exportDeliveries';
import { formatDateTime } from '../../utils';

/**
 * Whether the reports somebody scheduled actually went out (FS-285).
 *
 * `GET /api/v1/exports/deliveries` has returned `status` and `error` per job for some time
 * and **no page called it.** A scheduled export that fails to send sets `status='failed'`
 * with the reason in `error`, and the only thing a user experienced was a report that did
 * not arrive — with nowhere in the product to find out why, or even that it had been tried.
 *
 * The failures are the point, so they are counted at the top and listed first. A page that
 * showed fifty successful sends and buried one failure on the second screen would be the
 * same silence in a longer form.
 */

const TERMINAL_FAILURE = 'failed';

/** Status → how it should read. `sent` is the only one that is good news, and an unknown
 *  status falls to `neutral` rather than to `success` — a server that grows a new state
 *  should not have it render as a success here by default. */
const TONE: Record<string, 'success' | 'error' | 'warning' | 'neutral'> = {
  sent: 'success',
  failed: 'error',
  sending: 'warning',
  queued: 'neutral',
};

const StatusBadge: FC<{ status: string }> = ({ status }) => (
  <Badge variant={TONE[status] ?? 'neutral'}>{status}</Badge>
);

export const ExportDeliveries: FC = () => {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['export-deliveries'],
    queryFn: () => exportDeliveriesApi.list(50),
  });

  const deliveries: ExportDelivery[] = data?.items ?? [];
  const failed = deliveries.filter((d) => d.status === TERMINAL_FAILURE);
  // Failures first, then the rest in the order the server sent them (most recent first).
  const ordered = [...failed, ...deliveries.filter((d) => d.status !== TERMINAL_FAILURE)];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-opsgrid-text">Scheduled export deliveries</h1>
          <p className="text-sm text-opsgrid-text-secondary">
            The last 50 attempts to send a scheduled report, and what happened to each.
          </p>
        </div>
        <Button variant="outline" onClick={() => refetch()}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      {/* A failed load is not an empty history (FS-489). "No deliveries" says nothing has
          been scheduled; this says nobody knows — and they are opposite instructions to
          whoever is waiting on a report. `isLoading` is read as well as `isError` because
          react-query retries, and during those seconds `deliveries` is empty and
          `isError` is false. */}
      {isError && (
        <Card className="p-4">
          <p role="alert" className="text-sm text-status-alarm">
            Couldn’t load delivery history — this is a loading failure, not an empty one. A
            report you are waiting on may still have failed to send.
          </p>
        </Card>
      )}

      {!isError && !isLoading && failed.length > 0 && (
        <Card className="p-4">
          <p role="alert" className="flex items-center gap-2 text-sm text-status-alarm">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            {failed.length === 1
              ? '1 scheduled report failed to send. Nobody received it.'
              : `${failed.length} scheduled reports failed to send. Nobody received them.`}
          </p>
        </Card>
      )}

      <Card noPadding>
        {isLoading ? (
          <SkeletonTable rows={6} columns={5} />
        ) : isError ? null : ordered.length === 0 ? (
          <div className="flex flex-col items-center py-10 text-opsgrid-text-secondary">
            <Mail className="mb-2 h-8 w-8" />
            <p>No scheduled deliveries have been attempted.</p>
          </div>
        ) : (
          <Table>
            <caption className="sr-only">Scheduled export delivery attempts</caption>
            <Table.Head>
              <Table.Row>
                <Table.Header scope="col">Status</Table.Header>
                <Table.Header scope="col">File</Table.Header>
                <Table.Header scope="col">Scheduled</Table.Header>
                <Table.Header scope="col">Completed</Table.Header>
                <Table.Header scope="col">Why it failed</Table.Header>
              </Table.Row>
            </Table.Head>
            <Table.Body>
              {ordered.map((delivery) => (
                <Table.Row key={delivery.id}>
                  <Table.Cell>
                    <StatusBadge status={delivery.status} />
                  </Table.Cell>
                  <Table.Cell>{delivery.filename ?? '—'}</Table.Cell>
                  <Table.Cell>
                    {delivery.scheduled_for ? formatDateTime(delivery.scheduled_for) : '—'}
                  </Table.Cell>
                  <Table.Cell>
                    {/* An em dash, never a date that is not there. A delivery still queued
                        has no completion time, and inventing one would make it look sent. */}
                    {delivery.completed_at ? formatDateTime(delivery.completed_at) : '—'}
                  </Table.Cell>
                  <Table.Cell className="max-w-md">
                    {/* The server's own message, unedited. A generic "delivery failed" here
                        would throw away the only actionable thing on the page — an SMTP
                        rejection and an expired credential need different people. */}
                    <span className="text-xs text-opsgrid-text-secondary">
                      {delivery.error ?? (delivery.status === TERMINAL_FAILURE ? 'no reason recorded' : '—')}
                    </span>
                  </Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
        )}
      </Card>
    </div>
  );
};

export default ExportDeliveries;
