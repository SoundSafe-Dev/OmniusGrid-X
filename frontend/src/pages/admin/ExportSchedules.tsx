import { FC, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CalendarClock, Pause, Play, Plus, Trash2 } from 'lucide-react';
import { Card, Button, Badge, Table, SkeletonTable, Input } from '../../components/ui';
import {
  exportSchedulesApi,
  ScheduledExport,
  ExportTemplate,
} from '../../api/exportDeliveries';
import { formatDateTime } from '../../utils';

/**
 * The schedules behind the deliveries (P9, page-enhancement review).
 *
 * THE BIGGEST HOLE THE PAGE SURVEY FOUND: nine endpoints — schedules
 * list/create/get/update/delete plus the template routes — with **zero frontend
 * references**. `/admin/export-deliveries` showed that a scheduled report failed while
 * nothing in the product could say what the schedule was, who received it, when it next
 * ran, or how to pause it. The delivery log answered "did it go out?"; this answers
 * "what is it, and can I stop it?".
 *
 * Two things are said out loud that the server goes out of its way to send:
 *
 *   * `delivery_configured` — whether SMTP exists at all. A fleet of perfectly valid
 *     schedules delivering to nowhere is otherwise indistinguishable from a working
 *     setup until the reports fail to arrive, one by one.
 *   * `last_status` per schedule, beside its next run. A schedule whose last send failed
 *     is the one an admin came here about.
 *
 * Pausing is `is_active: false` through the existing PUT, not a delete: an admin who
 * wants a report to stop this month should not have to destroy its definition and
 * remember how to rebuild it.
 */

const FREQUENCIES = ['daily', 'weekly', 'monthly'];

/** Status → how it should read. An unknown status falls to neutral rather than to
 *  success — a server that grows a new state must not render it as good news here. */
const TONE: Record<string, 'success' | 'error' | 'warning' | 'neutral'> = {
  sent: 'success',
  failed: 'error',
  sending: 'warning',
  queued: 'neutral',
};

