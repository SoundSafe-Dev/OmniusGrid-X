import { FC, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Check, CheckCircle2, Clock, Loader2, Phone, X } from 'lucide-react'
import {
  ActivationPosting,
  InsightActivation,
  blockersFromError,
  insightActivationApi,
  messageFromError,
} from '../api/insightActivation'
import { Button } from '../components/ui'

/**
 * Everything activated from a correlation session, in one place (FS-425).
 *
 * WHAT WAS MISSING. `GET /insights/activations` and `/activations/{id}` were served by no
 * screen at all. An operator who activated a recommendation could see it only inline, in
 * that message, in that session — so "what did we commit to, and what is still
 * outstanding?" had no answer anywhere in the product. The API had the answer the whole
 * time.
 *
 * THIS IS A WORKLIST, NOT A LOG. It opens on `issued` — the ones still needing something —
 * and leads with the two things that need a person: a Kanban task that is not finished, and
 * a posting no system of record has acknowledged. Confirmed and rejected activations are a
 * filter away rather than mixed in, because a list where the finished outnumber the
 * outstanding stops being read.
 *
 * NOTHING HERE CLAIMS COMPLETION IT CANNOT SHOW. Each row renders the per-system postings
 * with their own statuses; `ready_to_confirm` comes from the server, and Confirm is left
 * enabled so a press returns the reasons rather than a greyed-out control that explains
 * nothing.
 */

const STATUS_LABEL: Record<string, string> = {
  pending: 'queued',
  posted: 'posted',
  failed: 'failed',
  manual_required: 'needs a person',
  not_applicable: 'not routed here',
}

const FILTERS = [
  { id: 'issued', label: 'Outstanding' },
  { id: 'confirmed', label: 'Confirmed' },
  { id: 'rejected', label: 'Declined' },
  { id: '', label: 'All' },
] as const

