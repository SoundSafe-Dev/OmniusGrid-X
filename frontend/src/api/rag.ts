import { api } from './client';
import { USE_MOCK } from './mockMode';
import { registerTransform } from './transformRegistry';

/**
 * Compliance Assistant — the frontend half of the RAG pipeline (backend: Hudson
 * Treinen's `app/api/rag.py`, SeaweedFS + Qdrant + BGE-M3/reranker + an
 * OpenAI-compatible generator).
 *
 * Casing is handled by the axios seam — TS speaks camelCase, the wire speaks
 * snake_case. `/api/v1/rag` is not on the never-register list, so opt in. NOTE
 * that `Citation.source` is a free-form bag of chunk metadata and gets camelized
 * too: the wire's `section_id` / `source_type` arrive here as `sectionId` /
 * `sourceType`.
 *
 * Only queries and document links live here. Ingestion is deliberately absent —
 * documents enter the corpus through the AI Correlation intake flow, and this
 * page reads the corpus rather than loading it.
 */
registerTransform('/api/v1/rag');

/** A passage the answer is built on. `n` matches the `[n]` markers in `answer`. */
export interface Citation {
  n: number;
  docId: string | null;
  filename: string | null;
  /** Presign this to open the original. Absent on chunks indexed without a blob. */
  s3Key: string | null;
  /** page / sectionId / heading / level / sourceType / chunkId — all optional. */
  source: Record<string, unknown>;
  /** Cross-encoder relevance from the reranker. */
  score: number;
  snippet: string;
}

/**
 * A whole document behind an answer, as opposed to one passage of it.
 *
 * Citations are chunks — three of them can be three pages of one PDF — and a form
 * that matched the question but placed below the rerank cut never appears among
 * them at all. This is the document-level roll-up of the full candidate set.
 */
export interface SourceDoc {
  docId: string | null;
  filename: string | null;
  s3Key: string | null;
  /** Did a passage of it reach the answer's context? */
  cited: boolean;
  /**
   * ONLY present when `cited`. Cited documents carry a cross-encoder score; the
   * rest carry an RRF fusion score, and the two are not on one scale — so the
   * server sends null rather than a number that would render as a false ranking.
   * Do not coalesce this to 0.
   */
  score: number | null;
  /** Filename looks like something you fill in and return, not something you read. */
  isForm: boolean;
}

export interface RagAnswer {
  /** null when generation was skipped or the LLM is unavailable — NOT an error. */
  answer: string | null;
  citations: Citation[];
  /** Whether any passage was retrieved at all. False = nothing in the corpus matched. */
  usedContext: boolean;
  /** Whether the LLM actually produced the answer. */
  generated: boolean;
  sources: SourceDoc[];
}

export interface RagQueryRequest {
  query: string;
  topN?: number;
  generate?: boolean;
}

export interface DocumentLinkResponse {
  url: string;
  expiresIn: number;
}

export interface RagHealth {
  inference: unknown;
  vectorStore: unknown;
  llm: unknown;
  documentStore: unknown;
}

const MOCK_DELAY = 400;
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const mockAnswer = (query: string): RagAnswer => ({
  answer:
    `Before any maintenance on the press line, energy sources must be isolated and ` +
    `each authorized employee must apply their own lock and tag [1]. Locks may only ` +
    `be removed by the person who applied them [1]. The collective agreement adds ` +
    `that a steward is notified before a lockout that stops a running line [2].` +
    `\n\n(Demo response for: "${query}")`,
  citations: [
    {
      n: 1,
      docId: 'doc-loto',
      filename: 'lockout-tagout-sop.pdf',
      s3Key: 'demo-org/doc-loto/lockout-tagout-sop.pdf',
      source: { page: 4, heading: 'Energy Isolation' },
      score: 0.94,
      snippet:
        'Each authorized employee shall affix a personal lockout device to each energy ' +
        'isolating device. Removal is permitted only by the employee who applied it.',
    },
    {
      n: 2,
      docId: 'doc-cba',
      filename: 'local-49-collective-agreement.docx',
      s3Key: 'demo-org/doc-cba/local-49-collective-agreement.docx',
      source: { sectionId: '7.3', heading: 'Safety Stoppages' },
      score: 0.81,
      snippet:
        'Article 7.3 — The Employer shall notify the steward on duty prior to any ' +
        'lockout which interrupts a running production line.',
    },
  ],
  usedContext: true,
  generated: true,
  sources: [
    {
      docId: 'doc-loto',
      filename: 'lockout-tagout-sop.pdf',
      s3Key: 'demo-org/doc-loto/lockout-tagout-sop.pdf',
      cited: true,
      score: 0.94,
      isForm: false,
    },
    {
      docId: 'doc-cba',
      filename: 'local-49-collective-agreement.docx',
      s3Key: 'demo-org/doc-cba/local-49-collective-agreement.docx',
      cited: true,
      score: 0.81,
      isForm: false,
    },
    {
      docId: 'doc-permit',
      filename: 'energy-isolation-permit.pdf',
      s3Key: 'demo-org/doc-permit/energy-isolation-permit.pdf',
      cited: false,
      score: null,
      isForm: true,
    },
    {
      docId: 'doc-osha',
      filename: 'osha-1910-147.pdf',
      s3Key: 'demo-org/doc-osha/osha-1910-147.pdf',
      cited: false,
      score: null,
      isForm: false,
    },
  ],
});

export const ragApi = {
  /**
   * Ask a compliance question. The answer is grounded in the document corpus and
   * cites it; nothing else is cited.
   *
   * The long timeout matches the other LLM-backed call in this codebase
   * (analysisSessions.sessionChat): retrieval is fast, generation is not, and the
   * default 30s cuts off a cold model mid-answer.
   */
  async query(request: RagQueryRequest): Promise<RagAnswer> {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockAnswer(request.query);
    }
    const response = await api.post<RagAnswer>('/api/v1/rag/query', request, {
      timeout: 180000,
    });
    return response.data;
  },

  /**
   * Time-limited URL that opens a cited document.
   *
   * POST so the key stays out of URLs and access logs. The backend rejects any key
   * outside the caller's organization prefix, which is what makes the resulting
   * link access-permitted rather than merely unguessable.
   */
  async documentLink(s3Key: string): Promise<DocumentLinkResponse> {
    if (USE_MOCK) {
      await delay(150);
      return { url: `https://example.invalid/demo/${encodeURIComponent(s3Key)}`, expiresIn: 3600 };
    }
    const response = await api.post<DocumentLinkResponse>('/api/v1/rag/documents/link', {
      s3Key,
    });
    return response.data;
  },

  async health(): Promise<RagHealth> {
    const response = await api.get<RagHealth>('/api/v1/rag/health');
    return response.data;
  },
};