export const ExportSchedules: FC = () => {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['export-schedules'],
    queryFn: () => exportSchedulesApi.list(),
  });
  const { data: templates } = useQuery({
    queryKey: ['export-templates'],
    queryFn: () => exportSchedulesApi.listTemplates(),
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['export-schedules'] });

  // Failure handled ON THE MUTATION, not per call site: a reader of the mutation can see
  // that it reports, and `mutationFailureIsVisible` can too — it flagged the first draft,
  // which handled errors at each `mutate(...)` call and looked silent from here. The
  // schedule name rides in the variables so the message can still name what did not
  // happen, which is the whole point of saying it.
  const toggle = useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean; name: string }) =>
      exportSchedulesApi.update(id, { is_active: isActive }),
    onSuccess: invalidate,
    onError: (_error, variables) =>
      setActionError(
        `Could not ${variables.isActive ? 'resume' : 'pause'} "${variables.name}" — it is unchanged.`,
      ),
  });
  const remove = useMutation({
    mutationFn: ({ id }: { id: string; name: string }) => exportSchedulesApi.remove(id),
    onSuccess: invalidate,
    onError: (_error, variables) =>
      setActionError(
        `Could not delete "${variables.name}" — it still exists and will run.`,
      ),
  });

  const schedules: ScheduledExport[] = data?.items ?? [];
  const templateName = (id: string) =>
    templates?.items.find((t: ExportTemplate) => t.id === id)?.name ?? id;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-opsgrid-text">Scheduled exports</h1>
          <p className="text-sm text-opsgrid-text-secondary mt-1">
            The report schedules behind the delivery log — what runs, when, and to whom.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => refetch()}>
            Refresh
          </Button>
          <Button onClick={() => setShowCreate((open) => !open)}>
            <Plus className="w-4 h-4 mr-1" />
            New schedule
          </Button>
        </div>
      </div>

      {/* A failed action, said out loud. A pause that silently did not happen leaves an
          admin believing a report has stopped going out when it has not. */}
      {actionError && (
        <div
          role="alert"
          className="rounded border border-status-alarm/40 bg-status-alarm/10 px-3 py-2 text-sm text-status-alarm"
        >
          {actionError}
        </div>
      )}

      {/* The server sends `delivery_configured` precisely so this can be said rather
          than inferred from reports that never arrive. */}
      {data && !data.delivery_configured && (
        <div className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
          No delivery channel is configured — SMTP is not set up, so these schedules will
          run and their reports will reach nobody.
        </div>
      )}

      {showCreate && (
        <CreateScheduleForm
          templates={templates?.items ?? []}
          onDone={() => {
            setShowCreate(false);
            invalidate();
          }}
          onError={setActionError}
        />
      )}

      <Card>
        {isLoading && <SkeletonTable rows={4} />}

        {/* A failed load is not an empty schedule list: "nothing is scheduled" is a fact
            about the org, "we could not ask" is a fact about the request, and only one of
            them means an admin should stop worrying about the report that never came. */}
        {isError && (
          <div className="p-6 text-center" role="alert">
            <p className="text-status-alarm">Could not load scheduled exports.</p>
            <Button variant="secondary" className="mt-3" onClick={() => refetch()}>
              Retry
            </Button>
          </div>
        )}

        {!isLoading && !isError && schedules.length === 0 && (
          <div className="p-8 text-center text-opsgrid-text-secondary">
            <CalendarClock className="w-6 h-6 mx-auto mb-2 opacity-60" />
            <p>No scheduled exports yet.</p>
            <p className="text-sm mt-1">
              A schedule sends a saved export template to a list of recipients on a timer.
            </p>
          </div>
        )}

        {!isLoading && !isError && schedules.length > 0 && (
          <Table>
            <thead>
              <tr>
                <th className="text-left p-3">Name</th>
                <th className="text-left p-3">Template</th>
                <th className="text-left p-3">Frequency</th>
                <th className="text-left p-3">Next run</th>
                <th className="text-left p-3">Recipients</th>
                <th className="text-left p-3">Last send</th>
                <th className="text-right p-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {schedules.map((schedule) => (
                <tr key={schedule.id} className="border-t border-opsgrid-border">
                  <td className="p-3">
                    <span className="font-medium">{schedule.name}</span>
                    {!schedule.is_active && (
                      <Badge variant="neutral" className="ml-2">paused</Badge>
                    )}
                  </td>
                  <td className="p-3 text-opsgrid-text-secondary">
                    {templateName(schedule.template_id)}
                  </td>
                  <td className="p-3">
                    {schedule.frequency}
                    <span className="text-opsgrid-text-secondary"> · {schedule.timezone}</span>
                  </td>
                  <td className="p-3">
                    {/* A paused schedule has a next_run_at that will not happen. Saying
                        "paused" here rather than printing the stale date keeps the column
                        from asserting a run nobody will get. */}
                    {schedule.is_active
                      ? schedule.next_run_at
                        ? formatDateTime(schedule.next_run_at)
                        : '—'
                      : 'paused'}
                  </td>
                  <td className="p-3 text-opsgrid-text-secondary">
                    {schedule.recipients.length === 0 ? (
                      <span className="text-amber-300">nobody</span>
                    ) : (
                      schedule.recipients.join(', ')
                    )}
                  </td>
                  <td className="p-3">
                    {schedule.last_status ? (
                      <>
                        <Badge variant={TONE[schedule.last_status] ?? 'neutral'}>
                          {schedule.last_status}
                        </Badge>
                        {schedule.last_run_at && (
                          <span className="text-opsgrid-text-secondary ml-2">
                            {formatDateTime(schedule.last_run_at)}
                          </span>
                        )}
                      </>
                    ) : (
                      <span className="text-opsgrid-text-secondary">never run</span>
                    )}
                  </td>
                  <td className="p-3 text-right whitespace-nowrap">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => {
                        setActionError(null);
                        toggle.mutate({
                          id: schedule.id,
                          isActive: !schedule.is_active,
                          name: schedule.name,
                        });
                      }}
                      aria-label={`${schedule.is_active ? 'Pause' : 'Resume'} ${schedule.name}`}
                    >
                      {schedule.is_active ? (
                        <Pause className="w-3.5 h-3.5" />
                      ) : (
                        <Play className="w-3.5 h-3.5" />
                      )}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="ml-2"
                      onClick={() => {
                        if (
                          !window.confirm(
                            `Delete the schedule "${schedule.name}"? Its definition is removed; pausing keeps it.`,
                          )
                        ) {
                          return;
                        }
                        setActionError(null);
                        remove.mutate({ id: schedule.id, name: schedule.name });
                      }}
                      aria-label={`Delete ${schedule.name}`}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
};

