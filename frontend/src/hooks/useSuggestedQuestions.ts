import { useEffect, useState } from 'react';
import { analysisSessionsApi } from '../api/analysisSessions';

export interface SuggestedQuestionsState {
  questions: string[];
  summary: string;
  loading: boolean;
}

/** Fetch session-specific prompts independently from the chat layout. */
export function useSuggestedQuestions(
  sessionId?: string,
  dataSourcesCount?: number,
  refreshKey = 0,
  client = analysisSessionsApi,
): SuggestedQuestionsState {
  const [questions, setQuestions] = useState<string[]>([]);
  const [summary, setSummary] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!sessionId) {
      setQuestions([]);
      setSummary('');
      setLoading(false);
      return () => { cancelled = true; };
    }

    const load = async () => {
      setLoading(true);
      try {
        const response = await client.getSuggestedQuestions(sessionId, 3);
        if (!cancelled) {
          setQuestions(response.questions || []);
          setSummary(response.context_summary || '');
        }
      } catch {
        if (!cancelled) {
          setQuestions([]);
          setSummary('');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => { cancelled = true; };
  }, [sessionId, dataSourcesCount, refreshKey, client]);

  return { questions, summary, loading };
}
