import { FC, FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowLeft,
  CalendarClock,
  Edit3,
  Eye,
  Power,
  RefreshCw,
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
  useCreateMaintenanceWindow,
  useDisableMaintenanceWindow,
  useFleetSites,
  useMaintenanceWindows,
  usePreviewMaintenanceWindows,
  useUpdateMaintenanceWindow,
} from '../../hooks/useFleet';
import { handleApiError } from '../../api';
import {
  MaintenanceWindow,
  MaintenanceWindowWeekday,
} from '../../types/fleet';
import { formatDateTime } from '../../utils';

const WEEKDAYS: Array<{ value: MaintenanceWindowWeekday; label: string }> = [
  { value: 0, label: 'Mon' },
  { value: 1, label: 'Tue' },
  { value: 2, label: 'Wed' },
  { value: 3, label: 'Thu' },
  { value: 4, label: 'Fri' },
  { value: 5, label: 'Sat' },
  { value: 6, label: 'Sun' },
];

interface WindowForm {
  id: string;
  name: string;
  site_id: string;
  timezone: string;
  weekdays: MaintenanceWindowWeekday[];
  local_start_time: string;
  local_end_time: string;
  enabled: boolean;
}

const browserTimezone =
  Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

const emptyForm: WindowForm = {
  id: '',
  name: '',
  site_id: '',
  timezone: browserTimezone,
  weekdays: [0, 1, 2, 3, 4],
  local_start_time: '02:00',
  local_end_time: '04:00',
  enabled: true,
};

function formForWindow(window: MaintenanceWindow): WindowForm {
  return {
    id: window.id,
    name: window.name,
    site_id: window.site_id || '',
    timezone: window.timezone,
    weekdays: window.weekdays,
    local_start_time: window.local_start_time.slice(0, 5),
    local_end_time: window.local_end_time.slice(0, 5),
    enabled: window.enabled,
  };
}

function weekdayLabel(days: MaintenanceWindowWeekday[]): string {
  if (days.length === 7) return 'Every day';
  return WEEKDAYS.filter((day) => days.includes(day.value))
    .map((day) => day.label)
    .join(', ');
}

