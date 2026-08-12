import { api } from './client';
import { USE_MOCK } from './mockMode';
import { mockIntakeItems, mockIntakeList } from './mocks/nlpMocks';

export interface NLPQueryRequest {
  query: string;
  context?: Record<string, any>;
  include_domains?: string[];
  auto_integrate?: boolean;
}

export interface NLPQueryResponse {
  query: string;
  analysis: string;
  domains_analyzed: string[];
  risk_score: number;
  recommended_actions: any[];
  kanban_tasks: any[];
  compliance_implications?: string[];
  integration_result?: { [key: string]: string[] };
}

export interface IntakeUploadRequest {
  title: string;
  description?: string;
  data_type: 'spreadsheet' | 'report' | 'image' | 'document';
  category?: string;
}

export interface IntakeAnalysisRequest {
  intake_id: string;
  query?: string;
  auto_integrate?: boolean;
}

export interface IntakeItem {
  id: string;
  title: string;
  description: string;
  data_type: string;
  category: string;
  file_name?: string;
  status: string;
  analysis_result?: any;
  created_at: string;
  analyzed_at?: string;
}

export interface EvidenceTableReference {
  source_id?: string;
  source_key?: string;
  source_name?: string;
  table_name?: string;
  table_key?: string;
  [key: string]: unknown;
}

export interface EvidenceJoinKey {
  canonical_name?: string;
  name?: string;
  left_column?: string;
  right_column?: string;
  strategy?: 'exact' | 'time_bucket' | string;
  time_bucket_minutes?: number | null;
  semantic_type?: string;
  date_granularity?: boolean;
  [key: string]: unknown;
}

export interface EvidenceJoinMetrics {
  matched_pair_count?: number;
  matched_left_record_count?: number;
  matched_right_record_count?: number;
  left_keyed_record_count?: number;
  right_keyed_record_count?: number;
  left_key_completeness?: number;
  right_key_completeness?: number;
  left_match_coverage?: number;
  right_match_coverage?: number;
  key_overlap_count?: number;
  key_union_count?: number;
  selectivity?: number;
  max_pairs_per_key?: number;
  many_to_many_key_count?: number;
  one_to_many_key_count?: number;
  many_to_one_key_count?: number;
}

export interface EvidenceJoinSafety {
  safe_for_auto_preview?: boolean;
  confirmation_required?: boolean;
  strong_anchor_fields?: string[];
  warnings?: string[];
}

export interface EvidenceJoinPlan {
  plan_id?: string;
  left: EvidenceTableReference;
  right: EvidenceTableReference;
  keys: EvidenceJoinKey[];
  strategy?: 'exact' | 'time_bucket' | string;
  score?: number;
  metrics?: EvidenceJoinMetrics;
  safety?: EvidenceJoinSafety;
  approval_state?: 'proposed' | 'confirmed' | 'rejected' | string;
  explanation?: string;
  value_aliases?: Record<string, Record<string, string>>;
}

export interface EvidenceLineage {
  source_id?: string;
  source_name?: string;
  source_key?: string;
  table_name?: string;
  table_key?: string;
  row_number?: number;
  row_id?: string;
}

export interface EvidenceSourceRow {
  side?: 'left' | 'right' | string;
  lineage?: EvidenceLineage;
  values?: Record<string, unknown>;
}

export interface EvidenceRow {
  evidence_id?: string;
  match_status?: 'matched' | 'unmatched_left' | 'unmatched_right' | 'source_row' | string;
  join_key?: Record<string, string> | null;
  lineage?: EvidenceLineage[];
  source_rows?: EvidenceSourceRow[];
  fields?: Record<string, unknown>;
}

export interface EvidenceQuality {
  evidence_quality_score?: number;
  evidence_quality_label?: 'high' | 'moderate' | 'low' | string;
  review_required?: boolean;
  interpretation?: string;
  warnings?: string[];
  left_table_row_count?: number;
  right_table_row_count?: number;
  [key: string]: unknown;
}

export interface EvidenceSourceProfile {
  source_count?: number;
  table_count?: number;
  tables?: Array<EvidenceTableReference & {
    row_count?: number;
    schema?: Record<string, unknown>;
  }>;
}

export interface EvidencePreviewRequest {
  intake_ids: string[];
  join_plan?: EvidenceJoinPlan;
  join_plans?: EvidenceJoinPlan[];
  confirm_join_plan?: boolean;
  time_bucket_minutes?: number;
  include_weak_keys?: boolean;
  include_operational_analytics?: boolean;
  assumed_timezone?: string;
  schema_mappings?: Record<string, Record<string, string>>;
  // Exact table names (workbooks) or archive member paths (ZIP batches)
  // returned by catalogEvidenceTables. This bounds parsing before the evidence
  // graph profiles table pairs.
  table_selection?: Record<string, string[]>;
  apply_long_form_normalization?: boolean;
  max_match_pairs?: number;
}

