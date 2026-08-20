import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider, useToast } from './ToastProvider';

/**
 * Non-blocking confirmation (FS-766). Of 21 pages that trigger a mutation, four gave the
 * user any feedback at all — so an operator acknowledged an alarm, watched a list that also
 * refreshes on a ten-second poll, and had no way to tell the change was theirs.
 */
const Harness = () => {
  const toast = useToast();
  return (
    <div>
      <button onClick={() => toast.success('Alarm acknowledged', 'Press 1')}>ok</button>
      <button onClick={() => toast.error('Could not save')}>bad</button>
    </div>
  );
};

const renderHarness = () =>
  render(
    <ToastProvider>
      <Harness />
    </ToastProvider>
  );

describe('ToastProvider', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('confirms a success without taking focus', () => {
    renderHarness();
    act(() => void screen.getByText('ok').click());
    expect(screen.getByTestId('toast-success')).toHaveTextContent('Alarm acknowledged');
    // A modal would move focus; a confirmation that interrupts gets dismissed unread, which
    // is how a real warning later gets missed.
    expect(document.activeElement).toBe(document.body);
  });

  it('auto-dismisses a success but keeps an error longer', () => {
    renderHarness();
    act(() => void screen.getByText('ok').click());
    act(() => void screen.getByText('bad').click());

    act(() => void vi.advanceTimersByTime(4500));
    expect(screen.queryByTestId('toast-success')).not.toBeInTheDocument();
    // "It worked" expiring is fine. "It failed" vanishing before it is read is not.
    expect(screen.getByTestId('toast-error')).toBeInTheDocument();

    act(() => void vi.advanceTimersByTime(6000));
    expect(screen.queryByTestId('toast-error')).not.toBeInTheDocument();
  });

  it('separates polite and assertive live regions', () => {
    // A screen reader only announces changes to a region it was ALREADY watching, which is
    // why both regions are rendered from the start rather than mounted on demand — the
    // standard way this feature ships silently broken.
    renderHarness();
    expect(document.querySelector('[aria-live="polite"]')).toBeInTheDocument();
    expect(document.querySelector('[aria-live="assertive"]')).toBeInTheDocument();
  });

  it('bounds the stack so a failing poll cannot cover the page', () => {
    renderHarness();
    act(() => {
      for (let i = 0; i < 8; i++) screen.getByText('bad').click();
    });
    expect(screen.getAllByTestId('toast-error').length).toBeLessThanOrEqual(4);
  });

  it('can be dismissed by name', () => {
    renderHarness();
    act(() => void screen.getByText('ok').click());
    act(() => void screen.getByRole('button', { name: /dismiss: alarm acknowledged/i }).click());
    expect(screen.queryByTestId('toast-success')).not.toBeInTheDocument();
  });

  it('fails loudly outside a provider', () => {
    // A silent no-op means a developer wires up feedback, sees nothing, and concludes the
    // mutation never fired — the exact confusion this component exists to remove.
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<Harness />)).toThrow(/must be used inside/i);
    quiet.mockRestore();
  });
});
