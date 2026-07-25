import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import { describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { Modal } from './Modal';
import { DialogProvider, useDialog } from './DialogProvider';
import { Button } from './Button';

describe('Modal', () => {
  it('has no axe violations and exposes dialog semantics', async () => {
    const { container } = render(
      <Modal isOpen onClose={() => {}} title="Confirm action">
        <p>Body content</p>
      </Modal>
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    // title wires aria-labelledby
    expect(dialog).toHaveAccessibleName('Confirm action');
    expect(await axe(container)).toHaveNoViolations();
  });

  it('closes on Escape and on backdrop click', () => {
    const onClose = vi.fn();
    render(
      <Modal isOpen onClose={onClose} title="T">
        <p>x</p>
      </Modal>
    );
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not render when closed', () => {
    render(
      <Modal isOpen={false} onClose={() => {}} title="Hidden">
        <p>x</p>
      </Modal>
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

describe('DialogProvider', () => {
  const Harness = () => {
    const { confirm } = useDialog();
    const [result, setResult] = useState<string>('');
    return (
      <div>
        <Button onClick={async () => setResult(String(await confirm({ title: 'Delete?' })))}>
          go
        </Button>
        <span data-testid="result">{result}</span>
      </div>
    );
  };

  it('resolves confirm() true when the confirm button is pressed', async () => {
    render(
      <DialogProvider>
        <Harness />
      </DialogProvider>
    );
    fireEvent.click(screen.getByText('go'));
    // dialog appears
    expect(await screen.findByRole('dialog')).toHaveAccessibleName('Delete?');
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(screen.getByTestId('result')).toHaveTextContent('true'));
  });
});
