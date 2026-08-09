import { FC, useMemo, useState, useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
} from 'recharts';
import { RefreshCw, AlertTriangle, Search } from 'lucide-react';
import {
  Card,
  Badge,
  Button,
  Input,
  Select,
  Table,
  SkeletonTable,
  ChartContainer,
} from '../../components/ui';
import { useErrorList, useErrorSummary } from '../../hooks/useErrorTriage';
import {
  ErrorRange,
  ErrorStatus,
  ErrorStatusFilter,
  ErrorSort,
  SortOrder,
} from '../../types/errorTriage';
import { cn, formatTimeAgo, formatDateTime, formatNumber } from '../../utils';

const PAGE_SIZE = 25;

const RANGE_OPTIONS = [
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: 'all', label: 'All time' },
];

const STATUS_OPTIONS = [
  { value: 'active', label: 'Active (open + ack)' },
  { value: 'open', label: 'Open' },
  { value: 'acknowledged', label: 'Acknowledged' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'all', label: 'All statuses' },
];

const SORT_OPTIONS = [
  { value: 'count', label: 'Occurrences' },
  { value: 'last_seen', label: 'Last seen' },
  { value: 'first_seen', label: 'First seen' },
];

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

/** Debounce a fast-changing value (used for the search box). */
function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

const SummaryCard: FC<{ label: string; value: string; tone?: 'default' | 'danger'; to?: string; hint?: string }> = ({
  label,
  value,
  tone = 'default',
  to,
  hint,
}) => {
  const body = (
    <Card hover={Boolean(to)} className="h-full">
      <p className="text-sm text-opsgrid-text-secondary">{label}</p>
      <p
        className={cn(
          'mt-2 text-2xl font-semibold tabular-nums',
          tone === 'danger' ? 'text-status-alarm' : 'text-opsgrid-text'
        )}
      >
        {value}
      </p>
      {hint && <p className="mt-1 text-xs text-opsgrid-text-secondary truncate" title={hint}>{hint}</p>}
    </Card>
  );
  return to ? (
    <Link to={to} className="block focus:outline-none focus-visible:ring-2 focus-visible:ring-opsgrid-primary rounded-lg">
      {body}
    </Link>
  ) : (
    body
  );
};

