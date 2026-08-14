import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useSuggestedQuestions } from './useSuggestedQuestions';

describe('useSuggestedQuestions', () => {
  it('loads prompts for the selected session', async () => {
    const getSuggestedQuestions = vi.fn().mockResolvedValue({
      questions: ['Which line has the most downtime?'],
      context_summary: '1 spreadsheet attached',
    });
    const client = { getSuggestedQuestions } as any;

    const { result } = renderHook(() => useSuggestedQuestions('session-1', 1, 0, client));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(getSuggestedQuestions).toHaveBeenCalledWith('session-1', 3);
    expect(result.current.questions).toEqual(['Which line has the most downtime?']);
    expect(result.current.summary).toBe('1 spreadsheet attached');
  });

  it('clears prompts when there is no session', () => {
    const { result } = renderHook(() => useSuggestedQuestions());
    expect(result.current).toEqual({ questions: [], summary: '', loading: false });
  });
});
