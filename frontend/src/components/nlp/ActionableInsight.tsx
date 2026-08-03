import { useState } from 'react';
import {
  AlertTriangle, Check, CheckCircle2, Circle, Clock, Loader2, Phone, Send, X,
} from 'lucide-react';
import { Button } from '../ui/Button';
import {
  ActivationBlocker,
  ActivationPosting,
  InsightActivation,
  blockersFromError,
  insightActivationApi,
  messageFromError,
} from '../../api/insightActivation';

/**
 * One recommended action from an analysis session, with a way to actually do it (FS-406).
 *
 * WHAT THIS REPLACES. The pane drew each recommendation as a bullet with a green tick and
 * no control. The tick was the worst part: it reads as "done" for something that had not
 * been started, could not be started from here, and — via the "Auto-integrate" checkbox —
 * might have been silently attempted and failed with the screen looking identical.
 *
 * SO THE RULE HERE IS THAT NOTHING IS DRAWN AS COMPLETE WITHOUT EVIDENCE. Before activation
 * the icon is an empty circle. After activation each system of record gets its own line
 * with its own status, and a target with no integration shows the sentence to read out to a
 * person — the analog path, on screen, where a supervisor can use it. Confirm stays disabled
 * until the server agrees, and when the server refuses it says which system is still
 * outstanding.
 */

interface Props {
  /** The raw action object from the session message. Shape is loose by design upstream. */
  action: Record<string, any>;
  index: number;
  sessionId?: string;
  messageId?: string;
  /** Domain inferred for the message, used to route the fan-out. */
  domain?: string;
  /** An activation already known for this action, if the parent has fetched it. */
  existing?: InsightActivation;
  onActivated?: (activation: InsightActivation) => void;
}

function actionTitle(action: Record<string, any>): string {
  return (
    action.title || action.description || action.action || action.recommendation ||
    JSON.stringify(action)
  );
}

const STATUS_LABEL: Record<string, string> = {
  pending: 'queued',
  posted: 'posted',
  failed: 'failed',
  manual_required: 'needs a person',
  not_applicable: 'not routed here',
};