export const MaintenanceWindows: FC = () => {
  const windows = useMaintenanceWindows();
  const sites = useFleetSites();
  const createWindow = useCreateMaintenanceWindow();
  const updateWindow = useUpdateMaintenanceWindow();
  const disableWindow = useDisableMaintenanceWindow();
  const previewWindows = usePreviewMaintenanceWindows();

  const [form, setForm] = useState<WindowForm>(emptyForm);
  const [previewSiteId, setPreviewSiteId] = useState('');
  const [previewAt, setPreviewAt] = useState('');
  const [feedback, setFeedback] = useState('');

  const siteOptions = (sites.data ?? []).map((site) => ({
    value: site.id,
    label: site.name,
  }));

  const resetForm = () => {
    setForm(emptyForm);
    setFeedback('');
  };

  const toggleWeekday = (weekday: MaintenanceWindowWeekday) => {
    setForm((current) => ({
      ...current,
      weekdays: current.weekdays.includes(weekday)
        ? current.weekdays.filter((value) => value !== weekday)
        : [...current.weekdays, weekday].sort(),
    }));
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setFeedback('');
    if (!form.name.trim() || !form.timezone.trim()) {
      setFeedback('Name and IANA timezone are required.');
      return;
    }
    if (form.weekdays.length === 0) {
      setFeedback('Select at least one weekday.');
      return;
    }
    if (form.local_start_time === form.local_end_time) {
      setFeedback('Start and end times must differ.');
      return;
    }
    const payload = {
      name: form.name.trim(),
      site_id: form.site_id || null,
      timezone: form.timezone.trim(),
      weekdays: form.weekdays,
      local_start_time: form.local_start_time,
      local_end_time: form.local_end_time,
      enabled: form.enabled,
    };
    const options = {
      onSuccess: () => {
        resetForm();
        setFeedback('Maintenance window saved.');
      },
      onError: (error: Error) => setFeedback(handleApiError(error).message),
    };
    if (form.id) {
      updateWindow.mutate({ windowId: form.id, payload }, options);
    } else {
      createWindow.mutate(payload, options);
    }
  };

  const preview = () => {
    setFeedback('');
    let at: string | undefined;
    if (previewAt) {
      const parsed = new Date(previewAt);
      if (Number.isNaN(parsed.getTime())) {
        setFeedback('Preview time is invalid.');
        return;
      }
      at = parsed.toISOString();
    }
    previewWindows.mutate(
      {
        site_ids: [previewSiteId || null],
        at,
        horizon_days: 15,
      },
      {
        onError: (error) => setFeedback(handleApiError(error).message),
      }
    );
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <Link
            to="/admin/fleet"
            className="mb-2 inline-flex items-center gap-1 rounded text-sm text-opsgrid-primary hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-opsgrid-primary"
          >
            <ArrowLeft size={16} /> Fleet OTA
          </Link>
          <h1 className="text-2xl font-bold text-opsgrid-text">
            Maintenance Windows
          </h1>
          <p className="text-sm text-opsgrid-text-secondary">
            Recurring site or organization windows. Times use the selected IANA timezone and support overnight ranges.
          </p>
        </div>
        <Button
          variant="secondary"
          onClick={() => {
            windows.refetch();
            sites.refetch();
          }}
        >
          <RefreshCw size={16} className="mr-2" /> Refresh
        </Button>
      </div>

      {feedback && (
        <div
          role="status"
          className="rounded-lg border border-opsgrid-border bg-opsgrid-panel p-3 text-sm text-opsgrid-text"
        >
          {feedback}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card
          title={form.id ? 'Edit window' : 'Create window'}
          subtitle="Monday is weekday 0 in the API; this form handles that mapping."
        >
          <form className="space-y-4" onSubmit={submit}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Input
                label="Name"
                value={form.name}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
                placeholder="Plant A night shift"
              />
              <Select
                label="Scope"
                value={form.site_id}
                onChange={(event) =>
                  setForm({ ...form, site_id: event.target.value })
                }
                options={[
                  { value: '', label: 'Organization default' },
                  ...siteOptions,
                ]}
              />
              <Input
                label="IANA timezone"
                value={form.timezone}
                onChange={(event) =>
                  setForm({ ...form, timezone: event.target.value })
                }
                placeholder="America/Chicago"
                helperText="Examples: UTC, America/Chicago, Asia/Tokyo."
              />
              <div className="flex items-end">
                <label className="flex min-h-[42px] w-full items-center gap-2 rounded-lg border border-opsgrid-border bg-opsgrid-bg px-3 text-sm text-opsgrid-text">
                  <input
                    type="checkbox"
                    checked={form.enabled}
                    onChange={(event) =>
                      setForm({ ...form, enabled: event.target.checked })
                    }
                  />
                  Enabled
                </label>
              </div>
              <Input
                label="Local start"
                type="time"
                value={form.local_start_time}
                onChange={(event) =>
                  setForm({
                    ...form,
                    local_start_time: event.target.value,
                  })
                }
              />
              <Input
                label="Local end"
                type="time"
                value={form.local_end_time}
                onChange={(event) =>
                  setForm({ ...form, local_end_time: event.target.value })
                }
                helperText={
                  form.local_end_time < form.local_start_time
                    ? 'Ends the following day.'
                    : undefined
                }
              />
            </div>

            <fieldset>
              <legend className="mb-2 text-sm font-medium text-opsgrid-text">
                Weekdays
              </legend>
              <div className="flex flex-wrap gap-2">
                {WEEKDAYS.map((weekday) => (
                  <label
                    key={weekday.value}
                    className="flex items-center gap-2 rounded-lg border border-opsgrid-border bg-opsgrid-bg px-3 py-2 text-sm text-opsgrid-text"
                  >
                    <input
                      type="checkbox"
                      checked={form.weekdays.includes(weekday.value)}
                      onChange={() => toggleWeekday(weekday.value)}
                    />
                    {weekday.label}
                  </label>
                ))}
              </div>
            </fieldset>

            <div className="flex justify-end gap-2">
              {form.id && (
                <Button type="button" variant="ghost" onClick={resetForm}>
                  Cancel
                </Button>
              )}
              <Button
                type="submit"
                loading={createWindow.isLoading || updateWindow.isLoading}
              >
                {form.id ? 'Save changes' : 'Create window'}
              </Button>
            </div>
          </form>
        </Card>

        <Card
          title="Calendar preview"
          subtitle="Shows the effective site override or organization fallback."
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Select
              label="Scope"
              value={previewSiteId}
              onChange={(event) => setPreviewSiteId(event.target.value)}
              options={[
                { value: '', label: 'Organization default' },
                ...siteOptions,
              ]}
            />
            <Input
              label={`At (${browserTimezone})`}
              type="datetime-local"
              value={previewAt}
              onChange={(event) => setPreviewAt(event.target.value)}
              helperText="Leave blank to evaluate now."
            />
          </div>
          <div className="mt-4 flex justify-end">
            <Button
              variant="secondary"
              onClick={preview}
              loading={previewWindows.isLoading}
            >
              <Eye size={16} className="mr-2" /> Preview
            </Button>
          </div>

          {previewWindows.data && (
            <div className="mt-4 space-y-3">
              <div className="rounded-lg border border-opsgrid-border bg-opsgrid-bg p-3">
                <div className="flex items-center gap-2">
                  <Badge
                    variant={
                      previewWindows.data.is_open ? 'success' : 'warning'
                    }
                  >
                    {previewWindows.data.is_open ? 'Open' : 'Closed'}
                  </Badge>
                  <span className="text-sm text-opsgrid-text">
                    {previewWindows.data.is_open
                      ? `Closes ${formatDateTime(
                          previewWindows.data.current_closes_at || ''
                        )}`
                      : previewWindows.data.next_eligible_at
                      ? `Next opens ${formatDateTime(
                          previewWindows.data.next_eligible_at
                        )}`
                      : 'No opening found'}
                  </span>
                </div>
                {previewWindows.data.missing_scopes.length > 0 && (
                  <p className="mt-2 text-sm text-status-alarm">
                    Missing window: {previewWindows.data.missing_scopes.join(', ')}
                  </p>
                )}
              </div>
              <div className="max-h-56 space-y-2 overflow-auto">
                {previewWindows.data.occurrences.slice(0, 12).map((item) => (
                  <div
                    key={`${item.start_at}-${item.end_at}`}
                    className="flex items-center gap-2 text-sm text-opsgrid-text-secondary"
                  >
                    <CalendarClock size={15} />
                    {formatDateTime(item.start_at)} – {formatDateTime(item.end_at)}
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      </div>

      <Card
        title="Configured windows"
        subtitle="Site-specific enabled windows override organization defaults."
        noPadding
      >
        {windows.isLoading && !windows.data ? (
          <SkeletonTable rows={5} columns={6} />
        ) : windows.isError ? (
          <div role="alert" className="p-6 text-status-alarm">
            Failed to load maintenance windows.
          </div>
        ) : (windows.data ?? []).length === 0 ? (
          <div className="p-8 text-center text-sm text-opsgrid-text-secondary">
            No maintenance windows configured.
          </div>
        ) : (
          <Table>
            <Table.Head>
              <Table.Row>
                <Table.Header>Status</Table.Header>
                <Table.Header>Name / scope</Table.Header>
                <Table.Header>Recurrence</Table.Header>
                <Table.Header>Timezone</Table.Header>
                <Table.Header>Updated</Table.Header>
                <Table.Header>Actions</Table.Header>
              </Table.Row>
            </Table.Head>
            <Table.Body>
              {(windows.data ?? []).map((window) => (
                <Table.Row key={window.id}>
                  <Table.Cell>
                    <Badge variant={window.enabled ? 'success' : 'neutral'}>
                      {window.enabled ? 'Enabled' : 'Disabled'}
                    </Badge>
                  </Table.Cell>
                  <Table.Cell>
                    <div className="font-medium">{window.name}</div>
                    <div className="text-xs text-opsgrid-text-secondary">
                      {window.site_name || 'Organization default'}
                    </div>
                  </Table.Cell>
                  <Table.Cell>
                    <div className="font-mono text-xs">
                      {window.local_start_time.slice(0, 5)}–
                      {window.local_end_time.slice(0, 5)}
                      {window.overnight ? ' +1d' : ''}
                    </div>
                    <div className="text-xs text-opsgrid-text-secondary">
                      {weekdayLabel(window.weekdays)}
                    </div>
                  </Table.Cell>
                  <Table.Cell className="font-mono text-xs">
                    {window.timezone}
                  </Table.Cell>
                  <Table.Cell>
                    {window.updated_at
                      ? formatDateTime(window.updated_at)
                      : 'Unknown'}
                  </Table.Cell>
                  <Table.Cell>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          setForm(formForWindow(window));
                          globalThis.window.scrollTo({
                            top: 0,
                            behavior: 'smooth',
                          });
                        }}
                      >
                        <Edit3 size={14} className="mr-1" /> Edit
                      </Button>
                      {window.enabled ? (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => disableWindow.mutate(window.id)}
                          loading={disableWindow.isLoading}
                        >
                          <Power size={14} className="mr-1" /> Disable
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            updateWindow.mutate({
                              windowId: window.id,
                              payload: { enabled: true },
                            })
                          }
                          loading={updateWindow.isLoading}
                        >
                          <Power size={14} className="mr-1" /> Enable
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
    </div>
  );
};

export default MaintenanceWindows;