export interface EvidenceJobStatus {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | string;
  stage?: string;
  progress?: number;
  processed?: number;
  total?: number;
  result?: EvidencePreviewResult | null;
  error?: string | null;
}

export interface EvidenceCatalogTable {
  selection_ref: string;
  selection_kind?: 'table' | 'archive_member' | string;
  table_name: string;
  source_table?: string;
  archive_path?: string;
  format?: string;
  row_count_preview?: number | null;
  parsed_table_count_preview?: number | null;
  parse_status?: string;
  source_id: string;
  source_name: string;
}

export interface EvidenceCatalogSource {
  source_id: string;
  file_name?: string;
  status?: string;
  tables: EvidenceCatalogTable[];
  table_limit?: Record<string, any>;
  warnings?: Array<Record<string, any>>;
  errors?: Array<Record<string, any>>;
}

export interface EvidenceCatalogResponse {
  sources: EvidenceCatalogSource[];
  selection_contract?: {
    field?: string;
    max_tables_per_source?: number;
    max_tables_per_evidence_graph?: number;
    guidance?: string;
  };
}

export interface EvidencePreviewResult {
  selection_mode: string;
  join_plan?: EvidenceJoinPlan | null;
  candidate_join_plans?: EvidenceJoinPlan[];
  evidence_rows?: EvidenceRow[];
  matched_rows?: EvidenceRow[];
  unmatched_left_rows?: EvidenceRow[];
  unmatched_right_rows?: EvidenceRow[];
  evidence_sets?: EvidencePreviewResult[];
  quality?: EvidenceQuality;
  normalization?: Record<string, any>;
  operational_analytics?: Record<string, any>;
  source_profile?: EvidenceSourceProfile;
  graph_scope?: {
    table_count?: number;
    eligible_safe_pair_count?: number;
    selected_pair_count?: number;
    relationship_limit?: number;
    partial_graph?: boolean;
    scope_note?: string;
  };
  input_scope?: {
    selected_intake_count: number;
    readable_source_count: number;
    readable_table_count: number;
    selected_table_ref_count?: number;
    single_source_multi_table: boolean;
    operations_source_record_count?: number | null;
    operations_source_records_truncated?: boolean;
  };
  relationship_count?: number;
  matched_pair_count?: number;
  review_required?: boolean;
  truncated?: boolean;
  response_truncated?: boolean;
  response_row_limit?: number;
}

export interface EvidenceCitation {
  evidence_id?: string;
  match_status?: string;
  join_key?: Record<string, string> | null;
  lineage?: EvidenceLineage[];
}

export interface OperationsFinding {
  id?: string;
  title?: string;
  detail?: string;
  statement?: string;
  metric?: string;
  evidence_ids?: string[];
  citations?: EvidenceCitation[];
  uncertainty?: string[];
  evidence?: Record<string, unknown>;
}

export interface OperationsChecklistItem {
  id?: string;
  action?: string;
  owner?: string;
  why?: string;
  evidence_ids?: string[];
  citations?: EvidenceCitation[];
  requires_human_approval?: boolean;
}

export interface OperationsLeadAnswer {
  intent?: string;
  title?: string;
  summary?: string;
  findings?: OperationsFinding[];
  citations?: EvidenceCitation[];
  checklist?: OperationsChecklistItem[];
  guardrails?: Record<string, any>;
  data_freshness?: Record<string, any>;
  scope_filter?: {
    status?: 'applied' | 'unmatched' | 'not_requested' | string;
    filters?: Array<{ dimension?: string; values?: string[] }>;
    unmatched_dimensions?: string[];
    description?: string;
  };
  suggested_questions?: Array<Record<string, any> | string>;
}

export interface OperationsQuestionResponse {
  question: string;
  answer: OperationsLeadAnswer;
  evidence_scope?: Record<string, any>;
  job_id?: string;
  // Optional bounded raw rows keyed by citation ID. Older backends omit this;
  // callers can still resolve citations against the evidence preview rows.
  citation_evidence?: Record<string, EvidenceRow>;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  analysis?: string;
  risk_score?: number;
  domains?: string[];
  actions?: any[];
  timestamp: string;
}

