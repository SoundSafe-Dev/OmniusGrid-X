import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ErrorState } from './ErrorState';

/**
 * The component that turns 65 dead ends into recoverable failures (FS-766).
 *
 * The assertions are about what a user can DO, not about markup: can they see that something
 * failed without relying on colour, can they act on it, and can they not make it worse by
 * clicking repeatedly.
 */
describe('ErrorState', () => {
  it('announces the failure rather than only colouring it', () => {
    // Colour was the only cue in most of the states this replaces, so a screen-reader user
    // reached the failure and heard nothing at all.
    render(<ErrorState message="Alarms could not be loaded." />);
    expect(screen.getByRole('alert')).toHaveTextContent('Alarms could not be loaded.');
  });

  it('offers a retry that calls back', () => {
    const onRetry = vi.fn();
    render(<ErrorState message="Nope." onRetry={onRetry} />);
    fireEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('omits the control entirely when a retry cannot help', () => {
    // A deleted record or a permission this session will never have. Offering a retry that
    // cannot work is worse than offering none — the user clicks it repeatedly and concludes
    // the product is broken rather than that the answer is no.
    render(<ErrorState message="This report no longer exists." />);
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument();
  });

  it('disables the control while a retry is in flight', () => {
    render(<ErrorState message="Nope." onRetry={vi.fn()} retrying />);
    const button = screen.getByRole('button', { name: /retrying/i });
    expect(button).toBeDisabled();
    // The LABEL changes, not just a spinner: a spinner alone is invisible to a screen
    // reader and ambiguous to everyone else.
    expect(button).toHaveTextContent(/retrying/i);
  });

  it('does not fire the callback again while already retrying', () => {
    const onRetry = vi.fn();
    render(<ErrorState message="Nope." onRetry={onRetry} retrying />);
    fireEvent.click(screen.getByRole('button', { name: /retrying/i }));
    expect(onRetry).not.toHaveBeenCalled();
  });

  it('renders extra escapes beside the retry', () => {
    // AssetDetail keeps "Back to Assets" here: a retry helps a transient failure, and an
    // asset that will never load needs a way out.
    render(
      <ErrorState message="Nope." onRetry={vi.fn()}>
        <a href="/assets">Back to Assets</a>
      </ErrorState>
    );
    expect(screen.getByRole('link', { name: /back to assets/i })).toBeInTheDocument();
  });

  it('shows a detail line when one is given, and nothing when not', () => {
    const { rerender } = render(
      <ErrorState message="Nope." detail="Your filters are still applied." />
    );
    expect(screen.getByText(/filters are still applied/i)).toBeInTheDocument();
    rerender(<ErrorState message="Nope." />);
    expect(screen.queryByText(/filters are still applied/i)).not.toBeInTheDocument();
  });
});