const PostingRow: FC<{
  posting: ActivationPosting
  activationId: string
  onUpdated: (a: InsightActivation) => void
}> = ({ posting, activationId, onUpdated }) => {
  const [reference, setReference] = useState('')
  const acknowledge = useMutation({
    mutationFn: () =>
      insightActivationApi.acknowledgePosting(activationId, posting.id, reference.trim() || undefined),
    onSuccess: onUpdated,
  })

  const needsAPerson = posting.status === 'manual_required' && !posting.acknowledgedAt
  const evidenced = posting.status === 'posted' || Boolean(posting.acknowledgedAt)

  return (
    <div className="rounded border border-opsgrid-border bg-opsgrid-bg px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {evidenced ? (
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-status-running" />
        ) : posting.status === 'failed' ? (
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-status-alarm" />
        ) : needsAPerson ? (
          <Phone className="h-3.5 w-3.5 shrink-0 text-status-warning" />
        ) : (
          <Clock className="h-3.5 w-3.5 shrink-0 text-opsgrid-text-secondary" />
        )}
        <span className="font-medium capitalize text-opsgrid-text">{posting.targetSystem}</span>
        <span className="text-opsgrid-text-secondary">
          {STATUS_LABEL[posting.status] ?? posting.status}
        </span>
        {/* The reference IS the evidence, so it is shown rather than summarised. */}
        {posting.externalRef && (
          <span className="ml-auto font-mono text-[11px] text-opsgrid-text-secondary">
            {posting.externalRef}
          </span>
        )}
        {!posting.externalRef && posting.acknowledgedAt && (
          <span className="ml-auto text-[11px] text-opsgrid-text-secondary">
            confirmed by a person
          </span>
        )}
      </div>

      {posting.lastError && (
        <p className="mt-1 text-[11px] text-status-alarm">{posting.lastError}</p>
      )}

      {needsAPerson && (
        <div className="mt-2 space-y-1.5">
          {/* The analog path, on screen. This is the sentence somebody reads out. */}
          {posting.instruction && (
            <p className="rounded border border-status-warning/50 bg-status-warning/10 px-2 py-1.5 text-xs leading-snug text-opsgrid-text">
              {posting.instruction}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <input
              aria-label={`Reference for ${posting.targetSystem}`}
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="reference they gave you (optional)"
              className="min-w-0 flex-1 rounded border border-opsgrid-border bg-opsgrid-bg px-2 py-1 text-xs text-opsgrid-text placeholder:text-opsgrid-text-secondary"
            />
            <Button size="sm" variant="outline" onClick={() => acknowledge.mutate()} disabled={acknowledge.isPending}>
              {acknowledge.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : 'I told them'}
            </Button>
          </div>
          {acknowledge.isError && (
            <p className="text-[11px] text-status-alarm" role="alert">
              Not recorded — this posting is unchanged and still needs passing on.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

const ActivationCard: FC<{ activation: InsightActivation }> = ({ activation }) => {
  const queryClient = useQueryClient()
  const [blockers, setBlockers] = useState<string[] | null>(null)
  const [reason, setReason] = useState('')
  const [rejecting, setRejecting] = useState(false)

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['insight-activations'] })

  const confirm = useMutation({
    mutationFn: () => insightActivationApi.confirm(activation.id),
    onSuccess: () => { setBlockers(null); refresh() },
    onError: (error) => {
      // A 409 is the server refusing WITH its reasons. Showing them is the point — the
      // alternative is a failed button and an operator with nowhere to go.
      const found = blockersFromError(error)
      setBlockers(found ? found.map((b) => b.reason) : [messageFromError(error) ?? 'could not confirm'])
    },
  })

  const reject = useMutation({
    mutationFn: () => insightActivationApi.reject(activation.id, reason.trim()),
    onSuccess: () => { setRejecting(false); refresh() },
  })

  const confirmed = activation.status === 'confirmed'
  const rejected = activation.status === 'rejected'

  return (
    <article className="rounded-lg border border-opsgrid-border bg-opsgrid-panel p-4">
      <header className="flex items-start gap-3">
        {confirmed ? (
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-status-running" />
        ) : rejected ? (
          <X className="mt-0.5 h-4 w-4 shrink-0 text-opsgrid-text-secondary" />
        ) : (
          <Clock className="mt-0.5 h-4 w-4 shrink-0 text-opsgrid-primary" />
        )}
        <div className="min-w-0 flex-1">
          <h2 className={`text-sm font-medium ${rejected ? 'text-opsgrid-text-secondary line-through' : 'text-opsgrid-text'}`}>
            {activation.title}
          </h2>
          <p className="mt-0.5 text-xs text-opsgrid-text-secondary">
            {activation.domain ?? 'no domain'} · {activation.priority}
            {activation.issuedAt ? ` · activated ${new Date(activation.issuedAt).toLocaleString()}` : ''}
          </p>
        </div>
      </header>

      {rejected ? (
        <p className="mt-2 pl-7 text-xs text-opsgrid-text-secondary">
          Declined: {activation.rejectionReason}
        </p>
      ) : (
        <div className="mt-3 space-y-2 pl-7">
          {activation.task ? (
            <p className="text-xs text-opsgrid-text-secondary">
              Task <span className="font-mono">{activation.task.taskType}</span> —{' '}
              <span className="font-medium text-opsgrid-text">{activation.task.status}</span>
            </p>
          ) : (
            <p className="text-xs text-status-warning">
              No board task: {activation.taskBlockedReason ?? 'reason not reported'}
            </p>
          )}

          <div className="space-y-1.5">
            {activation.postings.map((posting) => (
              <PostingRow
                key={posting.id}
                posting={posting}
                activationId={activation.id}
                onUpdated={refresh}
              />
            ))}
          </div>

          {blockers && blockers.length > 0 && (
            <div className="rounded border border-status-warning/50 bg-status-warning/10 px-2 py-1.5" role="alert">
              <p className="text-[11px] font-medium text-status-warning">Not confirmed yet:</p>
              <ul className="mt-0.5 space-y-0.5">
                {blockers.map((b, i) => (
                  <li key={i} className="text-[11px] text-opsgrid-text">{b}</li>
                ))}
              </ul>
            </div>
          )}

          {confirmed ? (
            <p className="text-xs text-status-running">
              Confirmed — every system of record above carries evidence.
            </p>
          ) : rejecting ? (
            <div className="flex flex-wrap items-center gap-2">
              <input
                aria-label="Why are you declining this?"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="why not?"
                className="min-w-0 flex-1 rounded border border-opsgrid-border bg-opsgrid-bg px-2 py-1 text-xs text-opsgrid-text placeholder:text-opsgrid-text-secondary"
              />
              <Button size="sm" variant="outline" onClick={() => reject.mutate()} disabled={reject.isPending || !reason.trim()}>
                Decline
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setRejecting(false)}>Cancel</Button>
              {reject.isError && (
                <p className="w-full text-[11px] text-status-alarm" role="alert">
                  Not recorded — this activation is unchanged.
                </p>
              )}
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" onClick={() => confirm.mutate()} disabled={confirm.isPending}>
                {confirm.isPending ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Check className="mr-1 h-3 w-3" />}
                Confirm done
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setRejecting(true)}>Decline</Button>
              {!activation.readyToConfirm && activation.blockers.length > 0 && (
                <span className="text-[11px] text-opsgrid-text-secondary">
                  {activation.blockers.length} thing{activation.blockers.length === 1 ? '' : 's'} outstanding
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </article>
  )
}

const Activations: FC = () => {
  const [status, setStatus] = useState<string>('issued')
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['insight-activations', status],
    queryFn: () => insightActivationApi.list({ status: status || undefined, limit: 100 }),
  })

  return (
    <div className="space-y-4 p-1">
      <header>
        <h1 className="text-xl font-semibold text-opsgrid-text">Activated insights</h1>
        <p className="mt-1 text-sm text-opsgrid-text-secondary">
          Recommendations someone chose to act on, and what each one still needs. A target with
          no integration is handed to a person, with the words to use.
        </p>
      </header>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by status">
        {FILTERS.map((f) => (
          <button
            key={f.id || 'all'}
            type="button"
            aria-pressed={status === f.id}
            onClick={() => setStatus(f.id)}
            className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
              status === f.id
                ? 'bg-opsgrid-primary font-medium text-opsgrid-bg'
                : 'bg-opsgrid-panel text-opsgrid-text-secondary hover:bg-opsgrid-hover'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <p className="text-sm text-opsgrid-text-secondary">Loading…</p>
      ) : isError ? (
        // An empty list here would read as "nothing outstanding", which is the opposite of
        // what a failed load means.
        <div className="flex items-center gap-3" role="alert">
          <p className="text-sm text-status-alarm">
            Couldn’t load activations — this is a loading failure, not an empty worklist.
          </p>
          <Button size="sm" variant="outline" onClick={() => refetch()}>Retry</Button>
        </div>
      ) : data!.items.length === 0 ? (
        <p className="text-sm text-opsgrid-text-secondary">
          {status === 'issued'
            ? 'Nothing outstanding. Activate a recommendation from a correlation session and it appears here.'
            : 'Nothing in this state.'}
        </p>
      ) : (
        <>
          <p className="text-xs text-opsgrid-text-secondary">
            {data!.total} total
            {data!.truncated ? ` — showing the first ${data!.items.length}` : ''}
          </p>
          <div className="space-y-3">
            {data!.items.map((activation) => (
              <ActivationCard key={activation.id} activation={activation} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export default Activations
