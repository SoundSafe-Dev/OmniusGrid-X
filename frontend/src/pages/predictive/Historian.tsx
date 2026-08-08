import { FC, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Database, Download, Search } from 'lucide-react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { Card, Button } from '../../components';
import { assetsApi, historianApi } from '../../api';
import type {
  HistorianGranularity,
  HistorianQueryParams,
  HistorianQueryResponse,
} from '../../api/historian';

const GRANULARITIES: { value: HistorianGranularity; label: string }[] = [
  { value: 'raw', label: 'Raw' },
  { value: '1m', label: '1 minute' },
  { value: '1h', label: '1 hour' },
  { value: '1d', label: '1 day' },
];

const RANGE_HOURS: Record<string, number> = { '24h': 24, '7d': 168, '30d': 720 };

/** Client-side CSV export of the loaded historian result (no extra API call). */
const exportCsv = (result: HistorianQueryResponse) => {
  const header = 'timestamp,average,minimum,maximum,sample_count';
  const rows = result.points.map(
    (p) => `${p.timestamp},${p.average},${p.minimum},${p.maximum},${p.sampleCount}`
  );

  // THE FILE SAYS WHAT THE SCREEN SAYS (FS-479).
  //
  // The card's subtitle already reads "(more available)" when `hasMore` — the operator
  // looking at the page knows the window was capped. The CSV carried no such note: header,
  // rows, end of file. And the CSV is the artefact that leaves the building — filed,
  // mailed, opened in a spreadsheet by somebody who never saw this page, and read as the
  // history of that metric over that window.
  //
  // A leading comment line rather than a trailing one: spreadsheet software shows the
  // first rows, and a caveat below ten thousand points is a caveat nobody reads.
  const preamble = result.hasMore
    ? [
        `# PARTIAL: the first ${result.count} points of a larger result` +
          ` (limit ${result.limit}, offset ${result.offset}).`,
        `# Narrow the window or raise the limit for the rest.`,
      ]
    : [];

  const blob = new Blob([[...preamble, header, ...rows].join('\n') + '\n'], {
    type: 'text/csv;charset=utf-8',
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `historian_${result.assetId}_${result.metric}_${result.granularity}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
};

export const Historian: FC = () => {
  // `isLoading` is read as well as `isError` (FS-489). react-query retries by default, so
  // `isError` stays false for SECONDS while the retries run — and during that window
  // `assets` is empty and `assetsError` is false, which is the shape of "this plant has
  // nothing instrumented". The state the picker was missing is the one it is in most of the
  // time something is wrong.
  const { data: assetsPage, isError: assetsError, isLoading: assetsLoading } = useQuery({
    queryKey: ['historian-assets'],
    queryFn: () => assetsApi.list({ limit: 500 }),
  });
  const assets = assetsPage?.items ?? [];

  const [assetId, setAssetId] = useState('');
  const [metric, setMetric] = useState('temperature');
  const [granularity, setGranularity] = useState<HistorianGranularity>('raw');
  const [range, setRange] = useState('24h');
  const [submitted, setSubmitted] = useState<HistorianQueryParams | null>(null);

  const effectiveAssetId = assetId || assets[0]?.id || '';

  const { data, isFetching, isError } = useQuery({
    queryKey: ['historian-query', submitted],
    queryFn: () => historianApi.query(submitted!),
    enabled: !!submitted,
  });

  const runQuery = () => {
    if (!effectiveAssetId || !metric) return;
    const now = new Date();
    const start = new Date(now.getTime() - (RANGE_HOURS[range] ?? 24) * 3600_000);
    setSubmitted({
      assetId: effectiveAssetId,
      metric,
      granularity,
      start: start.toISOString(),
      end: now.toISOString(),
      limit: 5000,
    });
  };

  const chartData = useMemo(
    () =>
      (data?.points ?? []).map((p) => ({
        time: new Date(p.timestamp).toLocaleString([], {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        }),
        average: p.average,
        minimum: p.minimum,
        maximum: p.maximum,
      })),
    [data]
  );

  // Summary of the loaded points: envelope min/max plus the mean of averages.
  const summary = useMemo(() => {
    const points = data?.points ?? [];
    if (points.length === 0) return null;
    let min = Infinity;
    let max = -Infinity;
    let sum = 0;
    for (const p of points) {
      if (p.minimum < min) min = p.minimum;
      if (p.maximum > max) max = p.maximum;
      sum += p.average;
    }
    return { min, max, avg: sum / points.length, count: points.length };
  }, [data]);

  return (
    <div className="space-y-6">
      <Card title="Historian Query" subtitle="Query the tenant time-series historian">
        <div className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
          <div className="md:col-span-1">
            <label htmlFor="historian-asset" className="block text-xs text-opsgrid-text-secondary mb-1">Asset</label>
            <select
              id="historian-asset"
              value={effectiveAssetId}
              onChange={(e) => setAssetId(e.target.value)}
              className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-opsgrid-text-primary"
            >
              {assets.length === 0 && (
                /* An asset picker reading "No assets" tells an engineer this plant has
                   nothing instrumented. On a failed load it means the list could not be
                   read, which is a different thing to go and check. */
                <option value="">
                  {assetsLoading
                    ? 'Loading assets…'
                    : assetsError
                      ? 'Asset list unavailable'
                      : 'No assets'}
                </option>
              )}
              {assets.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="historian-metric" className="block text-xs text-opsgrid-text-secondary mb-1">Metric</label>
            <input
              id="historian-metric"
              value={metric}
              onChange={(e) => setMetric(e.target.value)}
              placeholder="e.g. temperature"
              className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-opsgrid-text-primary"
            />
          </div>
          <div>
            <label htmlFor="historian-granularity" className="block text-xs text-opsgrid-text-secondary mb-1">Granularity</label>
            <select
              id="historian-granularity"
              value={granularity}
              onChange={(e) => setGranularity(e.target.value as HistorianGranularity)}
              className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-opsgrid-text-primary"
            >
              {GRANULARITIES.map((g) => (
                <option key={g.value} value={g.value}>
                  {g.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="historian-range" className="block text-xs text-opsgrid-text-secondary mb-1">Range</label>
            <select
              id="historian-range"
              value={range}
              onChange={(e) => setRange(e.target.value)}
              className="w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-opsgrid-text-primary"
            >
              <option value="24h">Last 24 hours</option>
              <option value="7d">Last 7 days</option>
              <option value="30d">Last 30 days</option>
            </select>
          </div>
          <div>
            <Button
              variant="primary"
              loading={isFetching}
              disabled={!effectiveAssetId || !metric}
              onClick={runQuery}
            >
              <Search size={16} className="mr-1" />
              Query
            </Button>
          </div>
        </div>
      </Card>

      {/* ANNOUNCED, and it says which failure it is (FS-479).
          
          This card is the only error surface on a FIRST query — the more specific "this is
          a loading failure, not an empty window" lives inside the `{data && …}` block, so
          it appears only when a previous query succeeded. Someone whose first query fails
          saw an unannounced sentence and no empty-state, which is the right information
          delivered to nobody using a screen reader. */}
      {isError && (
        <Card className="p-4">
          <p className="text-status-alarm text-sm" role="alert">
            Query failed — this is a loading failure, not an empty window. Check the asset
            and metric, then try again.
          </p>
        </Card>
      )}

      {data && (
        <>
          {summary && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Card className="p-4">
                <p className="text-xs text-opsgrid-text-secondary">Min</p>
                <p className="text-xl font-bold">{summary.min.toFixed(2)}</p>
              </Card>
              <Card className="p-4">
                <p className="text-xs text-opsgrid-text-secondary">Max</p>
                <p className="text-xl font-bold">{summary.max.toFixed(2)}</p>
              </Card>
              <Card className="p-4">
                <p className="text-xs text-opsgrid-text-secondary">Average</p>
                <p className="text-xl font-bold">{summary.avg.toFixed(2)}</p>
              </Card>
              <Card className="p-4">
                <p className="text-xs text-opsgrid-text-secondary">Points Loaded</p>
                <p className="text-xl font-bold">{summary.count}</p>
              </Card>
            </div>
          )}
          <Card
            title={`${data.metric} — ${data.granularity}`}
            subtitle={`${data.count} point${data.count === 1 ? '' : 's'}${
              data.hasMore ? ' (more available)' : ''
            }`}
            action={
              <Button
                variant="secondary"
                size="sm"
                disabled={data.points.length === 0}
                onClick={() => exportCsv(data)}
              >
                <Download size={16} className="mr-1" />
                Export CSV
              </Button>
            }
          >
            {isError ? (
              <p className="text-sm text-status-alarm py-8 text-center" role="alert">
                Couldn’t load history — this is a loading failure, not an empty window.
              </p>
            ) : chartData.length === 0 ? (
              <p className="text-opsgrid-text-secondary text-center py-8">
                No data points in this window.
              </p>
            ) : (
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis dataKey="time" stroke="#9CA3AF" minTickGap={40} />
                    <YAxis stroke="#9CA3AF" />
                    <RechartsTooltip
                      contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                      itemStyle={{ color: '#F3F4F6' }}
                    />
                    <Legend />
                    <Line type="monotone" dataKey="minimum" stroke="#6B7280" dot={false} name="Min" />
                    <Line type="monotone" dataKey="average" stroke="#3B82F6" strokeWidth={2} dot={false} name="Avg" />
                    <Line type="monotone" dataKey="maximum" stroke="#F59E0B" dot={false} name="Max" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>

          {data.points.length > 0 && (
            <Card title="Data Points" subtitle="Raw historian rows">
              <div className="overflow-x-auto max-h-96">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-opsgrid-text-secondary border-b border-opsgrid-border">
                      <th className="py-2 pr-4 font-medium">Timestamp</th>
                      <th className="py-2 pr-4 font-medium">Average</th>
                      <th className="py-2 pr-4 font-medium">Min</th>
                      <th className="py-2 pr-4 font-medium">Max</th>
                      <th className="py-2 pr-4 font-medium">Samples</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-opsgrid-border">
                    {data.points.slice(0, 500).map((p, i) => (
                      <tr key={`${p.timestamp}-${i}`}>
                        <td className="py-1.5 pr-4">{new Date(p.timestamp).toLocaleString()}</td>
                        <td className="py-1.5 pr-4">{p.average}</td>
                        <td className="py-1.5 pr-4">{p.minimum}</td>
                        <td className="py-1.5 pr-4">{p.maximum}</td>
                        <td className="py-1.5 pr-4">{p.sampleCount}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}

      {!data && !isError && (
        <Card className="p-8">
          <div className="flex flex-col items-center text-opsgrid-text-secondary">
            <Database className="w-10 h-10 mb-3" />
            <p>Select an asset and metric, then run a query to view historian data.</p>
          </div>
        </Card>
      )}
    </div>
  );
};