export const nlpCorrelationApi = {
  // NLP Query
  async queryNLP(request: NLPQueryRequest): Promise<NLPQueryResponse> {
    const response = await api.post(`/api/v1/nlp/correlation/query`, request);
    return response.data;
  },

  // Chat interface
  async chat(message: string, conversationHistory?: ChatMessage[]): Promise<ChatMessage> {
    // `conversation_history` is a BODY parameter, not a query parameter. The handler
    // declares it `Optional[List[Dict[str, str]]]`, and FastAPI reads complex types
    // from the body — so sending it in `params` with a `null` body meant the server
    // received `None` every time. The endpoint's docstring promises it "maintains
    // conversation context for multi-turn queries"; it never received any context to
    // maintain. `message` genuinely is a query parameter and stays there.
    const response = await api.post(
      `/api/v1/nlp/correlation/chat`,
      conversationHistory ?? null,
      { params: { message } }
    );
    return response.data;
  },

  // Intake Inbox
  async uploadToIntake(
    file: File,
    title: string,
    description: string = '',
    data_type: 'spreadsheet' | 'report' | 'image' | 'document' = 'document',
    category: string = 'general'
  ): Promise<IntakeItem> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('title', title);
    formData.append('description', description);
    formData.append('data_type', data_type);
    formData.append('category', category);

    const response = await api.post(`/api/v1/nlp/correlation/intake/upload`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    });
    return response.data;
  },

  async analyzeIntake(
    intake_id: string,
    query?: string,
    auto_integrate: boolean = true
  ): Promise<any> {
    const response = await api.post(`/api/v1/nlp/correlation/intake/analyze`, null, {
      params: {
        intake_id,
        query,
        auto_integrate
      }
    });
    return response.data;
  },

  async listIntakeItems(limit: number = 50, offset: number = 0, status?: string): Promise<{ items: IntakeItem[]; total: number }> {
    if (USE_MOCK) {
      return mockIntakeList(status);
    }
    const response = await api.get(`/api/v1/nlp/correlation/intake/list`, {
      params: { limit, offset, status }
    });
    return response.data;
  },

  async getIntakeItem(intake_id: string): Promise<IntakeItem> {
    if (USE_MOCK) {
      const match = mockIntakeItems.find((i) => i.id === intake_id);
      if (match) return match;
      throw new Error(`Mock intake item not found: ${intake_id}`);
    }
    const response = await api.get(`/api/v1/nlp/correlation/intake/${intake_id}`);
    return response.data;
  },

  // Deterministic, lineage-preserving correlation is separate from the
  // conversational AI summary so callers can show and confirm actual joins.
  async previewEvidence(request: EvidencePreviewRequest): Promise<EvidencePreviewResult> {
    // A small direct preview is useful for integrations, but browser screens
    // use the tracked job path below for multi-file work. Keep this safety
    // margin so an inspected result is not discarded halfway through parsing.
    const response = await api.post(`/api/v1/correlation/evidence/intake/preview`, request, { timeout: 120_000 });
    return response.data;
  },

  async analyzeEvidence(request: EvidencePreviewRequest): Promise<EvidencePreviewResult> {
    const response = await api.post(`/api/v1/correlation/evidence/intake/analytics`, request, { timeout: 120_000 });
    return response.data;
  },

  async catalogEvidenceTables(intakeIds: string[]): Promise<EvidenceCatalogResponse> {
    const response = await api.post(`/api/v1/correlation/evidence/intake/catalog`, {
      intake_ids: intakeIds,
    });
    return response.data;
  },

  async startEvidenceJob(request: EvidencePreviewRequest): Promise<{ job_id: string; status: string; status_url: string }> {
    const response = await api.post(`/api/v1/correlation/evidence/intake/jobs`, request);
    return response.data;
  },

  async getEvidenceJob(jobId: string): Promise<EvidenceJobStatus> {
    // A CPU-heavy local job can temporarily occupy the API worker. Let the
    // status request wait rather than turning a completed background result
    // into a misleading 30-second browser timeout.
    const response = await api.get(`/api/v1/correlation/evidence/jobs/${jobId}`, { timeout: 120_000 });
    return response.data;
  },

  // Operations Lead answers are generated from a fresh deterministic evidence
  // result; the assistant changes presentation, never the underlying joins.
  async answerOperationsQuestion(
    request: EvidencePreviewRequest & { question: string }
  ): Promise<OperationsQuestionResponse> {
    const response = await api.post(`/api/v1/correlation/operations/answer`, request);
    return response.data;
  },

  async createOperationsBriefing(request: EvidencePreviewRequest): Promise<{
    overview: OperationsLeadAnswer;
    next_shift_checklist: OperationsLeadAnswer;
    evidence_scope?: Record<string, any>;
  }> {
    const response = await api.post(`/api/v1/correlation/operations/briefing`, request);
    return response.data;
  },

  async getOperationsQuestionTypes(): Promise<{ questions: Array<Record<string, any> | string> }> {
    const response = await api.get(`/api/v1/correlation/operations/question-types`);
    return response.data;
  },

  async answerEvidenceJobQuestion(jobId: string, question: string): Promise<OperationsQuestionResponse> {
    const response = await api.post(`/api/v1/correlation/operations/jobs/${jobId}/answer`, { question });
    return response.data;
  }
};
