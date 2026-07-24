import {
  FC,
  ReactNode,
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Modal } from './Modal';
import { Button } from './Button';
import { Input } from './Input';

/**
 * Accessible, promise-based replacements for the native `window.alert`,
 * `window.confirm` and `window.prompt` (task: frontend a11y). The native
 * dialogs are unstyled, block the event loop, can't be focus-managed, and are
 * suppressed in some embedded/webview contexts — so a destructive "confirm"
 * that silently returns false there would delete without asking. These render
 * as real in-app modals via the accessible `Modal` primitive.
 *
 * Usage:
 *   const { confirm, prompt, alert } = useDialog();
 *   if (await confirm({ title: 'Delete user?', destructive: true })) { ... }
 *   const reason = await prompt({ title: 'Rejection reason', required: true });
 */

interface ConfirmOptions {
  title: ReactNode;
  message?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
}

interface PromptOptions {
  title: ReactNode;
  message?: ReactNode;
  placeholder?: string;
  defaultValue?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  required?: boolean;
  inputLabel?: string;
}

interface AlertOptions {
  title: ReactNode;
  message?: ReactNode;
  closeLabel?: string;
}

interface DialogContextValue {
  confirm: (opts: ConfirmOptions) => Promise<boolean>;
  prompt: (opts: PromptOptions) => Promise<string | null>;
  alert: (opts: AlertOptions) => Promise<void>;
}

const DialogContext = createContext<DialogContextValue | null>(null);

type Kind = 'confirm' | 'prompt' | 'alert';

interface DialogState {
  kind: Kind;
  opts: ConfirmOptions & PromptOptions & AlertOptions;
}

export const DialogProvider: FC<{ children: ReactNode }> = ({ children }) => {
  const [state, setState] = useState<DialogState | null>(null);
  const [value, setValue] = useState('');
  // The resolver for the currently-open dialog's promise.
  const resolver = useRef<((result: unknown) => void) | null>(null);

  const settle = useCallback((result: unknown) => {
    resolver.current?.(result);
    resolver.current = null;
    setState(null);
    setValue('');
  }, []);

  const open = useCallback(
    (kind: Kind, opts: DialogState['opts'], initialValue = '') =>
      new Promise((resolve) => {
        resolver.current = resolve as (result: unknown) => void;
        setValue(initialValue);
        setState({ kind, opts });
      }),
    []
  );

  const api = useMemo<DialogContextValue>(
    () => ({
      confirm: (opts) => open('confirm', opts as DialogState['opts']) as Promise<boolean>,
      prompt: (opts) =>
        open('prompt', opts as DialogState['opts'], opts.defaultValue ?? '') as Promise<
          string | null
        >,
      alert: (opts) => open('alert', opts as DialogState['opts']) as Promise<void>,
    }),
    [open]
  );

  const kind = state?.kind;
  const opts = state?.opts;
  const promptInvalid = kind === 'prompt' && !!opts?.required && value.trim() === '';

  const onCancel = useCallback(() => {
    // confirm → false, prompt → null, alert → undefined
    settle(kind === 'confirm' ? false : kind === 'prompt' ? null : undefined);
  }, [kind, settle]);

  const onConfirm = useCallback(() => {
    if (kind === 'confirm') settle(true);
    else if (kind === 'prompt') settle(value);
    else settle(undefined);
  }, [kind, value, settle]);

  const footer =
    kind === 'alert' ? (
      <Button onClick={onConfirm} autoFocus>
        {opts?.closeLabel ?? 'OK'}
      </Button>
    ) : (
      <>
        <Button variant="secondary" onClick={onCancel}>
          {opts?.cancelLabel ?? 'Cancel'}
        </Button>
        <Button
          variant={opts?.destructive ? 'danger' : 'primary'}
          onClick={onConfirm}
          disabled={promptInvalid}
        >
          {opts?.confirmLabel ?? (kind === 'confirm' ? 'Confirm' : 'OK')}
        </Button>
      </>
    );

  return (
    <DialogContext.Provider value={api}>
      {children}
      <Modal
        isOpen={state !== null}
        onClose={onCancel}
        title={opts?.title}
        footer={footer}
        className="max-w-md"
      >
        {opts?.message && (
          <p className="text-sm text-opsgrid-text-secondary">{opts.message}</p>
        )}
        {kind === 'prompt' && (
          <form
            className="mt-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!promptInvalid) onConfirm();
            }}
          >
            <Input
              label={opts?.inputLabel}
              autoFocus
              value={value}
              placeholder={opts?.placeholder}
              onChange={(e) => setValue(e.target.value)}
              error={promptInvalid ? 'This field is required' : undefined}
            />
          </form>
        )}
      </Modal>
    </DialogContext.Provider>
  );
};

export function useDialog(): DialogContextValue {
  const ctx = useContext(DialogContext);
  if (!ctx) {
    throw new Error('useDialog must be used within a <DialogProvider>');
  }
  return ctx;
}
