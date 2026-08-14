import React, { useState, useEffect } from 'react';
import { Card } from '../../components/ui/Card';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { Badge } from '../../components/ui/Badge';
import { Modal, Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';
import {
  EvidenceCitation,
  EvidenceJoinPlan,
  EvidenceCatalogResponse,
  EvidenceCatalogTable,
  EvidenceJobStatus,
  EvidenceLineage,
  EvidencePreviewRequest,
  EvidencePreviewResult,
  EvidenceRow,
  EvidenceSourceRow,
  EvidenceTableReference,
  OperationsQuestionResponse,
  nlpCorrelationApi,
  IntakeItem,
} from '../../api/nlpCorrelation';
import { Upload, FileText, Image, FileSpreadsheet, Loader2, CheckCircle, Search } from 'lucide-react';

type EvidenceDrawerTab = 'matched' | 'unmatched_left' | 'unmatched_right' | 'join_details' | 'quality' | 'citation';

interface EvidenceDrawerState {
  isOpen: boolean;
  edgeIndex: number;
  tab: EvidenceDrawerTab;
  evidenceId?: string;
  citation?: EvidenceCitation;
  citationRow?: EvidenceRow;
}

const EVIDENCE_DRAWER_PAGE_SIZE = 25;
const EVIDENCE_JOB_POLL_INTERVAL_MS = 750;
const EVIDENCE_JOB_MAX_WAIT_MS = 10 * 60 * 1000;

const planIdentifier = (plan: EvidenceJoinPlan, index = 0) => plan.plan_id || `candidate-plan-${index}`;

const asNumber = (value: unknown): number | undefined => (
  typeof value === 'number' && Number.isFinite(value) ? value : undefined
);

const formatCount = (value: unknown): string => {
  const numeric = asNumber(value);
  return numeric === undefined ? '—' : new Intl.NumberFormat().format(numeric);
};

const formatPercent = (value: unknown): string => {
  const numeric = asNumber(value);
  return numeric === undefined ? '—' : `${(numeric * 100).toFixed(1)}%`;
};

/**
 * The bounding flags the evidence engine and the operational analytics attach to their own
 * output. Each says the same kind of thing — what you are reading is a part, not the whole —
 * and each is set independently, so they are collected rather than collapsed into one badge.
 *
 * Sending a caveat nobody renders is worse than not sending it: the server author believes
 * the reader has been told. These four are set on every bounded preview and, until this was
 * written, none of them reached a screen.
 */
export const boundedAnalysisNotes = (result?: EvidencePreviewResult | null): string[] => {
  if (!result) return [];
  const notes: string[] = [];
  const rollups = result.entity_rollups;
  if (rollups?.rollups?.some((rollup) => rollup.groups_truncated)) {
    notes.push(
      'Some rollups list only their first groups. The group count is the real total, so the largest contributor may not be in the list.',
    );
  }
  if (rollups?.tables?.some((table) => table.rollups_truncated)) {
    notes.push(
      'Some tables produced more metric breakdowns than the limit allowed, so a metric you expect to see may be missing rather than absent from the data.',
    );
  }
  const analytics = result.operational_analytics;
  if (analytics?.bounded?.input_truncated) {
    notes.push('The statistics ran over a bounded slice of the rows, not every row in the selection.');
  }
  const signals = Object.values(analytics?.field_signals ?? {});
  const sampledSignal = signals.some(
    (signal) => signal?.anomalies?.sampled || signal?.change_point?.sampled,
  );
  const sampledRelationship = (analytics?.relationships ?? []).some((rel) => rel?.sampled);
  if (sampledSignal || sampledRelationship) {
    notes.push(
      'Some series were sampled before analysis, so anomaly and correlation figures describe the sample rather than every observation.',
    );
  }
  return notes;
};

const humanizeTechnicalLabel = (value: unknown, fallback = 'Unknown'): string => {
  const text = String(value ?? '').trim();
  if (!text) return fallback;
  const normalized = text
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_.\/]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const titled = normalized.charAt(0).toUpperCase() + normalized.slice(1);
  return titled.replace(/\bId\b/g, 'ID');
};

const humanizeSourceName = (value: unknown, fallback = 'Unknown source'): string => {
  const text = String(value ?? '')
    .trim()
    .replace(/\.(zip|xlsx|xlsm|xlsb|xls|csv|tsv|jsonl?|parquet|pdf|docx)$/i, '')
    // Uploaded ZIP names often end in a generated timestamp. It does not help
    // an operator choose a source, so keep it out of the primary label.
    .replace(/[-_]\d{8}T\d{6}Z(?:[-_]\d+)+$/i, '');
  return humanizeTechnicalLabel(text, fallback);
};

const catalogTableLabel = (table: EvidenceCatalogTable): string => {
  const reference = String(table.selection_ref || table.table_name || 'table');
  const filename = reference.split('/').pop() || reference;
  const basename = filename.replace(/\.[^.]+$/, '');
  // Typical ZIP members are named "company_name_FY2024__Production_Operations".
  // Show the meaningful year and business table name rather than the archive path.
  const fiscalYear = basename.match(/(?:^|_)(FY\d{4})__(.+)$/i)
    || basename.match(/(?:^|_)(FY\d{4})_(.+)$/i);
  if (fiscalYear) {
    return `${fiscalYear[1].toUpperCase()} · ${humanizeTechnicalLabel(fiscalYear[2])}`;
  }
  return humanizeTechnicalLabel(basename, 'Table');
};

const apiErrorMessage = (error: any, fallback: string): string => {
  const payload = error?.response?.data;
  const nestedDetail = payload?.error?.details?.detail;
  const candidates = [
    nestedDetail?.message,
    payload?.error?.details?.message,
    payload?.detail?.message,
    typeof payload?.detail === 'string' && payload.detail !== 'request failed' ? payload.detail : undefined,
    error?.message,
  ];
  return candidates.find((message) => typeof message === 'string' && message.trim()) || fallback;
};

const tableReferenceLabel = (reference: EvidenceTableReference): string => {
  const source = humanizeSourceName(reference.source_name || reference.source_id, 'Source');
  const table = humanizeTechnicalLabel(reference.table_name || reference.table_key, 'Table');
  return `${source} · ${table}`;
};

const technicalTableReference = (reference: EvidenceTableReference): string => {
  const source = String(reference.source_name || reference.source_id || 'source');
  const table = String(reference.table_name || reference.table_key || 'table');
  return `${source} → ${table}`;
};

const planTablePairIdentifier = (plan: EvidenceJoinPlan): string => (
  [plan.left, plan.right]
    .map((reference) => `${reference.source_key || reference.source_id || ''}/${reference.table_key || reference.table_name || ''}`)
    .sort()
    .join('::')
);

const describeJoinKeys = (plan: EvidenceJoinPlan): string => (
  plan.keys
    .map((key) => humanizeTechnicalLabel(key.canonical_name || key.name, 'Match key'))
    .join(' + ')
);

const recommendedPlansForResult = (result: EvidencePreviewResult): EvidenceJoinPlan[] => {
  if (result.evidence_sets?.length) {
    return result.evidence_sets
      .map((edge) => edge.join_plan)
      .filter((plan): plan is EvidenceJoinPlan => Boolean(plan?.safety?.safe_for_auto_preview));
  }
  if (result.join_plan?.safety?.safe_for_auto_preview) return [result.join_plan];
  const candidate = (result.candidate_join_plans || []).find((plan) => plan.safety?.safe_for_auto_preview);
  return candidate ? [candidate] : [];
};

const evidenceRowsForEdge = (edge: EvidencePreviewResult): EvidenceRow[] => {
  const explicitRows = [
    ...(edge.matched_rows || []),
    ...(edge.unmatched_left_rows || []),
    ...(edge.unmatched_right_rows || []),
  ];
  return explicitRows.length > 0 ? explicitRows : (edge.evidence_rows || []);
};

const evidenceRowsForTab = (edge: EvidencePreviewResult, tab: EvidenceDrawerTab): EvidenceRow[] => {
  if (tab === 'matched') return edge.matched_rows || evidenceRowsForEdge(edge).filter((row) => row.match_status === 'matched');
  if (tab === 'unmatched_left') return edge.unmatched_left_rows || evidenceRowsForEdge(edge).filter((row) => row.match_status === 'unmatched_left');
  if (tab === 'unmatched_right') return edge.unmatched_right_rows || evidenceRowsForEdge(edge).filter((row) => row.match_status === 'unmatched_right');
  return [];
};

const exactEvidenceRowTotal = (edge: EvidencePreviewResult, tab: EvidenceDrawerTab): number | undefined => {
  const metrics = edge.join_plan?.metrics;
  const quality = edge.quality;
  if (tab === 'matched') return metrics?.matched_pair_count;
  if (tab === 'unmatched_left') {
    const total = asNumber(quality?.left_table_row_count);
    const matched = metrics?.matched_left_record_count;
    return total !== undefined && matched !== undefined ? Math.max(0, total - matched) : undefined;
  }
  if (tab === 'unmatched_right') {
    const total = asNumber(quality?.right_table_row_count);
    const matched = metrics?.matched_right_record_count;
    return total !== undefined && matched !== undefined ? Math.max(0, total - matched) : undefined;
  }
  return undefined;
};

const formatEvidenceValue = (value: unknown): string => {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
};

const lineageLabel = (lineage?: EvidenceLineage): string => {
  if (!lineage) return 'Source lineage unavailable';
  const source = humanizeSourceName(lineage.source_name || lineage.source_id, 'Source');
  const table = humanizeTechnicalLabel(lineage.table_name || lineage.table_key, 'Table');
  const row = lineage.row_number ? `row ${lineage.row_number}` : lineage.row_id ? `record ${lineage.row_id}` : 'row unknown';
  return `${source} · ${table} · ${row}`;
};

