import { FC } from 'react';

/**
 * The one banner that separates an idle engine from an absent one (P4).
 *
 * Every engine status route reports `running` and, when the loop is down, a `note`
 * explaining that the figures are construction-time defaults rather than measurements
 * (FS-530 stamped the responses; nothing rendered them). Strategic has no status body —
 * its list routes signal via the `X-Engine-Not-Running` header instead — so this takes
 * the already-resolved boolean rather than a status object.
 *
 * `running === undefined` renders nothing: a server predating the field has not said the
 * loop is down, and "stopped" must not be the default for silence.
 */
export const EngineStoppedBanner: FC<{ running?: boolean; note?: string | null }> = ({
  running,
  note,
}) => {
  if (running !== false) return null;
  return (
    <div
      role="status"
      className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-300"
    >
      <span className="font-medium">Engine loop not running.</span>{' '}
      {note ??
        'The background loop behind this page is not started, so the figures below are defaults, not measurements.'}
    </div>
  );
};
