import {
  FC,
  ReactNode,
  useCallback,
  useEffect,
  useId,
  useRef,
} from 'react';
import { createPortal } from 'react-dom';
import { cn } from '../../utils';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Accessible title. Rendered as the dialog heading and wired via aria-labelledby. */
  title?: ReactNode;
  /** Optional description, wired via aria-describedby. */
  description?: ReactNode;
  children: ReactNode;
  /** Footer actions (buttons). Kept in the focus trap. */
  footer?: ReactNode;
  /** Close when the backdrop is clicked. Default true. */
  closeOnBackdrop?: boolean;
  /** Close when Escape is pressed. Default true. */
  closeOnEscape?: boolean;
  className?: string;
  /** Accessible label when there is no visible title. */
  ariaLabel?: string;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Accessible modal dialog primitive (task: frontend a11y).
 *
 * Provides everything a hand-rolled `fixed inset-0` overlay usually forgets:
 * `role="dialog"` + `aria-modal`, a focus trap, Escape-to-close, focus restore
 * to the trigger on close, body scroll-lock, and a labelled/described region.
 * Every modal in the app should be built on this instead of re-implementing the
 * overlay (which is how inaccessible, un-dismissable dialogs creep in).
 */
export const Modal: FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  description,
  children,
  footer,
  closeOnBackdrop = true,
  closeOnEscape = true,
  className,
  ariaLabel,
}) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();
  // Remember what had focus so we can restore it when the modal closes — a
  // keyboard user must land back where they were, not at the top of the page.
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    previouslyFocused.current = document.activeElement as HTMLElement | null;

    // Lock body scroll while open.
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    // Move focus into the dialog (first focusable, else the panel itself).
    const panel = panelRef.current;
    const first = panel?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? panel)?.focus();

    return () => {
      document.body.style.overflow = prevOverflow;
      // Restore focus to the trigger.
      previouslyFocused.current?.focus?.();
    };
  }, [isOpen]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === 'Escape' && closeOnEscape) {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;

      // Focus trap: keep Tab / Shift+Tab cycling inside the dialog.
      const panel = panelRef.current;
      if (!panel) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null || el === document.activeElement
      );
      if (focusable.length === 0) {
        e.preventDefault();
        panel.focus();
        return;
      }
      const firstEl = focusable[0];
      const lastEl = focusable[focusable.length - 1];
      const active = document.activeElement as HTMLElement;

      if (e.shiftKey && active === firstEl) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && active === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    },
    [closeOnEscape, onClose]
  );

  if (!isOpen) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onKeyDown={onKeyDown}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60"
        aria-hidden="true"
        onClick={closeOnBackdrop ? onClose : undefined}
      />
      {/* Panel */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-label={!title ? ariaLabel : undefined}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className={cn(
          'relative z-10 w-full max-w-lg rounded-xl border border-opsgrid-border',
          'bg-opsgrid-surface shadow-xl focus:outline-none',
          'max-h-[90vh] overflow-y-auto',
          className
        )}
      >
        {title && (
          <div className="px-6 pt-6">
            <h2 id={titleId} className="text-lg font-semibold text-opsgrid-text">
              {title}
            </h2>
          </div>
        )}
        {description && (
          <p id={descId} className="px-6 pt-2 text-sm text-opsgrid-text-secondary">
            {description}
          </p>
        )}
        <div className="px-6 py-4">{children}</div>
        {footer && (
          <div className="flex justify-end gap-2 border-t border-opsgrid-border px-6 py-4">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
};