const EvidenceRowCard: React.FC<{ row: EvidenceRow; highlighted?: boolean }> = ({ row, highlighted = false }) => {
  const sourceRows: EvidenceSourceRow[] = row.source_rows?.length
    ? row.source_rows
    : (row.lineage || []).map((lineage) => ({ lineage }));
  const joinEntries = Object.entries(row.join_key || {});

  return (
    <article className={`rounded-lg border p-3 ${highlighted ? 'border-opsgrid-primary bg-status-maintenance/10' : 'border-opsgrid-border'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={row.match_status === 'matched' ? 'success' : 'warning'}>
            {humanizeTechnicalLabel(row.match_status, 'Evidence row')}
          </Badge>
          {row.evidence_id && <span className="font-mono text-xs text-opsgrid-text-secondary">{row.evidence_id}</span>}
        </div>
        {joinEntries.length > 0 && (
          <span className="text-xs text-opsgrid-text-secondary">
            Match on {joinEntries.map(([key, value]) => `${humanizeTechnicalLabel(key)}: ${value}`).join(' · ')}
          </span>
        )}
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-2">
        {sourceRows.map((sourceRow, index) => {
          const values = Object.entries(sourceRow.values || {});
          return (
            <section key={`${sourceRow.side || 'source'}-${sourceRow.lineage?.row_id || index}`} className="rounded border border-opsgrid-border bg-opsgrid-bg p-2">
              <p className="text-xs font-medium text-opsgrid-text">
                {sourceRow.side ? `${humanizeTechnicalLabel(sourceRow.side)} record` : 'Source record'}
              </p>
              <p className="mt-1 text-xs text-opsgrid-text-secondary">{lineageLabel(sourceRow.lineage)}</p>
              {values.length > 0 ? (
                <dl className="mt-2 grid grid-cols-1 gap-x-3 gap-y-1 text-xs sm:grid-cols-2">
                  {values.slice(0, 16).map(([field, value]) => (
                    <div key={field} className="min-w-0">
                      <dt className="truncate text-opsgrid-text-secondary" title={field}>{humanizeTechnicalLabel(field)}</dt>
                      <dd className="break-words text-opsgrid-text">{formatEvidenceValue(value)}</dd>
                    </div>
                  ))}
                </dl>
              ) : row.fields ? (
                <dl className="mt-2 grid grid-cols-1 gap-x-3 gap-y-1 text-xs sm:grid-cols-2">
                  {Object.entries(row.fields).slice(0, 16).map(([field, value]) => (
                    <div key={field} className="min-w-0">
                      <dt className="truncate text-opsgrid-text-secondary" title={field}>{humanizeTechnicalLabel(field)}</dt>
                      <dd className="break-words text-opsgrid-text">{formatEvidenceValue(value)}</dd>
                    </div>
                  ))}
                </dl>
              ) : null}
              {values.length > 16 && <p className="mt-2 text-xs text-opsgrid-text-secondary">Showing 16 of {values.length} fields.</p>}
            </section>
          );
        })}
      </div>
    </article>
  );
};

interface EvidenceDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  edge?: EvidencePreviewResult;
  edgeLabel?: string;
  initialTab: EvidenceDrawerTab;
  focusEvidenceId?: string;
  citation?: EvidenceCitation;
  citationRow?: EvidenceRow;
}

const EvidenceDrawer: React.FC<EvidenceDrawerProps> = ({
  isOpen,
  onClose,
  edge,
  edgeLabel,
  initialTab,
  focusEvidenceId,
  citation,
  citationRow,
}) => {
  const [activeTab, setActiveTab] = useState<EvidenceDrawerTab>(initialTab);
  const [visibleRowCount, setVisibleRowCount] = useState(EVIDENCE_DRAWER_PAGE_SIZE);

  useEffect(() => {
    if (isOpen) {
      setActiveTab(initialTab);
      setVisibleRowCount(EVIDENCE_DRAWER_PAGE_SIZE);
    }
  }, [isOpen, initialTab, focusEvidenceId, edge?.join_plan?.plan_id]);

  const plan = edge?.join_plan;
  const tabs: Array<{ id: EvidenceDrawerTab; label: string; count?: number }> = edge
    ? [
      { id: 'matched', label: 'Matched', count: exactEvidenceRowTotal(edge, 'matched') },
      { id: 'unmatched_left', label: 'Only in left', count: exactEvidenceRowTotal(edge, 'unmatched_left') },
      { id: 'unmatched_right', label: 'Only in right', count: exactEvidenceRowTotal(edge, 'unmatched_right') },
      { id: 'join_details', label: 'Join details' },
      { id: 'quality', label: 'Data quality' },
    ]
    : [{ id: 'citation', label: 'Citation' }];
  const rows = edge ? evidenceRowsForTab(edge, activeTab) : (citationRow ? [citationRow] : []);
  const exactTotal = edge ? exactEvidenceRowTotal(edge, activeTab) : rows.length;
  const visibleRows = rows.slice(0, visibleRowCount);
  const qualityWarnings = edge?.quality?.warnings || [];

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={edgeLabel || (citation ? 'Cited evidence' : 'Evidence details')}
      description="Review the original source rows and lineage behind this result. A row match is evidence of co-occurrence, not proof of causation."
      className="max-w-5xl"
      footer={<Button variant="outline" onClick={onClose}>Close</Button>}
    >
      {edge && (
        <div className="mb-4 flex flex-wrap gap-2">
          <Badge variant={plan?.approval_state === 'confirmed' ? 'success' : 'warning'}>
            {plan?.approval_state === 'confirmed' ? 'Confirmed join' : 'Proposed join'}
          </Badge>
          {plan && <Badge variant="neutral">{describeJoinKeys(plan)}</Badge>}
          {edge.response_truncated || edge.truncated ? <Badge variant="warning">Returned rows are bounded</Badge> : null}
        </div>
      )}

      <div className="mb-4 flex flex-wrap gap-2 border-b border-opsgrid-border pb-3">
        {tabs.map((tab) => (
          <Button
            key={tab.id}
            size="sm"
            variant={activeTab === tab.id ? 'primary' : 'outline'}
            onClick={() => {
              setActiveTab(tab.id);
              setVisibleRowCount(EVIDENCE_DRAWER_PAGE_SIZE);
            }}
          >
            {tab.label}{tab.count !== undefined ? ` (${formatCount(tab.count)})` : ''}
          </Button>
        ))}
      </div>

      {activeTab === 'join_details' && plan && (
        <div className="space-y-3">
          <div className="grid gap-3 md:grid-cols-2">
            {(['left', 'right'] as const).map((side) => (
              <div key={side} className="rounded border border-opsgrid-border p-3">
                <p className="text-xs font-medium uppercase tracking-wide text-opsgrid-text-secondary">{side} table</p>
                <p className="mt-1 text-sm font-medium text-opsgrid-text">{tableReferenceLabel(plan[side])}</p>
                <p className="mt-1 text-xs text-opsgrid-text-secondary">{technicalTableReference(plan[side])}</p>
              </div>
            ))}
          </div>
          <div className="rounded border border-opsgrid-border p-3">
            <p className="text-sm font-medium text-opsgrid-text">Exact match rules</p>
            <div className="mt-2 space-y-2">
              {plan.keys.map((key, index) => (
                <div key={`${key.canonical_name || key.name || 'key'}-${index}`} className="rounded bg-opsgrid-bg p-2 text-sm">
                  <p className="font-medium text-opsgrid-text">{humanizeTechnicalLabel(key.canonical_name || key.name, 'Match key')}</p>
                  <p className="text-xs text-opsgrid-text-secondary">
                    {humanizeTechnicalLabel(key.left_column, 'Left column')} ↔ {humanizeTechnicalLabel(key.right_column, 'Right column')}
                    {key.strategy === 'time_bucket' && ` · ${key.time_bucket_minutes || 60}-minute time bucket`}
                    {key.strategy === 'exact' && ' · exact match'}
                  </p>
                </div>
              ))}
            </div>
          </div>
          {plan.explanation && <p className="text-sm text-opsgrid-text-secondary">{plan.explanation}</p>}
          {!!plan.safety?.warnings?.length && (
            <div className="rounded border border-status-warning/50 bg-status-warning/10 p-3 text-sm text-opsgrid-text">
              <p className="font-medium">Review notes</p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-xs">
                {plan.safety.warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      {activeTab === 'quality' && edge && (
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded border border-opsgrid-border p-3"><p className="text-xs text-opsgrid-text-secondary">Evidence quality</p><p className="mt-1 text-lg font-semibold text-opsgrid-text">{edge.quality?.evidence_quality_label || 'Review required'}</p></div>
            <div className="rounded border border-opsgrid-border p-3"><p className="text-xs text-opsgrid-text-secondary">Match coverage</p><p className="mt-1 text-lg font-semibold text-opsgrid-text">{formatPercent(plan?.metrics?.left_match_coverage)} / {formatPercent(plan?.metrics?.right_match_coverage)}</p></div>
            <div className="rounded border border-opsgrid-border p-3"><p className="text-xs text-opsgrid-text-secondary">Key completeness</p><p className="mt-1 text-lg font-semibold text-opsgrid-text">{formatPercent(plan?.metrics?.left_key_completeness)} / {formatPercent(plan?.metrics?.right_key_completeness)}</p></div>
            <div className="rounded border border-opsgrid-border p-3"><p className="text-xs text-opsgrid-text-secondary">Many-to-many keys</p><p className="mt-1 text-lg font-semibold text-opsgrid-text">{formatCount(plan?.metrics?.many_to_many_key_count)}</p></div>
          </div>
          {edge.quality?.interpretation && <p className="rounded bg-opsgrid-bg p-3 text-sm text-opsgrid-text-secondary">{edge.quality.interpretation}</p>}
          {qualityWarnings.length > 0 && (
            <div className="rounded border border-status-warning/50 bg-status-warning/10 p-3 text-sm text-opsgrid-text">
              <p className="font-medium">Warnings to review</p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-xs">
                {qualityWarnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            </div>
          )}
          {edge.response_truncated || edge.truncated ? (
            <p className="rounded border border-status-warning/50 bg-status-warning/10 p-3 text-xs text-opsgrid-text">
              This preview is bounded. Use the exact plan metrics above for counts; the displayed row list is not a complete export.
            </p>
          ) : null}
        </div>
      )}

      {activeTab === 'citation' && citation && (
        <div className="space-y-3">
          <div className="rounded border border-opsgrid-border p-3 text-sm">
            <p className="font-medium text-opsgrid-text">Cited source lineage</p>
            {(citation.lineage || []).length > 0 ? (
              <ul className="mt-2 space-y-1 text-sm text-opsgrid-text-secondary">
                {(citation.lineage || []).map((lineage, index) => <li key={`${lineage.row_id || lineage.row_number || index}`}>{lineageLabel(lineage)}</li>)}
              </ul>
            ) : <p className="mt-1 text-opsgrid-text-secondary">This citation did not include row lineage.</p>}
            {citation.evidence_id && <p className="mt-2 font-mono text-xs text-opsgrid-text-secondary">{citation.evidence_id}</p>}
          </div>
          {citationRow ? <EvidenceRowCard row={citationRow} highlighted /> : (
            <p className="rounded border border-status-warning/50 bg-status-warning/10 p-3 text-sm text-opsgrid-text">
              This source-specific citation is not part of the pairwise preview. Its source location is shown above; raw values are available only when the answer provides a bounded citation record.
            </p>
          )}
        </div>
      )}

      {(['matched', 'unmatched_left', 'unmatched_right'] as EvidenceDrawerTab[]).includes(activeTab) && edge && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-opsgrid-text-secondary">
            <span>
              Showing {formatCount(visibleRows.length)} of {formatCount(rows.length)} returned row{rows.length === 1 ? '' : 's'}
              {exactTotal !== undefined && exactTotal !== rows.length ? ` · ${formatCount(exactTotal)} total by the reviewed plan` : ''}
            </span>
            {edge.response_truncated || edge.truncated ? <span>Returned rows are bounded; do not infer totals from this list.</span> : null}
          </div>
          {visibleRows.length > 0 ? visibleRows.map((row, index) => (
            <EvidenceRowCard key={row.evidence_id || `${row.match_status}-${index}`} row={row} highlighted={row.evidence_id === focusEvidenceId} />
          )) : (
            <p className="rounded border border-opsgrid-border p-4 text-sm text-opsgrid-text-secondary">No returned rows in this category.</p>
          )}
          {visibleRows.length < rows.length && (
            <Button size="sm" variant="outline" onClick={() => setVisibleRowCount((count) => count + EVIDENCE_DRAWER_PAGE_SIZE)}>
              Show {Math.min(EVIDENCE_DRAWER_PAGE_SIZE, rows.length - visibleRows.length)} more returned rows
            </Button>
          )}
        </div>
      )}
    </Modal>
  );
};

export const IntakeInbox: React.FC = () => {
  const [items, setItems] = useState<IntakeItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  // A failed load rendered "No items in the inbox" above "Upload data to get started" — an
  // invitation to re-upload work that may already be there.
  const [loadError, setLoadError] = useState<string | null>(null);
  // A failed UPLOAD or ANALYSE reached only the console (FS-478). The user pressed a
  // button on purpose, so the absence of any response is indistinguishable from the
  // moment before the list refreshes — and for analyse it is worse, because the spinner
  // stops and the row simply stays as it was, which is what "nothing to analyse" looks
  // like. Same class the useMutation sweep covers; this page does not use useMutation, so
  // the sweep could not see it.
  const [actionError, setActionError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState<string | null>(null);
  const [loadingResults, setLoadingResults] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [dataType, setDataType] = useState<'spreadsheet' | 'report' | 'image' | 'document'>('document');
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadDropActive, setUploadDropActive] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [evidenceSelection, setEvidenceSelection] = useState<string[]>([]);
  const [evidenceResult, setEvidenceResult] = useState<EvidencePreviewResult | null>(null);
  // Keep the exact evidence scope and reviewed plan available for the
  // operations-question experience. It is cleared whenever the source
  // selection changes, so a question cannot silently use stale evidence.
  const [evidenceRequest, setEvidenceRequest] = useState<EvidencePreviewRequest | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [correlatingEvidence, setCorrelatingEvidence] = useState(false);
  const [evidenceJob, setEvidenceJob] = useState<EvidenceJobStatus | null>(null);
  const [tableCatalog, setTableCatalog] = useState<EvidenceCatalogResponse | null>(null);
  const [tableSelection, setTableSelection] = useState<Record<string, string[]>>({});
  const [loadingTableCatalog, setLoadingTableCatalog] = useState(false);
  const [tableCatalogError, setTableCatalogError] = useState<string | null>(null);
  const [tableCatalogFilter, setTableCatalogFilter] = useState('');
  const [operationsQuestion, setOperationsQuestion] = useState('');
  const [operationsAnswer, setOperationsAnswer] = useState<OperationsQuestionResponse | null>(null);
  const [operationsError, setOperationsError] = useState<string | null>(null);
  const [answeringOperations, setAnsweringOperations] = useState(false);
  // Plans are selected deliberately after a read-only preview. Rejection is
  // scoped to the current review only; changing the input/table scope resets
  // it so stale approval choices cannot leak into a new analysis.
  const [pendingPlanIds, setPendingPlanIds] = useState<string[]>([]);
  const [rejectedPlanIds, setRejectedPlanIds] = useState<string[]>([]);
  const [evidenceDrawer, setEvidenceDrawer] = useState<EvidenceDrawerState>({
    isOpen: false,
    edgeIndex: 0,
    tab: 'matched',
  });

  useEffect(() => {
    // P3 (page-enhancement review): this effect ran once with `[]` while the status
    // select wrote state the request had already captured — the dropdown APPEARED to
    // filter and did nothing. `loadIntakeItems` reads `statusFilter` from the closure,
    // so the filter is the dependency that makes the request follow the control.
    loadIntakeItems();
  // eslint-disable-next-line react-hooks/exhaustive-deps -- loadIntakeItems is stable per render; statusFilter is the real input
  }, [statusFilter]);

  const loadIntakeItems = async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const response = await nlpCorrelationApi.listIntakeItems(50, 0, statusFilter === 'all' ? undefined : statusFilter);
      setItems(response.items);
    } catch (error) {
      console.error('Error loading intake items:', error);
      setLoadError('Could not load the inbox.');
    } finally {
      setIsLoading(false);
    }
  };

  const selectUploadFile = (file: File) => {
    setSelectedFile(file);
    setUploadError(null);
    // A title is required by the Intake API. Supplying a sensible default
    // avoids a ZIP looking "stuck" after it has been selected or dropped.
    setTitle((current) => (
      current.trim() ? current : file.name.replace(/\.[^.]+$/, '')
    ));
    // Auto-detect data type from file extension. ZIPs are structured batch
    // uploads, not generic documents, so they enter the evidence adapters.
    const ext = file.name.split('.').pop()?.toLowerCase();
    if (['csv', 'tsv', 'tab', 'xlsx', 'xls', 'xlsm', 'xlsb', 'ods', 'numbers', 'parquet', 'pq', 'arrow', 'feather', 'json', 'jsonl', 'ndjson', 'xml', 'zip'].includes(ext || '')) {
      setDataType('spreadsheet');
    } else if (['pdf', 'docx', 'doc', 'rtf', 'odt', 'html', 'htm', 'eml'].includes(ext || '')) {
      setDataType('report');
    } else if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tiff', 'tif'].includes(ext || '')) {
      setDataType('image');
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) selectUploadFile(file);
    // Permit selecting the same ZIP again after an upload error.
    e.target.value = '';
  };

  const handleUploadDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setUploadDropActive(false);
    const file = event.dataTransfer.files?.[0];
    if (file) selectUploadFile(file);
  };

  const handleUpload = async () => {
    if (!selectedFile || !title) return;

    setUploading(true);
    setActionError(null);
    setUploadError(null);
    try {
      const response = await nlpCorrelationApi.uploadToIntake(
        selectedFile,
        title,
        description,
        dataType
      );
      setItems([response, ...items]);
      setSelectedFile(null);
      setTitle('');
      setDescription('');
    } catch (error: any) {
      console.error('Error uploading file:', error);
      const detail = error?.response?.data?.detail;
      const message =
        typeof detail === 'string'
          ? detail
          : detail?.message || 'Could not upload this file. Check the file size and ZIP safety requirements, then try again.';
      setUploadError(message);
      setActionError(`Could not upload ${selectedFile.name}. The file was not added to the inbox.`);
    } finally {
      setUploading(false);
    }
  };

  const handleAnalyze = async (itemId: string) => {
    setAnalyzing(itemId);
    setActionError(null);
    try {
      const response = await nlpCorrelationApi.analyzeIntake(itemId);
      // Update the item with analysis results
      setItems(items.map(item =>
        item.id === itemId
          ? { ...item, analysis_result: response, analyzed_at: new Date().toISOString(), status: 'analyzed' }
          : item
      ));
    } catch (error) {
      console.error('Error analyzing item:', error);
      // Names the item: the inbox shows many rows and a bare "analysis failed" leaves the
      // operator guessing which button they pressed.
      const failed = items.find((item) => item.id === itemId);
      setActionError(
        `Could not analyse ${failed?.title ?? 'that item'}. It has not been analysed.`,
      );
    } finally {
      setAnalyzing(null);
    }
  };

  const toggleEvidenceSelection = (itemId: string) => {
    setEvidenceSelection(current => (
      current.includes(itemId)
        ? current.filter(id => id !== itemId)
        : [...current, itemId]
    ));
    setEvidenceResult(null);
    setEvidenceRequest(null);
    setEvidenceError(null);
    setTableCatalog(null);
    setTableSelection({});
    setTableCatalogError(null);
    setTableCatalogFilter('');
    setOperationsAnswer(null);
    setOperationsError(null);
    setPendingPlanIds([]);
    setRejectedPlanIds([]);
    setEvidenceDrawer({ isOpen: false, edgeIndex: 0, tab: 'matched' });
  };

  const loadTableCatalog = async () => {
    if (evidenceSelection.length < 1) return;
    setLoadingTableCatalog(true);
    setTableCatalogError(null);
    try {
      const response = await nlpCorrelationApi.catalogEvidenceTables(evidenceSelection);
      setTableCatalog(response);
    } catch (error: any) {
      // CLEAR THE PREVIOUS CATALOG. Setting only the error left the last successful
      // catalog on screen beside a failure message, so a re-inspection that failed
      // rendered the table list for the PREVIOUS selection — including "No tables match
      // this filter" computed against sources the operator had already changed. A stale
      // answer under a fresh error reads as an answer.
      setTableCatalog(null);
      setTableCatalogError(apiErrorMessage(error, 'Could not inspect the available workbook/archive tables.'));
    } finally {
      setLoadingTableCatalog(false);
    }
  };

  const toggleTableSelection = (sourceId: string, selectionRef: string) => {
    const maxPerSource = tableCatalog?.selection_contract?.max_tables_per_source || 50;
    setTableCatalogError(null);
    setTableSelection(current => {
      const selected = current[sourceId] || [];
      if (selected.includes(selectionRef)) {
        const next = selected.filter(ref => ref !== selectionRef);
        if (next.length === 0) {
          const { [sourceId]: _removed, ...remaining } = current;
          return remaining;
        }
        return { ...current, [sourceId]: next };
      }
      if (selected.length >= maxPerSource) {
        setTableCatalogError(`Select at most ${maxPerSource} tables or archive members from each source.`);
        return current;
      }
      return { ...current, [sourceId]: [...selected, selectionRef] };
    });
    setEvidenceResult(null);
    setEvidenceRequest(null);
    setOperationsAnswer(null);
    setOperationsError(null);
    setPendingPlanIds([]);
    setRejectedPlanIds([]);
    setEvidenceDrawer({ isOpen: false, edgeIndex: 0, tab: 'matched' });
  };

  const useRecommendedOperationalTables = () => {
    if (!tableCatalog) return;
    const operational = /fy(?:20)?24|production|operation|quality|maintenance|downtime|logistics|equipment|asset|shift/i;
    // Keep the whole evidence graph small enough to inspect. Six tables make
    // fifteen pairwise relationships, which stays below the graph-edge limit.
    const coreDomainPatterns = [
      /production_operations|apparel_production/i,
      /quality_control/i,
      /maintenance_assets/i,
      /safety_compliance/i,
      /logistics_supply_chain/i,
      /workforce_hr/i,
    ];
    const chooseCoreDomains = (candidates: EvidenceCatalogTable[]) => (
      coreDomainPatterns
        .map(pattern => candidates.find(table => pattern.test(table.selection_ref) || pattern.test(table.table_name)))
        .filter((table): table is EvidenceCatalogTable => Boolean(table))
        .map(table => table.selection_ref)
    );
    const tableBudget = Math.min(
      6,
      tableCatalog.selection_contract?.max_tables_per_evidence_graph || 50,
    );
    const candidatesBySource = tableCatalog.sources.map((source) => {
      const tables = source.tables || [];
      const archiveMembers = tables.filter(table => table.selection_kind === 'archive_member');
      const currentYearMembers = archiveMembers.filter(table => /fy(?:20)?24/i.test(table.selection_ref));
      const currentYearWorkbook = archiveMembers.find(table => (
        /fy(?:20)?24/i.test(table.selection_ref) && /\.(xlsx|xlsm|xlsb|ods)$/i.test(table.selection_ref)
      ));
      const preferredArchive = archiveMembers.find(table => /\.(xlsx|xlsm|xlsb|ods)$/i.test(table.selection_ref));
      const preferredTables = tables
        .filter(table => operational.test(table.table_name) || operational.test(table.selection_ref))
        .map(table => table.selection_ref);

      const prioritized = [
        ...chooseCoreDomains(currentYearMembers),
        currentYearWorkbook?.selection_ref,
        ...chooseCoreDomains(archiveMembers),
        preferredArchive?.selection_ref,
        ...chooseCoreDomains(tables),
        ...preferredTables,
      ].filter((ref): ref is string => Boolean(ref));

      return {
        sourceId: source.source_id,
        refs: Array.from(new Set(prioritized)),
      };
    });

    const nextSelection: Record<string, string[]> = {};
    const sourceQuota = Math.max(1, Math.floor(tableBudget / Math.max(1, candidatesBySource.length)));
    let remaining = tableBudget;

    // First give each selected upload a fair share, then use any spare budget
    // for richer tables from the same source. This avoids two ZIP batches
    // silently expanding into twelve or more pairwise inputs.
    for (const source of candidatesBySource) {
      const refs = source.refs.slice(0, Math.min(sourceQuota, remaining));
      if (refs.length > 0) {
        nextSelection[source.sourceId] = refs;
        remaining -= refs.length;
      }
    }
    for (const source of candidatesBySource) {
      if (remaining <= 0) break;
      const selected = nextSelection[source.sourceId] || [];
      const extras = source.refs.filter(ref => !selected.includes(ref)).slice(0, remaining);
      if (extras.length > 0) {
        nextSelection[source.sourceId] = [...selected, ...extras];
        remaining -= extras.length;
      }
    }
    if (Object.keys(nextSelection).length === 0) {
      setTableCatalogError('No operational table name was recognized. Choose the relevant source tables manually.');
      return;
    }
    setTableCatalogError(null);
    setTableSelection(nextSelection);
    setEvidenceResult(null);
    setEvidenceRequest(null);
    setOperationsAnswer(null);
    setOperationsError(null);
    setPendingPlanIds([]);
    setRejectedPlanIds([]);
    setEvidenceDrawer({ isOpen: false, edgeIndex: 0, tab: 'matched' });
  };

  const buildEvidenceRequest = (
    plansToConfirm: EvidenceJoinPlan[] = [],
    previewForShape: EvidencePreviewResult | null = evidenceResult,
    confirmNoPlans = false,
  ): EvidencePreviewRequest => {
    const confirmingPlans = plansToConfirm.length > 0 || confirmNoPlans;
    const selectedCount = Object.values(tableSelection).reduce((total, refs) => total + refs.length, 0);
    // A multi-table preview is a graph, so the selected plans must be
    // confirmed together. A two-table preview keeps its direct common-table
    // envelope when the user confirms exactly one plan.
    const confirmAsGraph = confirmingPlans && (
      confirmNoPlans || Boolean(previewForShape?.evidence_sets) || plansToConfirm.length > 1
    );
    return {
      intake_ids: evidenceSelection,
      // Finding possible links is intentionally lighter than a confirmed
      // operational analysis. The latter runs only after the reviewer (or the
      // explicit skip action) has chosen a join plan.
      include_operational_analytics: confirmingPlans,
      ...(Object.keys(tableSelection).length > 0 ? { table_selection: tableSelection } : {}),
      // A six-domain recommended set has fifteen pairs. Give it enough
      // bounded processing headroom to retain each normal operational table
      // rather than allocating only a few hundred row pairs per edge.
      ...(selectedCount >= 4 ? { max_match_pairs: 25_000 } : {}),
      ...(confirmingPlans
        ? (confirmAsGraph
          ? { join_plans: plansToConfirm, confirm_join_plan: true }
          : { join_plan: plansToConfirm[0], confirm_join_plan: true })
        : {}),
    };
  };

  const applyEvidenceResult = (response: EvidencePreviewResult, request: EvidencePreviewRequest) => {
    setEvidenceRequest(request);
    setEvidenceResult(response);
    setOperationsAnswer(null);
    setOperationsError(null);
    setEvidenceDrawer({ isOpen: false, edgeIndex: 0, tab: 'matched' });
    setPendingPlanIds([]);
    setRejectedPlanIds([]);
  };

  const waitForEvidenceJob = async (request: EvidencePreviewRequest): Promise<EvidencePreviewResult> => {
    const started = await nlpCorrelationApi.startEvidenceJob(request);
    setEvidenceJob({
      job_id: started.job_id,
      status: started.status,
      stage: 'queued',
      progress: 0,
    });

    const deadline = Date.now() + EVIDENCE_JOB_MAX_WAIT_MS;
    while (Date.now() < deadline) {
      await new Promise<void>((resolve) => window.setTimeout(resolve, EVIDENCE_JOB_POLL_INTERVAL_MS));
      const job = await nlpCorrelationApi.getEvidenceJob(started.job_id);
      setEvidenceJob(job);
      if (job.status === 'completed') {
        if (!job.result) throw new Error('The evidence job completed without a result. Please try again.');
        return job.result;
      }
      if (job.status === 'failed') {
        throw new Error(job.error || 'The evidence job could not finish. Please try a smaller table scope.');
      }
      if (job.status === 'cancelled') {
        throw new Error('The evidence job was cancelled.');
      }
    }
    throw new Error('This evidence review is taking longer than expected. Try a smaller table scope or retry shortly.');
  };

  const runEvidenceCorrelation = async (plansToConfirm: EvidenceJoinPlan[] = [], confirmNoPlans = false) => {
    if (evidenceSelection.length < 1) return;
    const scopedTableCount = Object.values(tableSelection).reduce((total, refs) => total + refs.length, 0);
    if (!tableCatalog || scopedTableCount < 2) {
      setEvidenceError('Choose at least two sheets or files first. Nothing has been merged or changed.');
      if (!tableCatalog) await loadTableCatalog();
      return;
    }
    setCorrelatingEvidence(true);
    setEvidenceError(null);
    try {
      const request = buildEvidenceRequest(plansToConfirm, evidenceResult, confirmNoPlans);
      const response = await waitForEvidenceJob(request);
      applyEvidenceResult(response, request);
    } catch (error: any) {
      // Same reason as the catalog above, and sharper here: the join panels below read
      // `evidenceResult`, so leaving it set rendered "No safe automatic recommendation is
      // available" and "No join candidate was available" — conclusions about the PREVIOUS
      // evidence scope — beside an error saying this scope could not be built.
      setEvidenceResult(null);
      setEvidenceError(apiErrorMessage(error, 'Could not build a common evidence table for the selected sources.'));
    } finally {
      setCorrelatingEvidence(false);
      setEvidenceJob(null);
    }
  };

  const useRecommendedJoin = async () => {
    if (evidenceSelection.length < 1) return;
    const scopedTableCount = Object.values(tableSelection).reduce((total, refs) => total + refs.length, 0);
    if (!tableCatalog || scopedTableCount < 2) {
      setEvidenceError('Choose at least two sheets or files before asking the engine to recommend a link.');
      if (!tableCatalog) await loadTableCatalog();
      return;
    }
    if (evidenceResult) {
      const plans = recommendedPlansForResult(evidenceResult).filter(
        (plan) => !rejectedPlanIds.includes(planIdentifier(plan))
      );
      await runEvidenceCorrelation(plans);
      return;
    }

    // One explicit click can skip manual selection: first build the safe
    // read-only preview, then immediately resubmit its auto-selected edge(s)
    // as confirmed. If no safe plan exists, retain the preview for review.
    setCorrelatingEvidence(true);
    setEvidenceError(null);
    try {
      const previewRequest = buildEvidenceRequest();
      const preview = await waitForEvidenceJob(previewRequest);
      const plans = recommendedPlansForResult(preview);
      if (plans.length === 0) {
        applyEvidenceResult(preview, previewRequest);
        setEvidenceError('No safe recommended join was found. Review the proposed plans or narrow the table scope.');
        return;
      }
      const confirmedRequest = buildEvidenceRequest(plans, preview);
      const confirmed = await waitForEvidenceJob(confirmedRequest);
      applyEvidenceResult(confirmed, confirmedRequest);
    } catch (error: any) {
      setEvidenceResult(null);
      setEvidenceError(apiErrorMessage(error, 'Could not apply the recommended join.'));
    } finally {
      setCorrelatingEvidence(false);
      setEvidenceJob(null);
    }
  };

  const askOperationsQuestion = async (presetQuestion?: string) => {
    const question = (presetQuestion || operationsQuestion).trim();
    const currentEdges = evidenceResult?.evidence_sets || (evidenceResult ? [evidenceResult] : []);
    const joinsConfirmed = currentEdges.length > 0 && currentEdges.every(
      (edge) => edge.join_plan?.approval_state === 'confirmed'
    );
    if (!question || !evidenceRequest || !joinsConfirmed) {
      if (question && !joinsConfirmed) {
        setOperationsError('Confirm the selected join plan before asking an operations question. The proposed preview is available for review only.');
      }
      return;
    }
    setAnsweringOperations(true);
    setOperationsError(null);
    try {
      const response = await nlpCorrelationApi.answerOperationsQuestion({
        ...evidenceRequest,
        question,
      });
      setOperationsQuestion(question);
      setOperationsAnswer(response);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      setOperationsError(
        typeof detail === 'string'
          ? detail
          : detail?.message || 'Could not answer that question from the selected evidence.'
      );
    } finally {
      setAnsweringOperations(false);
    }
  };

  const getFileIcon = (dataType: string) => {
    switch (dataType) {
      case 'spreadsheet':
        return <FileSpreadsheet className="w-5 h-5 text-green-600" />;
      case 'report':
        return <FileText className="w-5 h-5 text-blue-600" />;
      case 'image':
        return <Image className="w-5 h-5 text-purple-600" />;
      default:
        return <FileText className="w-5 h-5 text-gray-600" />;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'analyzed':
        return <Badge variant="success">Analyzed</Badge>;
      case 'analyzing':
        return <Badge variant="warning">Analyzing</Badge>;
      case 'error':
        return <Badge variant="error">Error</Badge>;
      default:
        return <Badge variant="neutral">Pending</Badge>;
    }
  };

  const filteredItems = items.filter(item =>
    (item.title ?? '').toLowerCase().includes(searchQuery.toLowerCase()) ||
    (item.description ?? '').toLowerCase().includes(searchQuery.toLowerCase())
  );
  const evidenceEdges = evidenceResult?.evidence_sets || (evidenceResult ? [evidenceResult] : []);
  const evidenceMatchCount = evidenceResult?.matched_pair_count ?? evidenceEdges.reduce(
    (total, edge) => total + (edge.join_plan?.metrics?.matched_pair_count ?? edge.matched_rows?.length ?? 0),
    0
  );
  const candidatePlans = evidenceResult?.candidate_join_plans || [];
  const evidenceJoinsConfirmed = evidenceEdges.length > 0 && evidenceEdges.every(
    (edge) => edge.join_plan?.approval_state === 'confirmed'
  );
  const selectedCandidatePlans = candidatePlans.filter((plan, index) => (
    pendingPlanIds.includes(planIdentifier(plan, index))
      && !rejectedPlanIds.includes(planIdentifier(plan, index))
  ));
  const allCandidatePlansExcluded = candidatePlans.length > 0 && candidatePlans.every(
    (plan, index) => rejectedPlanIds.includes(planIdentifier(plan, index))
  );
  // For graph previews, the engine already materializes its highest-ranked
  // safe plan per table pair. Reuse those exact edges when the operator clicks
  // "Use recommended join" instead of reconstructing a graph from the larger
  // candidate catalog.
  const recommendedPlans = (() => {
    if (evidenceResult?.evidence_sets?.length) {
      return evidenceEdges
        .map((edge) => edge.join_plan)
        .filter((plan): plan is EvidenceJoinPlan => Boolean(
          plan
          && plan.safety?.safe_for_auto_preview
          && !rejectedPlanIds.includes(planIdentifier(plan))
        ));
    }
    if (
      evidenceResult?.join_plan?.safety?.safe_for_auto_preview
      && !rejectedPlanIds.includes(planIdentifier(evidenceResult.join_plan))
    ) {
      return [evidenceResult.join_plan];
    }
    const candidate = candidatePlans.find((plan, index) => (
      Boolean(plan.safety?.safe_for_auto_preview)
      && !rejectedPlanIds.includes(planIdentifier(plan, index))
    ));
    return candidate ? [candidate] : [];
  })();
  const selectedTableCount = Object.values(tableSelection).reduce((total, refs) => total + refs.length, 0);
  const evidenceScopeReady = Boolean(tableCatalog) && selectedTableCount >= 2;
  const matchesCatalogFilter = (table: EvidenceCatalogTable) => {
    const filter = tableCatalogFilter.trim().toLowerCase();
    if (!filter) return true;
    return [table.selection_ref, table.table_name, table.source_table, table.format]
      .filter(Boolean)
      .some(value => String(value).toLowerCase().includes(filter));
  };
  const isTableSelected = (table: EvidenceCatalogTable) => (
    (tableSelection[table.source_id] || []).includes(table.selection_ref)
  );
  const operationsQuestionExamples = [
    'Give me an overview of operations.',
    "What’s hurting us? Why are we losing time?",
    'What changed in the operation?',
    'Are we on plan, and where is the bottleneck?',
    'What needs attention first: asset, line, or shift?',
    'Where are the quality issues or reconciliation gaps?',
    'Which assets show maintenance risk?',
    'Are there safety or compliance issues to review?',
    'Are materials, inventory, or deliveries constraining operations?',
    'Is staffing, overtime, or absenteeism a shift-readiness concern?',
    'What do I check next shift?',
  ];
  const describePlanTables = (plan: EvidenceJoinPlan) => `${tableReferenceLabel(plan.left)} ↔ ${tableReferenceLabel(plan.right)}`;
  const toggleCandidatePlan = (plan: EvidenceJoinPlan, index: number) => {
    const id = planIdentifier(plan, index);
    const pairId = planTablePairIdentifier(plan);
    setRejectedPlanIds((current) => current.filter((candidateId) => candidateId !== id));
    setPendingPlanIds((current) => {
      if (current.includes(id)) return current.filter((candidateId) => candidateId !== id);
      const withoutSamePair = current.filter((candidateId) => {
        const candidateIndex = candidatePlans.findIndex((candidate, candidatePosition) => (
          planIdentifier(candidate, candidatePosition) === candidateId
        ));
        const candidate = candidateIndex >= 0 ? candidatePlans[candidateIndex] : undefined;
        return !candidate || planTablePairIdentifier(candidate) !== pairId;
      });
      return [...withoutSamePair, id];
    });
  };
  const rejectCandidatePlan = (plan: EvidenceJoinPlan, index: number) => {
    const id = planIdentifier(plan, index);
    setPendingPlanIds((current) => current.filter((candidateId) => candidateId !== id));
    setRejectedPlanIds((current) => (
      current.includes(id) ? current.filter((candidateId) => candidateId !== id) : [...current, id]
    ));
  };
  const openEvidenceDrawer = (
    edgeIndex: number,
    tab: EvidenceDrawerTab = 'matched',
    evidenceId?: string,
    citation?: EvidenceCitation,
    citationRow?: EvidenceRow,
  ) => {
    setEvidenceDrawer({ isOpen: true, edgeIndex, tab, evidenceId, citation, citationRow });
  };
  const openCitationEvidence = (citation: EvidenceCitation) => {
    const evidenceId = citation.evidence_id;
    if (evidenceId) {
      for (let edgeIndex = 0; edgeIndex < evidenceEdges.length; edgeIndex += 1) {
        const row = evidenceRowsForEdge(evidenceEdges[edgeIndex]).find((candidate) => candidate.evidence_id === evidenceId);
        if (row) {
          const tab: EvidenceDrawerTab = row.match_status === 'unmatched_left'
            ? 'unmatched_left'
            : row.match_status === 'unmatched_right'
              ? 'unmatched_right'
              : 'matched';
          openEvidenceDrawer(edgeIndex, tab, evidenceId, citation, row);
          return;
        }
      }
    }
    openEvidenceDrawer(
      0,
      'citation',
      evidenceId,
      citation,
      evidenceId ? operationsAnswer?.citation_evidence?.[evidenceId] : undefined,
    );
  };
  const citationsFor = (citations?: EvidenceCitation[], evidenceIds?: string[]): EvidenceCitation[] => {
    if (citations?.length) return citations;
    if (!evidenceIds?.length) return [];
    return (operationsAnswer?.answer.citations || []).filter((citation) => (
      Boolean(citation.evidence_id && evidenceIds.includes(citation.evidence_id))
    ));
  };
  const activeDrawerEdge = evidenceDrawer.tab === 'citation' && evidenceDrawer.citation
    ? undefined
    : (evidenceEdges[evidenceDrawer.edgeIndex] || evidenceEdges[0]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-opsgrid-text">Intake Inbox</h1>
        <p className="text-opsgrid-text-secondary mt-1">
          Upload operational files, then review deterministic evidence links before asking AI to explain them
        </p>
      </div>

      {/* Upload Section */}
      <Card title="Upload Data for Analysis">
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-opsgrid-text mb-1">Title *</label>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Enter a descriptive title"
              />
            </div>
            <div>
              <label htmlFor="intakeinbox-data-type" className="block text-sm font-medium text-opsgrid-text mb-1">Data Type</label>
              <select
              id="intakeinbox-data-type"
                value={dataType}
                onChange={(e) => setDataType(e.target.value as any)}
                className="w-full px-3 py-2 border border-opsgrid-border rounded-md bg-opsgrid-bg text-opsgrid-text"
              >
                <option value="document">Document</option>
                <option value="spreadsheet">Structured data (Excel, CSV, JSON, XML, Parquet)</option>
                <option value="report">Report (PDF, Word, HTML)</option>
                <option value="image">Image / scanned evidence</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-opsgrid-text mb-1">Description</label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional description of the data"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-opsgrid-text mb-1">File or ZIP batch *</label>
            <div
              className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors ${
                uploadDropActive
                  ? 'border-opsgrid-primary bg-opsgrid-primary/5'
                  : 'border-opsgrid-border hover:border-opsgrid-border-emphasis'
              }`}
              onDragEnter={(event) => {
                event.preventDefault();
                setUploadDropActive(true);
              }}
              onDragOver={(event) => {
                event.preventDefault();
                event.dataTransfer.dropEffect = 'copy';
                setUploadDropActive(true);
              }}
              onDragLeave={(event) => {
                if (event.currentTarget === event.target) setUploadDropActive(false);
              }}
              onDrop={handleUploadDrop}
            >
              {selectedFile ? (
                <div className="flex items-center justify-center gap-2">
                  {getFileIcon(dataType)}
                  <span className="text-sm text-opsgrid-text">{selectedFile.name}</span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setSelectedFile(null);
                      setUploadError(null);
                    }}
                  >
                    Remove
                  </Button>
                </div>
              ) : (
                <div>
                  <Upload className="w-8 h-8 mx-auto text-opsgrid-text-secondary mb-2" />
                  <p className="text-sm text-opsgrid-text-secondary mb-2">
                    Drag and drop a file or ZIP batch here, or select one below
                  </p>
                  <input
                    type="file"
                    onChange={handleFileSelect}
                    className="hidden"
                    id="file-upload"
                    accept=".zip,application/zip,.csv,.tsv,.tab,.xlsx,.xls,.xlsm,.xlsb,.ods,.numbers,.parquet,.pq,.arrow,.feather,.json,.jsonl,.ndjson,.xml,.pdf,.docx,.doc,.rtf,.odt,.html,.htm,.eml,.png,.jpg,.jpeg,.gif,.webp,.bmp,.tiff,.tif,.txt,.md,.yaml,.yml"
                  />
                  <label htmlFor="file-upload">
                    <Button variant="outline" size="sm" onClick={() => document.getElementById('file-upload')?.click()}>
                      Select file or ZIP
                    </Button>
                  </label>
                </div>
              )}
            </div>
            {uploadError && <p className="mt-2 text-sm text-red-600">{uploadError}</p>}
          </div>

          <div className="flex justify-end">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  onClick={handleUpload}
                  disabled={!selectedFile || !title || uploading}
                  className="min-w-[120px]"
                >
                  {uploading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Uploading...
                    </>
                  ) : (
                    <>
                      <Upload className="w-4 h-4 mr-2" />
                      Upload
                    </>
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent>Upload file for AI analysis</TooltipContent>
            </Tooltip>
          </div>
        </div>
      </Card>

      <Card title="Compare selected files">
        <div className="space-y-3">
          <p className="text-sm text-opsgrid-text-secondary">
            Build a reviewable comparison without merging or changing the original files.
          </p>
          {evidenceSelection.length > 0 && (
            <div className="rounded-md border border-opsgrid-border bg-opsgrid-bg p-3 text-sm">
              <p className="font-medium text-opsgrid-text">
                {evidenceSelection.length} source{evidenceSelection.length === 1 ? '' : 's'} added to this evidence review
              </p>
              <p className="mt-1 text-xs text-opsgrid-text-secondary">
                Nothing has been copied, merged, analyzed, or added to a chat yet. Next, choose the sheets or files you want to compare.
              </p>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant="info">{evidenceSelection.length} source{evidenceSelection.length === 1 ? '' : 's'} selected</Badge>
            <Button
              size="sm"
              variant="outline"
              onClick={loadTableCatalog}
              disabled={evidenceSelection.length < 1 || loadingTableCatalog || correlatingEvidence}
            >
              {loadingTableCatalog ? (
                <><Loader2 className="w-3 h-3 mr-2 animate-spin" />Inspecting tables...</>
              ) : tableCatalog ? '1. Adjust sheets or files' : '1. Choose sheets or files'}
            </Button>
            <Button
              size="sm"
              onClick={() => runEvidenceCorrelation()}
              disabled={!evidenceScopeReady || correlatingEvidence}
            >
              {correlatingEvidence ? (
                <><Loader2 className="w-3 h-3 mr-2 animate-spin" />Building evidence...</>
              ) : '2. Find possible links'}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={useRecommendedJoin}
              disabled={!evidenceScopeReady || correlatingEvidence}
            >
              {evidenceResult ? '3. Use recommended link' : 'Skip review — use recommended setup'}
            </Button>
            {selectedTableCount > 0 && (
              <Badge variant="neutral">{selectedTableCount} sheet{selectedTableCount === 1 ? '' : 's'} or file{selectedTableCount === 1 ? '' : 's'} chosen</Badge>
            )}
          </div>
          {evidenceSelection.length > 0 && !tableCatalog && (
            <p className="text-xs text-opsgrid-text-secondary">Start with step 1. Large ZIPs must be narrowed to a small set before the engine compares them.</p>
          )}
          {tableCatalog && selectedTableCount < 2 && (
            <p className="text-xs text-opsgrid-text-secondary">Select at least two sheets or files to enable step 2.</p>
          )}
          {evidenceScopeReady && !evidenceResult && (
            <p className="text-xs text-opsgrid-text-secondary">
              In a hurry? The skip option previews this small scope and confirms only the engine’s safest available link. If none is safe, it stops for your review.
            </p>
          )}
          {evidenceJob && (
            <div role="status" className="flex flex-wrap items-center gap-2 rounded border border-status-maintenance/50 bg-status-maintenance/10 p-3 text-sm text-opsgrid-text">
              <Loader2 className="h-4 w-4 animate-spin text-status-maintenance" />
              <span>
                {humanizeTechnicalLabel(evidenceJob.stage || evidenceJob.status, 'Preparing evidence')}
                {typeof evidenceJob.progress === 'number' ? ` · ${Math.round(evidenceJob.progress)}%` : ''}
              </span>
              {typeof evidenceJob.processed === 'number' && typeof evidenceJob.total === 'number' && evidenceJob.total > 0 && (
                <span className="text-xs text-opsgrid-text-secondary">{evidenceJob.processed} of {evidenceJob.total} sources</span>
              )}
              <span className="text-xs text-opsgrid-text-secondary">You can stay on this page while the review finishes.</span>
            </div>
          )}
          {tableCatalogError && <p className="rounded border border-status-alarm/50 bg-status-alarm/10 p-2 text-sm text-status-alarm">{tableCatalogError}</p>}
          {tableCatalog && (
            <div className="rounded-md border border-opsgrid-border bg-opsgrid-bg p-3 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-medium text-opsgrid-text">Choose a small comparison scope</p>
                  <p className="text-xs text-opsgrid-text-secondary">
                    For a ZIP, each selected archive member is read separately. Pick the two to six sheets/files relevant to one operations question.
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={useRecommendedOperationalTables} disabled={correlatingEvidence}>
                    Use 6-table starter scope
                  </Button>
                  {selectedTableCount > 0 && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={correlatingEvidence}
                      onClick={() => {
                        setTableSelection({});
                        setEvidenceResult(null);
                        setEvidenceRequest(null);
                        setOperationsAnswer(null);
                        setOperationsError(null);
                        setPendingPlanIds([]);
                        setRejectedPlanIds([]);
                        setEvidenceDrawer({ isOpen: false, edgeIndex: 0, tab: 'matched' });
                      }}
                    >
                      Clear scope
                    </Button>
                  )}
                </div>
              </div>
              <Input
                value={tableCatalogFilter}
                onChange={(event) => setTableCatalogFilter(event.target.value)}
                placeholder="Filter tables or archive members..."
              />
              <div className="max-h-72 space-y-3 overflow-auto pr-1">
                {tableCatalog.sources.map((source) => {
                  const visibleTables = (source.tables || []).filter(matchesCatalogFilter);
                  return (
                    <div key={source.source_id} className="rounded border border-opsgrid-border p-2">
                      <div className="flex items-center justify-between gap-2 text-xs">
                        <span className="font-medium text-opsgrid-text truncate">{humanizeSourceName(source.file_name || source.source_id)}</span>
                        <Badge variant={source.status === 'rejected' || source.status === 'unavailable' ? 'error' : 'neutral'}>
                          {source.status || 'catalogued'}
                        </Badge>
                      </div>
                      {visibleTables.length === 0 ? (
                        <p className="mt-2 text-xs text-opsgrid-text-secondary">No tables match this filter.</p>
                      ) : (
                        <div className="mt-2 space-y-1">
                          {visibleTables.map((table) => (
                            <label key={`${table.source_id}:${table.selection_ref}`} className="flex cursor-pointer items-start gap-2 rounded p-1 text-xs hover:bg-opsgrid-hover">
                              <input
                                type="checkbox"
                                checked={isTableSelected(table)}
                                onChange={() => toggleTableSelection(table.source_id, table.selection_ref)}
                                disabled={correlatingEvidence}
                              />
                              <span className="min-w-0 flex-1">
                                <span className="block text-opsgrid-text">{catalogTableLabel(table)}</span>
                                <span className="text-opsgrid-text-secondary">
                                  {table.selection_kind === 'archive_member' ? 'File in ZIP' : 'Workbook table'}
                                  {table.format ? ` · ${String(table.format).toUpperCase()}` : ''}
                                  {table.parsed_table_count_preview ? ` · ${table.parsed_table_count_preview} table${table.parsed_table_count_preview === 1 ? '' : 's'}` : ''}
                                </span>
                              </span>
                            </label>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {evidenceError && (
            <div className="rounded border border-status-alarm/50 bg-status-alarm/10 p-3 text-sm text-status-alarm">
              <p>{evidenceError}</p>
              <Button
                size="sm"
                variant="outline"
                className="mt-2 border-status-alarm/60 text-status-alarm hover:bg-status-alarm/10"
                onClick={loadTableCatalog}
                disabled={loadingTableCatalog || evidenceSelection.length < 1}
              >
                Choose sheets or files
              </Button>
            </div>
          )}
          {evidenceResult && (
            <div className="rounded-md border border-opsgrid-border p-3 space-y-3">
              <div className="flex flex-wrap gap-2 text-sm">
                <Badge variant={evidenceResult.quality?.evidence_quality_label === 'high' ? 'success' : 'warning'}>
                  Evidence quality: {evidenceResult.quality?.evidence_quality_label || 'review required'}
                </Badge>
                <Badge variant="info">{evidenceMatchCount} matched row pair{evidenceMatchCount === 1 ? '' : 's'}</Badge>
                {evidenceRequest && (
                  <Badge variant="neutral">
                    {evidenceResult.input_scope?.readable_table_count || evidenceRequest.intake_ids.length} evidence table{(evidenceResult.input_scope?.readable_table_count || evidenceRequest.intake_ids.length) === 1 ? '' : 's'}
                  </Badge>
                )}
                <Badge variant={evidenceJoinsConfirmed ? 'success' : 'warning'}>
                  {evidenceJoinsConfirmed ? 'Join plan confirmed' : 'Join review required'}
                </Badge>
                <Badge variant="neutral">Association only — not causation</Badge>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => openEvidenceDrawer(0, 'matched')}
                  disabled={evidenceEdges.length === 0}
                >
                  View evidence
                </Button>
              </div>
              <p className="text-xs text-opsgrid-text-secondary">
                {evidenceResult.quality?.interpretation || 'Every row retains its source, table, and row lineage.'}
              </p>
              {(evidenceResult.response_truncated || evidenceResult.truncated) && (
                <p className="rounded border border-status-warning/50 bg-status-warning/10 p-2 text-xs text-opsgrid-text">
                  This is a bounded preview. The plan metrics are the reliable counts; the row drawer shows only returned records.
                </p>
              )}
              {evidenceResult.graph_scope?.partial_graph && (
                <p className="rounded bg-status-warning/10 p-2 text-xs text-opsgrid-text-secondary">
                  {evidenceResult.graph_scope.scope_note || 'Only part of the selected table graph was materialized. Narrow the table scope before relying on an operational answer.'}
                </p>
              )}
              {boundedAnalysisNotes(evidenceResult).length > 0 && (
                <div
                  data-testid="bounded-analysis-notes"
                  className="rounded border border-status-warning/50 bg-status-warning/10 p-2 text-xs text-opsgrid-text-secondary"
                >
                  <p className="font-medium text-opsgrid-text">What these figures leave out</p>
                  <ul className="mt-1 list-disc space-y-1 pl-4">
                    {boundedAnalysisNotes(evidenceResult).map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                </div>
              )}
              {evidenceJoinsConfirmed ? (
                <div className="rounded border border-status-running/50 bg-status-running/10 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium text-opsgrid-text">Confirmed evidence scope</p>
                      <p className="text-xs text-opsgrid-text-secondary">Operations questions will use only these explicitly confirmed joins.</p>
                    </div>
                    <Button size="sm" variant="outline" onClick={() => openEvidenceDrawer(0, 'join_details')}>
                      Review join details
                    </Button>
                  </div>
                  <div className="mt-3 space-y-2">
                    {evidenceEdges.map((edge, index) => edge.join_plan && (
                      <div key={edge.join_plan.plan_id || `confirmed-edge-${index}`} className="flex flex-wrap items-center justify-between gap-2 rounded border border-status-running/50 bg-opsgrid-panel p-2 text-xs">
                        <span className="min-w-0">
                          <span className="block font-medium text-opsgrid-text">{describePlanTables(edge.join_plan)}</span>
                          <span className="text-opsgrid-text-secondary">Match on {describeJoinKeys(edge.join_plan)} · {formatCount(edge.join_plan.metrics?.matched_pair_count)} matched pair{edge.join_plan.metrics?.matched_pair_count === 1 ? '' : 's'}</span>
                        </span>
                        <Button size="sm" variant="outline" onClick={() => openEvidenceDrawer(index, 'matched')}>
                          View rows
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="rounded border border-status-warning/50 bg-status-warning/10 p-3 space-y-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-opsgrid-text">Review proposed joins before using operational answers</p>
                      <p className="mt-1 text-xs text-opsgrid-text-secondary">Choose one proposed key set per table pair, inspect its match quality, then confirm. You can also explicitly use the engine’s safe recommendation.</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        onClick={useRecommendedJoin}
                        disabled={recommendedPlans.length === 0 || correlatingEvidence}
                      >
                        Use recommended join
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => runEvidenceCorrelation(selectedCandidatePlans)}
                        disabled={selectedCandidatePlans.length === 0 || correlatingEvidence}
                      >
                        Confirm selected ({selectedCandidatePlans.length})
                      </Button>
                      {allCandidatePlansExcluded && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => runEvidenceCorrelation([], true)}
                          disabled={correlatingEvidence}
                        >
                          Apply exclusions
                        </Button>
                      )}
                    </div>
                  </div>
                  {recommendedPlans.length > 0 ? (
                    <p className="text-xs text-opsgrid-text-secondary">Use recommended join skips manual selection and explicitly confirms the engine’s best safe plan{recommendedPlans.length === 1 ? '' : 's'} for this scope.</p>
                  ) : (
                    <p className="text-xs text-opsgrid-text-secondary">No safe automatic recommendation is available. Select only a plan you have reviewed closely.</p>
                  )}
                  {allCandidatePlansExcluded && (
                    <p className="rounded border border-status-warning/50 bg-opsgrid-panel p-2 text-xs text-opsgrid-text">All proposed joins are excluded for this review. Apply exclusions to record an intentionally no-join evidence scope; Operations Lead questions will remain unavailable.</p>
                  )}
                  {candidatePlans.length > 0 ? (
                    <div className="space-y-2">
                      {candidatePlans.slice(0, 8).map((plan, index) => {
                        const planId = planIdentifier(plan, index);
                        const isSelected = pendingPlanIds.includes(planId);
                        const isRejected = rejectedPlanIds.includes(planId);
                        const previewEdgeIndex = evidenceEdges.findIndex((edge) => edge.join_plan?.plan_id === plan.plan_id);
                        const metrics = plan.metrics;
                        return (
                          <div key={planId} className={`rounded border p-3 ${isRejected ? 'border-opsgrid-border bg-opsgrid-bg opacity-70' : 'border-status-warning/50 bg-opsgrid-panel'}`}>
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <label className="flex min-w-0 cursor-pointer items-start gap-2">
                                <input
                                  type="checkbox"
                                  checked={isSelected}
                                  onChange={() => toggleCandidatePlan(plan, index)}
                                />
                                <span className="min-w-0">
                                  <span className="block text-sm font-medium text-opsgrid-text">{describePlanTables(plan)}</span>
                                  <span className="mt-1 block text-xs text-opsgrid-text-secondary">Match on {describeJoinKeys(plan)}</span>
                                </span>
                              </label>
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge variant={plan.safety?.safe_for_auto_preview ? 'success' : 'warning'}>
                                  {isRejected ? 'Excluded' : plan.safety?.safe_for_auto_preview ? 'Safe recommendation' : 'Manual review'}
                                </Badge>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => rejectCandidatePlan(plan, index)}
                                >
                                  {isRejected ? 'Restore' : 'Exclude'}
                                </Button>
                                {previewEdgeIndex >= 0 && (
                                  <Button size="sm" variant="outline" onClick={() => openEvidenceDrawer(previewEdgeIndex, 'join_details')}>
                                    Inspect
                                  </Button>
                                )}
                              </div>
                            </div>
                            <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
                              <div><span className="block text-opsgrid-text-secondary">Matched pairs</span><span className="font-medium text-opsgrid-text">{formatCount(metrics?.matched_pair_count)}</span></div>
                              <div><span className="block text-opsgrid-text-secondary">Left / right coverage</span><span className="font-medium text-opsgrid-text">{formatPercent(metrics?.left_match_coverage)} / {formatPercent(metrics?.right_match_coverage)}</span></div>
                              <div><span className="block text-opsgrid-text-secondary">Key completeness</span><span className="font-medium text-opsgrid-text">{formatPercent(metrics?.left_key_completeness)} / {formatPercent(metrics?.right_key_completeness)}</span></div>
                              <div><span className="block text-opsgrid-text-secondary">Cardinality warnings</span><span className="font-medium text-opsgrid-text">{formatCount(metrics?.many_to_many_key_count)} many-to-many · {formatCount(metrics?.one_to_many_key_count)} one-to-many</span></div>
                            </div>
                            {!!plan.safety?.warnings?.length && (
                              <p className="mt-2 text-xs text-opsgrid-text-secondary">{plan.safety.warnings[0]}</p>
                            )}
                          </div>
                        );
                      })}
                      {candidatePlans.length > 8 && <p className="text-xs text-opsgrid-text-secondary">Showing the first 8 of {candidatePlans.length} proposed plans. Narrow the table scope to review fewer alternatives.</p>}
                    </div>
                  ) : (
                    <p className="rounded border border-status-warning/50 bg-opsgrid-panel p-3 text-sm text-opsgrid-text">No join candidate was available. Add shared identifiers or revise the selected table scope.</p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </Card>

      {evidenceResult && evidenceRequest && (
        evidenceJoinsConfirmed ? (
        <Card title="Operations Lead Questions">
          <div className="space-y-3">
            <p className="text-sm text-opsgrid-text-secondary">
              Ask in normal operations language. Answers stay tied to reviewed evidence, show applied filters, and ask for clarification rather than guessing.
            </p>
            <div className="flex flex-wrap gap-2">
              {operationsQuestionExamples.map((question) => (
                <Button
                  key={question}
                  size="sm"
                  variant="outline"
                  onClick={() => askOperationsQuestion(question)}
                  disabled={answeringOperations}
                >
                  {question}
                </Button>
              ))}
            </div>
            <div className="flex gap-2">
              <Input
                value={operationsQuestion}
                onChange={(event) => setOperationsQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    askOperationsQuestion();
                  }
                }}
                placeholder="Example: Which night-shift assets need inspection first?"
              />
              <Button
                onClick={() => askOperationsQuestion()}
                disabled={!operationsQuestion.trim() || answeringOperations}
              >
                {answeringOperations ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Answering...</> : 'Ask'}
              </Button>
            </div>
            {operationsError && <p className="text-sm text-red-600">{operationsError}</p>}
            {operationsAnswer && (
              <div className="rounded-md border border-opsgrid-border p-3 space-y-3">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="info">{operationsAnswer.answer.intent?.replace(/_/g, ' ') || 'operations answer'}</Badge>
                  <Badge variant="neutral">Evidence-backed — association is not causation</Badge>
                </div>
                {(operationsAnswer.evidence_scope?.review_required || operationsAnswer.answer.guardrails?.human_approval?.required) && (
                  <p className="rounded border border-status-warning/50 bg-status-warning/10 p-2 text-xs text-opsgrid-text">
                    Supervisor review is required before acting. Verify the join/data-quality warnings, current conditions, and cited source rows.
                  </p>
                )}
                {operationsAnswer.evidence_scope?.operations_source_scope?.truncated && (
                  <p className="rounded border border-status-warning/50 bg-status-warning/10 p-2 text-xs text-opsgrid-text">
                    This answer uses a bounded source-record packet. Treat totals as a review sample and run an approved full job before making a material decision.
                  </p>
                )}
                <div>
                  <p className="font-medium text-opsgrid-text">{operationsAnswer.answer.title}</p>
                  <p className="mt-1 text-sm text-opsgrid-text-secondary">{operationsAnswer.answer.summary}</p>
                </div>
                {operationsAnswer.answer.data_freshness?.caveat && (
                  <p className="rounded bg-status-warning/10 p-2 text-xs text-opsgrid-text-secondary">
                    {String(operationsAnswer.answer.data_freshness.caveat)}
                  </p>
                )}
                {operationsAnswer.answer.scope_filter?.status === 'applied' && (
                  <p className="rounded bg-status-maintenance/10 p-2 text-xs text-opsgrid-text-secondary">
                    Applied scope: {(operationsAnswer.answer.scope_filter.filters || []).map((filter) => (
                      `${filter.dimension}: ${(filter.values || []).join(', ')}`
                    )).join(' · ')}
                  </p>
                )}
                {operationsAnswer.answer.scope_filter?.status === 'unmatched' && (
                  <p className="rounded bg-status-warning/10 p-2 text-xs text-opsgrid-text-secondary">
                    The requested filter was not applied because no exact matching source value was found. The engine did not substitute the full dataset.
                  </p>
                )}
                {(operationsAnswer.answer.findings || []).slice(0, 5).map((finding, index) => {
                  const findingCitations = citationsFor(finding.citations, finding.evidence_ids);
                  return (
                    <div key={`${finding.title || 'finding'}-${index}`} className="rounded border border-opsgrid-border p-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-medium text-opsgrid-text">{finding.title || 'Evidence finding'}</p>
                        {finding.metric && <Badge variant="neutral">{humanizeTechnicalLabel(finding.metric)}</Badge>}
                      </div>
                      <p className="mt-1 text-sm text-opsgrid-text-secondary">{finding.detail}</p>
                      {finding.uncertainty?.[0] && <p className="mt-2 text-xs text-opsgrid-text-secondary">Review note: {finding.uncertainty[0]}</p>}
                      {findingCitations.length > 0 && (
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-opsgrid-text-secondary">
                          <span>{findingCitations.length} cited source row{findingCitations.length === 1 ? '' : 's'}</span>
                          <Button size="sm" variant="outline" onClick={() => openCitationEvidence(findingCitations[0])}>
                            View evidence
                          </Button>
                        </div>
                      )}
                    </div>
                  );
                })}
                {!!operationsAnswer.answer.checklist?.length && (
                  <div className="rounded border border-status-warning/50 bg-status-warning/10 p-3">
                    <p className="text-sm font-medium text-opsgrid-text">Proposed next-shift checklist — supervisor approval required</p>
                    <ol className="mt-2 list-decimal space-y-2 pl-5 text-sm text-opsgrid-text">
                      {operationsAnswer.answer.checklist.map((item, index) => {
                        const checklistCitations = citationsFor(item.citations, item.evidence_ids);
                        return (
                          <li key={`${item.action || 'check'}-${index}`}>
                            <span>{item.action}</span>
                            {item.why && <span className="block text-xs text-opsgrid-text-secondary">Why: {item.why}</span>}
                            {checklistCitations.length > 0 && (
                              <Button size="sm" variant="outline" className="mt-1" onClick={() => openCitationEvidence(checklistCitations[0])}>
                                View evidence
                              </Button>
                            )}
                          </li>
                        );
                      })}
                    </ol>
                  </div>
                )}
              </div>
            )}
          </div>
        </Card>
        ) : (
          <Card title="Operations Lead Questions">
            <div className="rounded border border-status-warning/50 bg-status-warning/10 p-4">
              <p className="text-sm font-medium text-opsgrid-text">Confirm a join plan to unlock operations questions</p>
              <p className="mt-1 text-sm text-opsgrid-text-secondary">The preview is safe to inspect, but it is not an approved operational evidence scope yet. Review the proposed joins above or explicitly use the recommended safe join.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  onClick={useRecommendedJoin}
                  disabled={recommendedPlans.length === 0 || correlatingEvidence}
                >
                  Use recommended join
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => openEvidenceDrawer(0, 'join_details')}
                  disabled={evidenceEdges.length === 0}
                >
                  Review proposed evidence
                </Button>
              </div>
            </div>
          </Card>
        )
      )}

      {/* Items List */}
      <Card
        title="Intake Items"
        action={
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 transform -translate-y-1/2 text-opsgrid-text-secondary" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search items..."
                className="pl-9 w-64"
              />
            </div>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-3 py-2 border border-opsgrid-border rounded-md bg-opsgrid-bg text-opsgrid-text text-sm"
            >
              <option value="all">All Status</option>
              <option value="pending">Pending</option>
              <option value="analyzed">Analyzed</option>
              <option value="error">Error</option>
            </select>
          </div>
        }
      >
        {/* A failed upload or analysis, said out loud (FS-478). Above the list rather than
            beside the button, because the analyse buttons are per-row and the failure has
            to survive the row re-rendering. */}
        {actionError && (
          <div
            role="alert"
            className="mb-4 rounded border border-status-alarm/40 bg-status-alarm/10 px-3 py-2 text-sm text-status-alarm"
          >
            {actionError}
          </div>
        )}
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-8 h-8 animate-spin text-opsgrid-primary" />
          </div>
        ) : loadError ? (
          <div className="text-center py-8 text-status-alarm" role="alert">
            <p>{loadError}</p>
            <p className="text-sm text-opsgrid-text-secondary">
              This is a loading failure, not an empty inbox.
            </p>
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="text-center py-8 text-opsgrid-text-secondary">
            <FileText className="w-12 h-12 mx-auto mb-2 opacity-50" />
            <p>No items in the inbox</p>
            <p className="text-sm">Upload data to get started with AI analysis</p>
          </div>
        ) : (
          <div className="space-y-3">
            {filteredItems.map((item) => (
              <div
                key={item.id}
                className="border border-opsgrid-border rounded-lg p-4 hover:border-opsgrid-border-emphasis transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-3 flex-1">
                    <div className="mt-1">
                      {getFileIcon(item.data_type)}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="font-medium text-opsgrid-text">{item.title}</h3>
                        {getStatusBadge(item.status)}
                      </div>
                      <p className="text-sm text-opsgrid-text-secondary mb-2">{item.description}</p>
                      <div className="flex items-center gap-2 text-xs text-opsgrid-text-secondary">
                        <span>{item.data_type}</span>
                        <span>•</span>
                        <span>{new Date(item.created_at).toLocaleString()}</span>
                        {item.file_name && (
                          <>
                            <span>•</span>
                            <span title={item.file_name}>{humanizeSourceName(item.file_name, 'Uploaded file')}</span>
                          </>
                        )}
                      </div>
                      <label className="mt-3 inline-flex cursor-pointer items-start gap-2 text-xs text-opsgrid-text-secondary">
                        <input
                          type="checkbox"
                          checked={evidenceSelection.includes(item.id)}
                          onChange={() => toggleEvidenceSelection(item.id)}
                          disabled={correlatingEvidence}
                        />
                        <span>
                          <span className="block font-medium text-opsgrid-text">
                            {evidenceSelection.includes(item.id) ? 'Added to this evidence review' : 'Add to this evidence review'}
                          </span>
                          <span className="block text-opsgrid-text-secondary">This only selects the file for comparison; it does not create a chat or merge data.</span>
                        </span>
                      </label>
                    </div>
                  </div>
                  <div className="flex flex-col gap-2 ml-4">
                    {item.status === 'pending' && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            size="sm"
                            onClick={() => handleAnalyze(item.id)}
                            disabled={analyzing === item.id}
                          >
                            {analyzing === item.id ? (
                              <>
                                <Loader2 className="w-3 h-3 mr-2 animate-spin" />
                                Analyzing...
                              </>
                            ) : (
                              <>
                                <CheckCircle className="w-3 h-3 mr-2" />
                                Analyze
                              </>
                            )}
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Run AI correlation analysis on this item</TooltipContent>
                      </Tooltip>
                    )}
                    {item.status === 'analyzed' && !item.analysis_result && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={loadingResults === item.id}
                            onClick={async () => {
                              // P3: this button had NO onClick — and the list endpoint
                              // never sends analysis_result, so for any item analysed
                              // before the last reload this dead button was the only
                              // path to results that only GET /intake/{id} carries.
                              setActionError(null);
                              setLoadingResults(item.id);
                              try {
                                const full = await nlpCorrelationApi.getIntakeItem(item.id);
                                setItems((prev) =>
                                  prev.map((existing) =>
                                    existing.id === item.id
                                      ? { ...existing, analysis_result: full.analysis_result }
                                      : existing,
                                  ),
                                );
                              } catch {
                                setActionError(
                                  `Could not load results for "${item.title}".`,
                                );
                              } finally {
                                setLoadingResults(null);
                              }
                            }}
                          >
                            {loadingResults === item.id ? (
                              <>
                                <Loader2 className="w-3 h-3 mr-2 animate-spin" />
                                Loading…
                              </>
                            ) : (
                              'View Results'
                            )}
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Load the detailed analysis results</TooltipContent>
                      </Tooltip>
                    )}
                  </div>
                </div>

                {/* Analysis Results */}
                {item.analysis_result && (
                  <div className="mt-4 pt-4 border-t border-opsgrid-border">
                    <div className="grid grid-cols-2 gap-4 mb-3">
                      <div>
                        <p className="text-xs font-medium text-opsgrid-text-secondary mb-1">Risk Score</p>
                        <Badge variant={item.analysis_result.risk_score > 50 ? 'warning' : 'success'}>
                          {item.analysis_result.risk_score.toFixed(1)}/100
                        </Badge>
                      </div>
                      <div>
                        <p className="text-xs font-medium text-opsgrid-text-secondary mb-1">Domains</p>
                        <div className="flex flex-wrap gap-1">
                          {item.analysis_result.domains_analyzed?.map((domain: string) => (
                            <Badge key={domain} variant="info" className="text-xs">
                              {domain}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    </div>
                    {/* The analysis was built from part of the document (FS-456).

                        The parser caps pages, and caps text within each page. Both caps
                        already reached this component and neither was rendered — so a risk
                        score derived from the first 20k characters of a 90k-character page
                        read exactly like one derived from the whole thing. A confident
                        number over a partial reading is worse than no number, because
                        nothing about it looks partial. */}
                    {(item.analysis_result.truncated ||
                      item.analysis_result.pages_text_truncated > 0) && (
                      <div className="mb-3 rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2">
                        <p className="text-xs text-amber-300">
                          Analysed from part of the document
                          {item.analysis_result.truncated && ' — some pages were not read'}
                          {item.analysis_result.pages_text_truncated > 0 &&
                            ` — text was cut on ${item.analysis_result.pages_text_truncated} page(s)` +
                              (item.analysis_result.text_chars_dropped
                                ? ` (${item.analysis_result.text_chars_dropped.toLocaleString()} characters dropped)`
                                : '')}
                          . Findings below may be incomplete.
                        </p>
                      </div>
                    )}
                    <div>
                      <p className="text-xs font-medium text-opsgrid-text-secondary mb-1">Analysis</p>
                      <p className="text-sm text-opsgrid-text">{item.analysis_result.analysis}</p>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
      <EvidenceDrawer
        isOpen={evidenceDrawer.isOpen}
        onClose={() => setEvidenceDrawer((current) => ({ ...current, isOpen: false }))}
        edge={activeDrawerEdge}
        edgeLabel={activeDrawerEdge?.join_plan ? describePlanTables(activeDrawerEdge.join_plan) : undefined}
        initialTab={evidenceDrawer.tab}
        focusEvidenceId={evidenceDrawer.evidenceId}
        citation={evidenceDrawer.citation}
        citationRow={evidenceDrawer.citationRow}
      />
    </div>
  );
};
