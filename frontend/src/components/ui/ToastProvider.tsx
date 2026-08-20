import {
  createContext,
  FC,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { cn } from '../../utils';

/**
 * Non-blocking confirmation that something happened.
 *
 * MEASURED: of 21 pages that trigger a mutation, **4 gave the user any feedback at all**. You
 * acknowledge every alarm on the page, the list refreshes, and nothing tells you the action
 * was yours rather than the ten-second poll. You save a notification rule and the form simply
 * sits there. The uncertainty is the friction — the usual response is to click again, which
 * is also why seven of those pages were double-submittable.
 *
 * WHY NOT THE EXISTING DIALOG. `DialogProvider` already offers `alert()`, and it is the wrong
 * tool here: it is modal, it takes focus, and it demands a dismissal for something the user
 * already knows they asked for. A confirmation that interrupts is worse than none — people
 * learn to dismiss it without reading, which is exactly how a real warning gets missed.
 *
 * ACCESSIBILITY IS THE POINT, NOT A GARNISH. The live region is rendered ALWAYS, empty when
 * idle, because a screen reader only announces changes to a region it was already watching —
 * mounting a populated `aria-live` node announces nothing, which is the standard way this
 * feature ships broken. Errors use `assertive`, successes `polite`: a failure interrupts, a
 * success waits for a pause.
 *
 * Auto-dismiss timing is per-variant on purpose: a success is gone in four seconds because
 * the screen already shows the new state, and an error stays for ten because the user has to
 * read it and decide. Errors are also dismissible, since "it worked" expiring is fine and
 * "it failed" vanishing before it is read is not.
 */
export type ToastVariant = 'success' | 'error' | 'info';

interface Toast {
  id: number;
  message: string;
  detail?: string;
  variant: ToastVariant;
}

interface ToastContextValue {
  /** Confirm an action succeeded. Auto-dismisses. */
  success: (message: string, detail?: string) => void;
  /** Report an action failed. Stays longer, and is dismissible. */
  error: (message: string, detail?: string) => void;
  info: (message: string, detail?: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const DISMISS_MS: Record<ToastVariant, number> = {
  success: 4000,
  info: 5000,
  error: 10000,
};

export const ToastProvider: FC<{ children: ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (variant: ToastVariant, message: string, detail?: string) => {
      const id = nextId.current++;
      setToasts((current) => {
        // Bounded. A failing poll can fire on an interval, and an unbounded stack would
        // cover the page it is reporting on.
        const next = [...current, { id, message, detail, variant }];
        return next.slice(-4);
      });
      timers.current.set(
        id,
        setTimeout(() => dismiss(id), DISMISS_MS[variant])
      );
    },
    [dismiss]
  );

  // Timers outlive the component without this, and fire setState on an unmounted tree.
  useEffect(
    () => () => {
      timers.current.forEach(clearTimeout);
      timers.current.clear();
    },
    []
  );

  const value = useMemo<ToastContextValue>(
    () => ({
      success: (message, detail) => push('success', message, detail),
      error: (message, detail) => push('error', message, detail),
      info: (message, detail) => push('info', message, detail),
    }),
    [push]
  );

  return (
    <ToastContext.Provider value={value}>
      {children}

      {/* Rendered unconditionally — see the note above about live regions. */}
      <div
        className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none"
        aria-live="polite"
        aria-atomic="false"
      >
        {toasts
          .filter((t) => t.variant !== 'error')
          .map((t) => (
            <ToastCard key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
          ))}
      </div>

      <div
        className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none"
        aria-live="assertive"
        aria-atomic="false"
      >
        {toasts
          .filter((t) => t.variant === 'error')
          .map((t) => (
            <ToastCard key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
          ))}
      </div>
    </ToastContext.Provider>
  );
};

const ToastCard: FC<{ toast: Toast; onDismiss: () => void }> = ({ toast, onDismiss }) => (
  <div
    data-testid={`toast-${toast.variant}`}
    className={cn(
      'pointer-events-auto min-w-[16rem] max-w-sm rounded-md border px-4 py-3 shadow-lg',
      'bg-opsgrid-panel text-opsgrid-text',
      toast.variant === 'success' && 'border-status-running',
      toast.variant === 'error' && 'border-status-alarm',
      toast.variant === 'info' && 'border-opsgrid-border'
    )}
  >
    <div className="flex items-start gap-3">
      <div className="flex-1 space-y-0.5">
        <p className="text-sm font-medium">{toast.message}</p>
        {toast.detail && (
          <p className="text-xs text-opsgrid-text-secondary">{toast.detail}</p>
        )}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        // Named for what it dismisses; "Close" alone gives a screen-reader user a list of
        // identical buttons when several are stacked.
        aria-label={`Dismiss: ${toast.message}`}
        className="text-opsgrid-text-secondary hover:text-opsgrid-text focus:outline-none focus:ring-2 focus:ring-opsgrid-primary rounded"
      >
        ×
      </button>
    </div>
  </div>
);

export const useToast = (): ToastContextValue => {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // Loud rather than a no-op. A silent fallback means a developer wires up feedback,
    // sees nothing, and concludes the mutation did not fire — which is the exact confusion
    // this component exists to remove.
    throw new Error('useToast must be used inside a <ToastProvider>');
  }
  return ctx;
};
