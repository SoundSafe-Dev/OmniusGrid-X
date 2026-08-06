import { FC, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
} from 'recharts';
import { ArrowLeft, Copy, Check, AlertTriangle } from 'lucide-react';
import {
  Card,
  Badge,
  Button,
  ChartContainer,
  SkeletonCard,
} from '../../components/ui';
import { useErrorDetail, useUpdateErrorStatus } from '../../hooks/useErrorTriage';
import { ErrorStatus } from '../../types/errorTriage';
import { formatDateTime, formatNumber } from '../../utils';

const STATUS_VARIANT: Record<ErrorStatus, 'error' | 'warning' | 'success'> = {
  open: 'error',
  acknowledged: 'warning',
  resolved: 'success',
};

const STATUS_LABEL: Record<ErrorStatus, string> = {
  open: 'Open',
  acknowledged: 'Acknowledged',
  resolved: 'Resolved',
};

const MetaItem: FC<{ label: string; value: string; mono?: boolean }> = ({ label, value, mono }) => (
  <div>
    <dt className="text-xs uppercase tracking-wide text-opsgrid-text-secondary">{label}</dt>
    <dd className={`mt-1 text-sm text-opsgrid-text ${mono ? 'font-mono' : ''}`}>{value}</dd>
  </div>
);

export const ErrorTriageDetail: FC = () => {
  const { fingerprint = '' } = useParams();
  const { data, isLoading, isError } = useErrorDetail(fingerprint);
  const updateStatus = useUpdateErrorStatus();

  const [confirmingResolve, setConfirmingResolve] = useState(false);
  const [copied, setCopied] = useState(false);
  const [announce, setAnnounce] = useState('');

  const changeStatus = (status: ErrorStatus) => {
    updateStatus.mutate(
      { fingerprint, status },
      {
        onSuccess: () => setAnnounce(`Status changed to ${STATUS_LABEL[status]}`),
        onError: () => setAnnounce('Failed to change status'),
      }
    );
    setConfirmingResolve(false);
  };

  const copyTraceback = async () => {
    if (!data?.traceback_sample) return;
    try {
      await navigator.clipboard.writeText(data.traceback_sample);
      setCopied(true);
      setAnnounce('Traceback copied to clipboard');
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setAnnounce('Copy failed');
    }
  };

  const seriesData = (data?.series ?? []).map((p) => ({
    hour: new Date(p.hour).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric' }),
    count: p.count,
  }));

  return (
    <div className="space-y-6">
      <Link
        to="/admin/errors"
        className="inline-flex items-center gap-1 text-sm text-opsgrid-primary hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-opsgrid-primary rounded"
      >
        <ArrowLeft size={16} /> Error Triage
      </Link>

      {/* Live region for status/copy announcements */}
      <div aria-live="polite" className="sr-only">{announce}</div>

      {isLoading ? (
        <Card noPadding><SkeletonCard lines={4} /></Card>
      ) : isError || !data ? (
        <Card>
          <div role="alert" className="flex items-center gap-2 text-status-alarm">
            <AlertTriangle size={18} /> Unknown or expired fingerprint.
          </div>
          <Link to="/admin/errors" className="mt-4 inline-block text-opsgrid-primary hover:underline">
            Back to Error Triage
          </Link>
        </Card>
      ) : (
        <>
          {/* Header */}
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="font-mono text-xl font-bold text-opsgrid-text break-all">{data.exception_type}</h1>
                <Badge variant={STATUS_VARIANT[data.status]}>{STATUS_LABEL[data.status]}</Badge>
                {data.regression_count > 0 && (
                  <Badge variant="warning" tooltip="Reopened after being resolved">
                    Regression ×{data.regression_count}
                  </Badge>
                )}
              </div>
              <p className="mt-1 font-mono text-sm text-opsgrid-text-secondary break-all">
                {data.method} {data.route}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {data.status === 'open' && (
                <Button variant="secondary" onClick={() => changeStatus('acknowledged')} loading={updateStatus.isPending}>
                  Acknowledge
                </Button>
              )}
              {data.status !== 'resolved' && !confirmingResolve && (
                <Button variant="primary" onClick={() => setConfirmingResolve(true)}>Resolve</Button>
              )}
              {confirmingResolve && (
                <>
                  <Button variant="primary" onClick={() => changeStatus('resolved')} loading={updateStatus.isPending}>
                    Confirm resolve
                  </Button>
                  <Button variant="ghost" onClick={() => setConfirmingResolve(false)}>Cancel</Button>
                </>
              )}
              {data.status === 'resolved' && (
                <Button variant="secondary" onClick={() => changeStatus('open')} loading={updateStatus.isPending}>
                  Reopen
                </Button>
              )}
            </div>
          </div>

          {/* Meta grid */}
          <Card>
            <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
              <MetaItem label="Total" value={formatNumber(data.total_count, 0)} />
              <MetaItem label="In range (7d)" value={formatNumber(data.count_in_range, 0)} />
              <MetaItem label="Regressions" value={formatNumber(data.regression_count, 0)} />
              <MetaItem label="Status code" value={String(data.status_code)} />
              <MetaItem label="First seen" value={formatDateTime(data.first_seen)} />
              <MetaItem label="Last seen" value={formatDateTime(data.last_seen)} />
            </dl>
          </Card>

          {/* Trend */}
          <ChartContainer title="Occurrences" subtitle="Per hour, last 7 days" height={200}>
            {seriesData.length === 0 ? (
              <div className="flex h-full items-center justify-center text-sm text-opsgrid-text-secondary">
                No occurrences in the last 7 days.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={seriesData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--opsgrid-border, #2a2a2a)" />
                  <XAxis dataKey="hour" tick={{ fontSize: 11 }} stroke="currentColor" className="text-opsgrid-text-secondary" />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} stroke="currentColor" className="text-opsgrid-text-secondary" />
                  <RechartsTooltip />
                  <Bar dataKey="count" fill="#ef4444" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </ChartContainer>

          {/* Traceback.

              THE PLACEHOLDER STAYS IN THE BLOCK, DELIBERATELY. `ErrorTriageDetail.test.tsx`
              asserts it: "No traceback captured." is a claim about the error and the
              redaction is a claim about the viewer's permissions, and showing the first
              where the second is true tells an operator the wrong thing. That decision is
              older than this comment and is not being reversed.

              WHAT WAS WRONG WAS AROUND IT (FS-477). The subtitle promised "Latest
              occurrence · scrubbed of PII" over a sentence that is neither, and Copy was
              ENABLED — the marker is a truthy string, so an operator could paste
              "[redacted: belongs to another organization]" into a bug report believing it
              was a stack trace.

              Both now read `samples_redacted` rather than matching the server's wording,
              because prose is not an API: matching the marker text would work today and
              break the day somebody improves it. */}
          <Card
            noPadding
            title="Sample traceback"
            subtitle={
              data.samples_redacted
                ? 'Withheld — this error belongs to another organisation'
                : 'Latest occurrence · scrubbed of PII'
            }
            action={
              <Button
                variant="ghost"
                size="sm"
                onClick={copyTraceback}
                disabled={!data.traceback_sample || data.samples_redacted}
              >
                {copied ? <Check size={16} className="mr-1.5" /> : <Copy size={16} className="mr-1.5" />}
                {copied ? 'Copied' : 'Copy'}
              </Button>
            }
          >
            <pre className="overflow-x-auto p-4 text-xs font-mono text-opsgrid-text whitespace-pre">
              {data.traceback_sample || 'No traceback captured.'}
            </pre>
          </Card>
        </>
      )}
    </div>
  );
};

export default ErrorTriageDetail;