function PostingRow({
  posting,
  activationId,
  onUpdated,
}: {
  posting: ActivationPosting;
  activationId: string;
  onUpdated: (a: InsightActivation) => void;
}) {
  const [ref, setRef] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const needsAPerson = posting.status === 'manual_required' && !posting.acknowledgedAt;
  const evidenced = posting.status === 'posted' || Boolean(posting.acknowledgedAt);

  const acknowledge = async () => {
    setBusy(true);
    setError(null);
    try {
      onUpdated(
        await insightActivationApi.acknowledgePosting(activationId, posting.id, ref.trim() || undefined),
      );
    } catch (e) {
      setError(messageFromError(e) || 'could not record that — the posting is unchanged');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border border-gray-200 bg-white px-2.5 py-2">
      <div className="flex items-center gap-2 text-[11px]">
        {evidenced ? (
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-600" />
        ) : posting.status === 'failed' ? (
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-red-600" />
        ) : needsAPerson ? (
          <Phone className="h-3.5 w-3.5 shrink-0 text-amber-600" />
        ) : (
          <Clock className="h-3.5 w-3.5 shrink-0 text-gray-400" />
        )}
        <span className="font-medium capitalize text-gray-900">{posting.targetSystem}</span>
        <span className="text-gray-500">{STATUS_LABEL[posting.status] ?? posting.status}</span>
        {/* The reference IS the evidence. Shown, so a reader can check the claim. */}
        {posting.externalRef && (
          <span className="ml-auto font-mono text-[10px] text-gray-600">{posting.externalRef}</span>
        )}
        {!posting.externalRef && posting.acknowledgedAt && (
          <span className="ml-auto text-[10px] text-gray-500">confirmed by a person</span>
        )}
      </div>

      {posting.lastError && (
        <p className="mt-1 text-[10px] text-red-700">{posting.lastError}</p>
      )}

      {needsAPerson && (
        <div className="mt-1.5 space-y-1.5">
          {/* The analog path, on screen. This is the line a supervisor reads out. */}
          {posting.instruction && (
            <p className="rounded bg-amber-50 px-2 py-1.5 text-[11px] leading-snug text-amber-900">
              {posting.instruction}
            </p>
          )}
          <div className="flex items-center gap-1.5">
            <input
              value={ref}
              onChange={(e) => setRef(e.target.value)}
              placeholder="reference they gave you (optional)"
              className="min-w-0 flex-1 rounded border border-gray-300 px-2 py-1 text-[11px]"
            />
            <Button size="sm" variant="outline" onClick={acknowledge} disabled={busy}>
              {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : 'I told them'}
            </Button>
          </div>
          {/* Said plainly, because the two outcomes are genuinely different and the operator
              is the one choosing between them. */}
          <p className="text-[10px] text-gray-500">
            With a reference this counts as posted. Without one it records that you passed it
            on, and the system still shows it as needing an entry.
          </p>
          {error && <p className="text-[10px] text-red-700">{error}</p>}
        </div>
      )}
    </div>
  );
}

export function ActionableInsight({
  action,
  index,
  sessionId,
  messageId,
  domain,
  existing,
  onActivated,
}: Props) {
  const [activation, setActivation] = useState<InsightActivation | null>(existing ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blockers, setBlockers] = useState<ActivationBlocker[] | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');

  const title = actionTitle(action);

  const update = (next: InsightActivation) => {
    setActivation(next);
    setBlockers(null);
    onActivated?.(next);
  };

  const activate = async () => {
    setBusy(true);
    setError(null);
    try {
      update(
        await insightActivationApi.activate({
          title,
          description: action.description && action.description !== title ? action.description : undefined,
          domain: action.domain || domain,
          priority: action.priority || 'medium',
          sessionId,
          messageId,
          actionIndex: index,
        }),
      );
    } catch (e) {
      setError(messageFromError(e) || 'could not activate this — nothing was created');
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!activation) return;
    setBusy(true);
    setError(null);
    try {
      update(await insightActivationApi.confirm(activation.id));
    } catch (e) {
      // A 409 is the server refusing, WITH the list of what is outstanding. Showing that
      // list is the whole point — "could not confirm" on its own is not actionable.
      const found = blockersFromError(e);
      if (found) {
        setBlockers(found);
        setActivation(await insightActivationApi.get(activation.id));
      } else {
        setError(messageFromError(e) || 'could not confirm this');
      }
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    if (!activation || !reason.trim()) return;
    setBusy(true);
    setError(null);
    try {
      update(await insightActivationApi.reject(activation.id, reason.trim()));
      setRejecting(false);
    } catch (e) {
      setError(messageFromError(e) || 'could not record that');
    } finally {
      setBusy(false);
    }
  };

  // Not activated yet: an EMPTY circle. The old green tick claimed a completed action for
  // something that had not been started.
  if (!activation) {
    return (
      <li className="flex items-start gap-2">
        <Circle className="mt-0.5 h-3 w-3 shrink-0 text-gray-400" />
        <span className="min-w-0 flex-1">{title}</span>
        <Button
          size="sm"
          variant="outline"
          className="h-6 shrink-0 px-2 text-[11px]"
          onClick={activate}
          disabled={busy}
        >
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="mr-1 h-3 w-3" />}
          Activate
        </Button>
        {error && <span className="w-full text-[10px] text-red-700">{error}</span>}
      </li>
    );
  }

  const confirmed = activation.status === 'confirmed';
  const rejected = activation.status === 'rejected';

  return (
    <li className="rounded-md border border-gray-200 bg-gray-50 p-2.5">
      <div className="flex items-start gap-2">
        {confirmed ? (
          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-600" />
        ) : rejected ? (
          <X className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gray-400" />
        ) : (
          <Clock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-blue-600" />
        )}
        <div className="min-w-0 flex-1">
          <p className={`text-xs ${rejected ? 'text-gray-500 line-through' : 'text-gray-900'}`}>
            {title}
          </p>
          {activation.alreadyExisted && (
            <p className="text-[10px] text-gray-500">
              already activated — this did not dispatch it a second time
            </p>
          )}
        </div>
      </div>

      {rejected ? (
        <p className="mt-1.5 pl-5 text-[11px] text-gray-600">
          Declined: {activation.rejectionReason}
        </p>
      ) : (
        <div className="mt-2 space-y-2 pl-5">
          {/* The Kanban task. Or, if none, WHY none — the old path returned null from three
              places with no way to tell them apart. */}
          {activation.task ? (
            <p className="text-[11px] text-gray-700">
              Task <span className="font-mono">{activation.task.taskType}</span> on the board —{' '}
              <span className="font-medium">{activation.task.status}</span>
            </p>
          ) : (
            <p className="text-[11px] text-amber-800">
              No board task was created: {activation.taskBlockedReason ?? 'reason not reported'}
            </p>
          )}

          <div className="space-y-1.5">
            {activation.postings.map((posting) => (
              <PostingRow
                key={posting.id}
                posting={posting}
                activationId={activation.id}
                onUpdated={update}
              />
            ))}
          </div>

          {blockers && blockers.length > 0 && (
            <div className="rounded border border-amber-300 bg-amber-50 px-2 py-1.5">
              <p className="text-[10px] font-medium text-amber-900">Not confirmed yet:</p>
              <ul className="mt-0.5 space-y-0.5">
                {blockers.map((blocker, i) => (
                  <li key={i} className="text-[10px] text-amber-900">
                    {blocker.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {confirmed ? (
            <p className="text-[11px] text-green-700">
              Confirmed — every system of record above carries evidence.
            </p>
          ) : rejecting ? (
            <div className="flex items-center gap-1.5">
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="why not?"
                className="min-w-0 flex-1 rounded border border-gray-300 px-2 py-1 text-[11px]"
              />
              <Button size="sm" variant="outline" onClick={reject} disabled={busy || !reason.trim()}>
                Decline
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setRejecting(false)}>
                Cancel
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-1.5">
              <Button
                size="sm"
                variant="outline"
                className="h-6 px-2 text-[11px]"
                onClick={confirm}
                disabled={busy}
                // NOT disabled on `readyToConfirm`. The server is the authority, and a button
                // the user can press and be told why gives a better answer than one that is
                // greyed out for a reason nobody explains.
              >
                {busy ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Check className="mr-1 h-3 w-3" />
                )}
                Confirm done
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-6 px-2 text-[11px]"
                onClick={() => setRejecting(true)}
              >
                Decline
              </Button>
              {!activation.readyToConfirm && (
                <span className="text-[10px] text-gray-500">
                  {activation.blockers.length} thing
                  {activation.blockers.length === 1 ? '' : 's'} outstanding
                </span>
              )}
            </div>
          )}

          {error && <p className="text-[10px] text-red-700">{error}</p>}
        </div>
      )}
    </li>
  );
}

export default ActionableInsight;