/**
 * Creating a schedule. Deliberately minimal: a template, a name, a cadence, a first run
 * and recipients — every field the POST requires and nothing invented on top.
 *
 * Created PAUSED by default (`is_active: false`, the server's own default): a schedule
 * that starts sending the moment it is saved gives no chance to check the recipient list,
 * and the recipient list is the part that is embarrassing to get wrong.
 */
const CreateScheduleForm: FC<{
  templates: ExportTemplate[];
  onDone: () => void;
  onError: (message: string) => void;
}> = ({ templates, onDone, onError }) => {
  const [templateId, setTemplateId] = useState('');
  const [name, setName] = useState('');
  const [frequency, setFrequency] = useState('daily');
  const [nextRunAt, setNextRunAt] = useState('');
  const [recipients, setRecipients] = useState('');

  const create = useMutation({
    mutationFn: () =>
      exportSchedulesApi.create({
        template_id: templateId,
        name,
        frequency,
        // The browser's zone, so "daily at 08:00" means the admin's morning. The server
        // takes an IANA name and validates it.
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
        // The server REQUIRES an aware datetime and rejects a naive one — a
        // datetime-local input has no zone, so the offset is attached here rather than
        // letting the request 400 with a message about tzinfo.
        next_run_at: nextRunAt ? new Date(nextRunAt).toISOString() : '',
        recipients: recipients
          .split(',')
          .map((address) => address.trim())
          .filter(Boolean),
        is_active: false,
      }),
    onSuccess: onDone,
    onError: () => onError('Could not create the schedule — nothing was saved.'),
  });

  const ready = templateId !== '' && name.trim() !== '' && nextRunAt !== '';

  return (
    <Card className="p-4">
      <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
        <label className="text-sm">
          <span className="block text-opsgrid-text-secondary mb-1">Template</span>
          <select
            aria-label="Template"
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
            className="w-full bg-opsgrid-bg border border-opsgrid-border rounded px-2 py-1.5 text-sm"
          >
            <option value="">Select a template…</option>
            {templates.map((template) => (
              <option key={template.id} value={template.id}>{template.name}</option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="block text-opsgrid-text-secondary mb-1">Name</span>
          <Input value={name} onChange={(e) => setName(e.target.value)} aria-label="Schedule name" />
        </label>
        <label className="text-sm">
          <span className="block text-opsgrid-text-secondary mb-1">Frequency</span>
          <select
            aria-label="Frequency"
            value={frequency}
            onChange={(e) => setFrequency(e.target.value)}
            className="w-full bg-opsgrid-bg border border-opsgrid-border rounded px-2 py-1.5 text-sm"
          >
            {FREQUENCIES.map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="block text-opsgrid-text-secondary mb-1">First run</span>
          <input
            type="datetime-local"
            aria-label="First run"
            value={nextRunAt}
            onChange={(e) => setNextRunAt(e.target.value)}
            className="w-full bg-opsgrid-bg border border-opsgrid-border rounded px-2 py-1.5 text-sm"
          />
        </label>
        <label className="text-sm">
          <span className="block text-opsgrid-text-secondary mb-1">Recipients</span>
          <Input
            value={recipients}
            onChange={(e) => setRecipients(e.target.value)}
            placeholder="a@example.com, b@example.com"
            aria-label="Recipients"
          />
        </label>
      </div>
      <div className="flex items-center gap-3 mt-3">
        <Button disabled={!ready || create.isPending} onClick={() => create.mutate()}>
          {create.isPending ? 'Creating…' : 'Create paused'}
        </Button>
        <span className="text-xs text-opsgrid-text-secondary">
          Created paused so the recipient list can be checked before anything sends.
        </span>
      </div>
    </Card>
  );
};

export default ExportSchedules;
