import { FC, Fragment, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  ExternalLink,
  FileText,
  ClipboardList,
  Search,
  ShieldCheck,
} from 'lucide-react';
import { Badge, Button, Card } from '../../components/ui';
import { ragApi } from '../../api';
import { handleApiError } from '../../api/client';
import type { Citation, RagAnswer, SourceDoc } from '../../api/rag';

/**
 * Compliance Assistant — grounded Q&A over the organization's policy corpus.
 *
 * Deliberately NOT a chat. There is no message history, no session, and no data
 * source to attach: that is the Correlation AI surface, which answers a different
 * kind of question. Here a reader asks one thing about policy, OSHA, or the
 * collective agreement, and gets an answer that is only ever built from documents
 * they can open, plus the forms the answer implies they need to file.
 */

const SUGGESTIONS = [
  'What PPE does our lockout/tagout procedure require?',
  'How much notice does the collective agreement require for a shift change?',
  'What do I file to request FMLA leave?',
  'What are the cold chain temperature limits for finished goods?',
];

/** '(page 4 · Energy Isolation)' from whatever locator keys the chunk carried. */
const sourceLabel = (source: Record<string, unknown>): string => {
  const parts: string[] = [];
  if (source.page != null) parts.push(`page ${source.page}`);
  if (source.heading) parts.push(String(source.heading));
  else if (source.sectionId != null) parts.push(`section ${source.sectionId}`);
  return parts.join(' · ');
};

const docKey = (doc: { docId: string | null; s3Key: string | null; filename: string | null }) =>
  doc.docId ?? doc.s3Key ?? doc.filename ?? '';

/**
 * Render `[1]`, `[2]` markers as buttons that jump to the citation.
 *
 * A citation the reader cannot get to is only marginally better than no citation,
 * and the markers are the only affordance connecting a sentence to its source.
 */
const AnswerText: FC<{ text: string; onJump: (n: number) => void }> = ({ text, onJump }) => {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="text-opsgrid-text whitespace-pre-wrap leading-relaxed">
      {parts.map((part, i) => {
        const match = /^\[(\d+)\]$/.exec(part);
        if (!match) return <Fragment key={i}>{part}</Fragment>;
        const n = Number(match[1]);
        return (
          <button
            key={i}
            type="button"
            onClick={() => onJump(n)}
            aria-label={`Jump to source ${n}`}
            className="mx-0.5 px-1 rounded bg-opsgrid-primary/20 text-opsgrid-primary text-xs align-super hover:bg-opsgrid-primary/40"
          >
            {n}
          </button>
        );
      })}
    </p>
  );
};

