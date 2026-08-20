import { FC, ReactNode } from 'react';
import { cn } from '../../utils';

/**
 * A failure the user can do something about.
 *
 * MEASURED BEFORE IT WAS WRITTEN: 68 failure messages across the frontend, and **65 of them
 * were dead ends** — a sentence in red and nothing else. `<p>Failed to load alarms.</p>`.
 *
 * The cost of a dead end is not the missing button. It is that the only recovery left is a
 * full page reload, which throws away filters, the selected time range, scroll position, and
 * anything half-typed elsewhere on the page. A transient 502 on one of six panels therefore
 * costs the operator their whole working state, and the fix — retry this one query — was
 * already sitting in react-query as `refetch`.
 *
 * WHY A COMPONENT RATHER THAN A CONVENTION. The 65 were written by many hands and are worded
 * 65 ways ("Failed to load", "Unable to load", "Error loading", "Could not load"), which is
 * its own friction: an operator learns one shape of failure per page. One component means one
 * shape, one recovery, and a `role="alert"` that is not optional — colour was the only cue in
 * most of them, so a screen-reader user reached the failure and heard nothing.
 *
 * `onRetry` is optional and its absence is deliberate rather than lazy: a few failures are
 * genuinely terminal (a deleted record, a permission the session will never have), and
 * offering a retry that cannot work is worse than offering none. Those pass `onRetry`
 * undefined and get the message without the button.
 */
interface ErrorStateProps {
  /** What failed, in the user's terms. "Alarms could not be loaded", not "500". */
  message: string;
  /** Optional detail — a server-supplied reason, an id to quote to support. */
  detail?: string | null;
  /** react-query's `refetch`. Omit only when a retry genuinely cannot help. */
  onRetry?: () => void;
  /** True while the retry is in flight, so the control cannot be hammered. */
  retrying?: boolean;
  /** `inline` for a panel inside a page; `block` for a whole-page failure. */
  variant?: 'inline' | 'block';
  className?: string;
  children?: ReactNode;
}

export const ErrorState: FC<ErrorStateProps> = ({
  message,
  detail = null,
  onRetry,
  retrying = false,
  variant = 'inline',
  className,
  children,
}) => (
  <div
    // `role="alert"` announces it without the user going looking. `aria-busy` while retrying
    // is what stops a screen reader re-announcing the same failure on every render.
    role="alert"
    aria-busy={retrying || undefined}
    className={cn(
      'flex flex-col items-center justify-center gap-3 text-center',
      variant === 'block' ? 'py-12 px-6' : 'py-6 px-4',
      className
    )}
  >
    <div className="space-y-1">
      <p className="text-status-alarm font-medium">{message}</p>
      {detail && (
        <p className="text-sm text-opsgrid-text-secondary max-w-prose">{detail}</p>
      )}
    </div>

    {onRetry && (
      <button
        type="button"
        onClick={onRetry}
        disabled={retrying}
        className={cn(
          'inline-flex items-center gap-2 rounded-md border border-opsgrid-border',
          'bg-opsgrid-panel px-3 py-1.5 text-sm text-opsgrid-text',
          'hover:bg-opsgrid-border focus:outline-none focus:ring-2 focus:ring-opsgrid-primary',
          'disabled:opacity-60 disabled:cursor-not-allowed'
        )}
      >
        {/* The label changes rather than only the spinner: "Retrying…" is the state, and a
            spinner alone is invisible to a screen reader and ambiguous to everyone else. */}
        {retrying ? 'Retrying…' : 'Retry'}
      </button>
    )}

    {children}
  </div>
);