export const ErrorTriage: FC = () => {
  const [params, setParams] = useSearchParams();

  const range = (params.get('range') as ErrorRange) || '7d';
  const statusFilter = (params.get('status') as ErrorStatusFilter) || 'active';
  const sort = (params.get('sort') as ErrorSort) || 'count';
  const order = (params.get('order') as SortOrder) || 'desc';
  const page = Math.max(0, parseInt(params.get('page') || '0', 10) || 0);
  const qParam = params.get('q') || '';

  const [searchInput, setSearchInput] = useState(qParam);
  const debouncedSearch = useDebounced(searchInput, 300);

  // Push debounced search into the URL (resets to page 0 on a new query).
  useEffect(() => {
    if (debouncedSearch === qParam) return;
    const next = new URLSearchParams(params);
    if (debouncedSearch) next.set('q', debouncedSearch);
    else next.delete('q');
    next.delete('page');
    setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch]);

  const updateParam = (key: string, value: string, resetPage = true) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    if (resetPage) next.delete('page');
    setParams(next);
  };

  const listParams = useMemo(
    () => ({
      status: statusFilter,
      q: qParam || undefined,
      sort,
      order,
      range,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [statusFilter, qParam, sort, order, range, page]
  );

  const summary = useErrorSummary(range);

  // An em dash for "no figure", never a zero. A tile that cannot distinguish "none" from
  // "not known" is worse than a blank one, because a zero is an answer.
  const summaryFigure = (value: number | undefined) =>
    value === undefined ? '—' : formatNumber(value, 0);
  const summaryHint = summary.isError
    ? 'Could not load — this is not a count of zero'
    : summary.isLoading
      ? 'Loading…'
      : undefined;
  const list = useErrorList(listParams);

  const total = list.data?.total ?? 0;
  const items = list.data?.items ?? [];
  const rangeStart = page * PAGE_SIZE + 1;
  const rangeEnd = Math.min((page + 1) * PAGE_SIZE, total);
  const hasFilters = Boolean(qParam) || statusFilter !== 'active' || range !== '7d';

  const clearFilters = () => {
    setSearchInput('');
    setParams(new URLSearchParams());
  };

  const seriesData = (summary.data?.series ?? []).map((p) => ({
    hour: new Date(p.hour).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric' }),
    count: p.count,
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-opsgrid-text">Error Triage</h1>
          <p className="text-sm text-opsgrid-text-secondary">
            Production unhandled exceptions, grouped and ranked. Auto-refreshes every 30s.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="w-44">
            <Select
              aria-label="Time range"
              options={RANGE_OPTIONS}
              value={range}
              onChange={(e) => updateParam('range', e.target.value)}
            />
          </div>
          <Button
            variant="secondary"
            onClick={() => {
              summary.refetch();
              list.refetch();
            }}
            aria-label="Refresh now"
          >
            <RefreshCw size={16} className="mr-2" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      {/* ZERO IS A NUMBER, AND `?? 0` INVENTS IT (FS-489).
          All four tiles read `summary.data?.x ?? 0`, so a summary that had not arrived —
          loading, retrying, or failed — rendered "Open errors 0" on the page an engineer
          checks to find out whether a deploy broke anything. That is the FS-191 shape
          exactly: a complete, error-free dashboard of zeros. And because react-query retries
          by default, the window where `isError` is still false lasts seconds.
          `summaryFigure` shows an em dash instead, and the hint says which state it is. */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard label="Open errors" value={summaryFigure(summary.data?.open_count)} tone="danger" hint={summaryHint} />
        <SummaryCard label="Events (range)" value={summaryFigure(summary.data?.events_in_range)} hint={summaryHint} />
        <SummaryCard label="Regressions (range)" value={summaryFigure(summary.data?.regressions_in_range)} hint={summaryHint} />
        <SummaryCard
          label="Most frequent"
          value={summary.data?.top_error ? formatNumber(summary.data.top_error.count_in_range, 0) : '—'}
          hint={
            summary.data?.top_error
              ? `${summary.data.top_error.exception_type} · ${summary.data.top_error.route}`
              : (summaryHint ?? 'No errors in range')
          }
          to={summary.data?.top_error ? `/admin/errors/${summary.data.top_error.fingerprint}` : undefined}
        />
      </div>

      {/* Trend chart */}
      <ChartContainer
        title="Error volume"
        subtitle="Unhandled exceptions per hour"
        height={220}
        loading={summary.isLoading}
        error={summary.isError ? 'Failed to load error volume' : null}
      >
        {seriesData.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-opsgrid-text-secondary">
            No errors recorded in this range.
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

      {/* Filter toolbar */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="relative min-w-[16rem] flex-1">
          <label htmlFor="error-search" className="sr-only">Filter by route or exception type</label>
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-opsgrid-text-secondary" />
          <Input
            id="error-search"
            className="pl-9"
            placeholder="Filter by route or exception type…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
        </div>
        <div className="w-52">
          <Select aria-label="Status filter" options={STATUS_OPTIONS} value={statusFilter} onChange={(e) => updateParam('status', e.target.value)} />
        </div>
        <div className="w-44">
          <Select aria-label="Sort by" options={SORT_OPTIONS} value={sort} onChange={(e) => updateParam('sort', e.target.value)} />
        </div>
        <Button
          variant="outline"
          onClick={() => updateParam('order', order === 'desc' ? 'asc' : 'desc', false)}
          aria-label={`Sort ${order === 'desc' ? 'descending' : 'ascending'}, toggle`}
        >
          {order === 'desc' ? 'Desc ↓' : 'Asc ↑'}
        </Button>
      </div>

      {/* Errors table */}
      <Card noPadding>
        {list.isLoading && !list.data ? (
          <SkeletonTable rows={8} columns={6} />
        ) : list.isError ? (
          <div role="alert" className="flex items-center justify-between gap-4 p-6">
            <span className="flex items-center gap-2 text-status-alarm">
              <AlertTriangle size={18} />
              Failed to load errors.
            </span>
            <Button variant="secondary" onClick={() => list.refetch()}>Retry</Button>
          </div>
        ) : items.length === 0 ? (
          <div className="p-10 text-center">
            <p className="text-opsgrid-text">
              {hasFilters ? 'No errors match these filters.' : 'No production errors recorded — nice.'}
            </p>
            {hasFilters && (
              <Button variant="outline" className="mt-4" onClick={clearFilters}>Clear filters</Button>
            )}
          </div>
        ) : (
          <Table>
            <caption className="sr-only">Aggregated production errors</caption>
            <Table.Head>
              <Table.Row>
                <Table.Header scope="col">Status</Table.Header>
                <Table.Header scope="col">Exception</Table.Header>
                <Table.Header scope="col">Route</Table.Header>
                <Table.Header scope="col" className="text-right" aria-sort={sort === 'count' ? (order === 'desc' ? 'descending' : 'ascending') : undefined}>
                  Count
                </Table.Header>
                <Table.Header scope="col">Last seen</Table.Header>
                <Table.Header scope="col">First seen</Table.Header>
              </Table.Row>
            </Table.Head>
            <Table.Body>
              {items.map((item) => (
                <Table.Row key={item.fingerprint} className="cursor-pointer">
                  <Table.Cell>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge variant={STATUS_VARIANT[item.status]}>{STATUS_LABEL[item.status]}</Badge>
                      {item.regression_count > 0 && (
                        <Badge variant="warning" tooltip="Reopened after being resolved">
                          Regression ×{item.regression_count}
                        </Badge>
                      )}
                    </div>
                  </Table.Cell>
                  <Table.Cell className="font-mono text-xs">
                    <Link
                      to={`/admin/errors/${item.fingerprint}`}
                      className="text-opsgrid-primary hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-opsgrid-primary rounded"
                    >
                      {item.exception_type}
                    </Link>
                  </Table.Cell>
                  <Table.Cell className="max-w-xs truncate font-mono text-xs" title={`${item.method} ${item.route}`}>
                    <span className="text-opsgrid-text-secondary">{item.method}</span> {item.route}
                  </Table.Cell>
                  <Table.Cell className="text-right tabular-nums" title={`${item.total_count} all time`}>
                    {formatNumber(item.count_in_range, 0)}
                  </Table.Cell>
                  <Table.Cell title={formatDateTime(item.last_seen)}>{formatTimeAgo(item.last_seen)}</Table.Cell>
                  <Table.Cell title={formatDateTime(item.first_seen)}>{formatTimeAgo(item.first_seen)}</Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
        )}
      </Card>

      {/* Pagination */}
      {items.length > 0 && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-opsgrid-text-secondary">
            Showing {rangeStart}–{rangeEnd} of {formatNumber(total, 0)}
          </p>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={page === 0}
              onClick={() => updateParam('page', String(page - 1), false)}
            >
              Previous
            </Button>
            <Button
              variant="secondary"
              disabled={rangeEnd >= total}
              onClick={() => updateParam('page', String(page + 1), false)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};

export default ErrorTriage;