export const ComplianceAssistant: FC = () => {
  const [draft, setDraft] = useState('');
  const [submitted, setSubmitted] = useState<string | null>(null);
  const citationRefs = useRef<Record<number, HTMLDivElement | null>>({});

  const { data, isFetching, isError, error } = useQuery({
    queryKey: ['compliance-query', submitted],
    queryFn: () => ragApi.query({ query: submitted! }),
    enabled: !!submitted,
    // A policy answer is not a live metric; re-asking is an explicit act.
    refetchInterval: false,
    refetchOnWindowFocus: false,
  });

  const link = useMutation({
    mutationFn: (s3Key: string) => ragApi.documentLink(s3Key),
    onSuccess: (result) => window.open(result.url, '_blank', 'noopener,noreferrer'),
  });

  const ask = (question: string) => {
    const trimmed = question.trim();
    if (!trimmed) return;
    setDraft(trimmed);
    setSubmitted(trimmed);
    link.reset();
  };

  const jumpToCitation = (n: number) => {
    citationRefs.current[n]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  const { forms, cited, alsoRelevant } = useMemo(() => {
    const sources = data?.sources ?? [];
    return {
      forms: sources.filter((s) => s.isForm),
      cited: sources.filter((s) => s.cited && !s.isForm),
      alsoRelevant: sources.filter((s) => !s.cited && !s.isForm),
    };
  }, [data]);

  // 503 is a routine outcome here, not a bug: the RAG router is mounted with
  // `unavailable_responses` and retrieval-only / storage-only deployments are
  // supported by design. Saying which thing is down is more useful than "failed".
  const failureMessage = (() => {
    if (!isError) return null;
    const { status, message } = handleApiError(error);
    if (status === 503) {
      return 'The assistant’s retrieval services are unavailable right now. Your documents are safe — this is a service outage, not an empty library.';
    }
    return message || 'The question could not be answered. Try again.';
  })();

  const DocumentRow: FC<{ doc: SourceDoc }> = ({ doc }) => (
    <div className="flex items-center justify-between gap-3 py-2 border-b border-opsgrid-border last:border-0">
      <div className="flex items-center gap-2 min-w-0">
        {doc.isForm ? (
          <ClipboardList size={16} className="text-opsgrid-primary shrink-0" />
        ) : (
          <FileText size={16} className="text-opsgrid-text-secondary shrink-0" />
        )}
        <span className="text-sm text-opsgrid-text truncate">
          {doc.filename ?? 'Untitled document'}
        </span>
        {doc.isForm && <Badge variant="info">Form</Badge>}
        {/* No score on an uncited document: it has an RRF fusion score, not a
            cross-encoder one, and showing them together would read as a ranking
            that does not exist. */}
        {doc.score != null && (
          <span className="text-xs text-opsgrid-text-secondary shrink-0">
            {(doc.score * 100).toFixed(0)}% match
          </span>
        )}
      </div>
      {doc.s3Key && (
        <Button
          variant="secondary"
          size="sm"
          loading={link.isPending && link.variables === doc.s3Key}
          onClick={() => link.mutate(doc.s3Key!)}
        >
          <ExternalLink size={14} className="mr-1" />
          Open
        </Button>
      )}
    </div>
  );

  return (
    <div className="space-y-6">
      <Card
        title="Compliance Assistant"
        subtitle="Answers drawn from your policy library — SOPs, OSHA standards, collective agreements, and corporate policy"
      >
        <div className="flex gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && ask(draft)}
            placeholder="Ask about a policy, rule, or requirement…"
            aria-label="Compliance question"
            className="flex-1 px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-opsgrid-text placeholder:text-opsgrid-text-secondary"
          />
          <Button
            variant="primary"
            loading={isFetching}
            disabled={!draft.trim()}
            onClick={() => ask(draft)}
          >
            <Search size={16} className="mr-1" />
            Ask
          </Button>
        </div>
        <div className="flex flex-wrap gap-2 mt-3">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => ask(s)}
              className="px-3 py-1 text-xs rounded-full border border-opsgrid-border text-opsgrid-text-secondary hover:border-opsgrid-primary hover:text-opsgrid-primary transition-colors"
            >
              {s}
            </button>
          ))}
        </div>
      </Card>

      {failureMessage && (
        <Card className="p-4">
          <p className="text-status-alarm text-sm flex items-start gap-2" role="alert">
            <AlertTriangle size={16} className="shrink-0 mt-0.5" />
            {failureMessage}
          </p>
        </Card>
      )}

      {link.isError && (
        <Card className="p-4">
          <p className="text-status-alarm text-sm" role="alert">
            Couldn’t open that document — {handleApiError(link.error).message}
          </p>
        </Card>
      )}

      {data && !isError && (
        <>
          <Card title="Answer">
            {/* answer === null with citations present is a NORMAL outcome: the
                retrieval half works and the generator is unavailable or was not
                asked. The passages are still the answer, just unsummarised. */}
            {data.answer === null && data.citations.length > 0 && (
              <p className="text-sm text-opsgrid-text-secondary mb-3">
                Answer generation is unavailable. These are the most relevant passages
                from your library.
              </p>
            )}
            {data.answer !== null && (
              <AnswerText text={data.answer} onJump={jumpToCitation} />
            )}
            {!data.usedContext && (
              <p className="text-opsgrid-text-secondary text-sm mt-2">
                Nothing in your document library matches that question. If the policy
                exists but hasn’t been loaded yet, it won’t be found here.
              </p>
            )}
          </Card>

          {data.citations.length > 0 && (
            <Card
              title="Cited passages"
              subtitle="The exact text this answer is built on"
            >
              <div className="space-y-3">
                {data.citations.map((c: Citation) => (
                  <div
                    key={c.n}
                    ref={(el) => {
                      citationRefs.current[c.n] = el;
                    }}
                    className="border border-opsgrid-border rounded-lg p-3"
                  >
                    <div className="flex items-start justify-between gap-3 mb-1">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="px-1.5 rounded bg-opsgrid-primary/20 text-opsgrid-primary text-xs shrink-0">
                          {c.n}
                        </span>
                        <span className="text-sm font-medium text-opsgrid-text truncate">
                          {c.filename ?? 'Untitled document'}
                        </span>
                        <span className="text-xs text-opsgrid-text-secondary shrink-0">
                          {sourceLabel(c.source)}
                        </span>
                      </div>
                      {c.s3Key && (
                        <Button
                          variant="secondary"
                          size="sm"
                          loading={link.isPending && link.variables === c.s3Key}
                          onClick={() => link.mutate(c.s3Key!)}
                        >
                          <ExternalLink size={14} className="mr-1" />
                          Open
                        </Button>
                      )}
                    </div>
                    <p className="text-sm text-opsgrid-text-secondary">{c.snippet}</p>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {forms.length > 0 && (
            <Card
              title="Forms you may need"
              subtitle="Documents this answer implies you have to complete and return"
            >
              {forms.map((doc) => (
                <DocumentRow key={docKey(doc)} doc={doc} />
              ))}
            </Card>
          )}

          {(cited.length > 0 || alsoRelevant.length > 0) && (
            <Card title="Source documents">
              {cited.length > 0 && (
                <>
                  <p className="text-xs uppercase tracking-wider text-opsgrid-text-secondary mb-1">
                    Used in this answer
                  </p>
                  {cited.map((doc) => (
                    <DocumentRow key={docKey(doc)} doc={doc} />
                  ))}
                </>
              )}
              {alsoRelevant.length > 0 && (
                <>
                  <p className="text-xs uppercase tracking-wider text-opsgrid-text-secondary mt-4 mb-1">
                    Also relevant
                  </p>
                  {alsoRelevant.map((doc) => (
                    <DocumentRow key={docKey(doc)} doc={doc} />
                  ))}
                </>
              )}
            </Card>
          )}
        </>
      )}

      {!submitted && !isError && (
        <Card className="p-8">
          <div className="flex flex-col items-center text-opsgrid-text-secondary text-center">
            <ShieldCheck className="w-10 h-10 mb-3" />
            <p className="max-w-md">
              Ask a question about policy, safety rules, OSHA standards, or your
              collective agreement. Every answer cites the documents it came from, and
              links to the originals.
            </p>
          </div>
        </Card>
      )}
    </div>
  );
};

export type { RagAnswer };
