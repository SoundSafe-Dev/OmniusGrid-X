import React, { useState, useRef, useEffect } from 'react';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { Badge } from '../ui/Badge';
import { Tooltip, TooltipTrigger, TooltipContent, useDialog } from '../ui';
import { analysisSessionsApi, AnalysisSession, SessionMessage } from '../../api/analysisSessions';
import { SessionList } from './SessionList';
import { DataSourcesPanel, DataSourcesPanelHandle } from './DataSourcesPanel';
import { IntakeSelectorDialog } from './IntakeSelectorDialog';
import { ChatHistoryModal } from './ChatHistoryModal';
import { ContextPanel } from './ContextPanel';
import { RealTimeDataPanel } from './RealTimeDataPanel';
import { ActionableInsight } from './ActionableInsight';
import { Send, Loader2, CheckCircle, History, Inbox, Plus, Upload } from 'lucide-react';

interface CorrelationAIPaneProps {
  className?: string;
}

const ANALYSIS_PROGRESS_STEPS = [
  'Reading the uploaded spreadsheet',
  'Identifying the important columns and totals',
  'Looking for rows with high cost, delays, defects, or downtime',
  'Connecting delay reasons to assets, shifts, and maintenance status',
  'Generating response',
];

const CHAT_PROGRESS_STEPS = [
  'Reading your question',
  'Checking the current session context',
  'Thinking through the best response',
  'Generating response',
];

const splitInlineMarkdown = (text: string) => {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return <React.Fragment key={index}>{part}</React.Fragment>;
  });
};

const prettifyKeyValueText = (text: string) =>
  text
    .replace(/\basset_id=/g, '**Asset ID:** ')
    .replace(/\basset_name=/g, '**Asset name:** ')
    .replace(/\bproduction_line=/g, '**Production line:** ')
    .replace(/\bshift=/g, '**Shift:** ')
    .replace(/\bmaintenance_status=/g, '**Maintenance status:** ')
    .replace(/\bpriority=/g, '**Priority:** ')
    .replace(/\bdowntime_minutes=/g, '**Downtime:** ')
    .replace(/\bdowntime=/g, '**Downtime:** ')
    .replace(/\bdefect_count=/g, '**Defect count:** ')
    .replace(/\bvibration_level=/g, '**Vibration:** ')
    .replace(/\bvibration=/g, '**Vibration:** ')
    .replace(/\bestimated_cost_impact_usd=/g, '**Estimated cost impact:** ');

const normalizeAssistantContent = (content: string) =>
  prettifyKeyValueText(content)
    .replace(/\s+(#{1,4}\s+)/g, '\n$1')
    .replace(/\s+\*\s+/g, '\n* ')
    .replace(/\s+-\s+\*\*/g, '\n- **')
    .replace(/\s+(For [A-Z][^:\n]{2,60}:)/g, '\n\n$1')
    .replace(/\s+\|\s+/g, '\n')
    .replace(/;\s+(?=\*\*[A-Z])/g, '\n- ');

const FormattedMessageContent = ({ content, isAssistant }: { content: string; isAssistant: boolean }) => {
  if (!isAssistant) {
    return <p className="text-sm whitespace-pre-wrap text-white">{content}</p>;
  }

  const normalized = normalizeAssistantContent(content);
  const lines = normalized.split('\n');

  return (
    <div className="space-y-2 text-sm text-gray-900">
      {lines.map((rawLine, index) => {
        const line = rawLine.trim();
        if (!line) {
          return <div key={index} className="h-1" />;
        }

        const headingMatch = line.match(/^#{1,4}\s+(.+)$/);
        if (headingMatch) {
          return (
            <p key={index} className="pt-1 font-semibold text-gray-950">
              {splitInlineMarkdown(headingMatch[1])}
            </p>
          );
        }

        if (/^[A-Z][A-Za-z0-9 +/&-]{2,60}:$/.test(line)) {
          return (
            <p key={index} className="pt-2 font-semibold text-gray-950">
              {line}
            </p>
          );
        }

        const bulletMatch = line.match(/^[-*]\s+(.+)$/);
        if (bulletMatch) {
          return (
            <div key={index} className="flex gap-2 pl-1">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-gray-500" />
              <p className="leading-relaxed">{splitInlineMarkdown(bulletMatch[1])}</p>
            </div>
          );
        }

        const numberedMatch = line.match(/^(\d+)[.)]\s+(.+)$/);
        if (numberedMatch) {
          return (
            <div key={index} className="flex gap-2 pl-1">
              <span className="min-w-5 text-gray-500">{numberedMatch[1]}.</span>
              <p className="leading-relaxed">{splitInlineMarkdown(numberedMatch[2])}</p>
            </div>
          );
        }

        return (
          <p key={index} className="leading-relaxed">
            {splitInlineMarkdown(line)}
          </p>
        );
      })}
    </div>
  );
};

export const CorrelationAIPane: React.FC<CorrelationAIPaneProps> = ({ className }) => {
  const { alert } = useDialog();
  const [currentSession, setCurrentSession] = useState<AnalysisSession | null>(null);
  const [messages, setMessages] = useState<SessionMessage[]>([]);
  // The messages endpoint caps at `limit` and orders OLDEST FIRST (FS-459), so a session
  // over the cap loses its most recent turns — the pane shows the beginning of a
  // conversation and silently omits what was just said, which is the half a user is
  // actually looking at.
  const [historyTruncated, setHistoryTruncated] = useState(false);
  // Why a transcript is missing, when it is missing because the request failed rather than
  // because the session is new (FS-481). Those two look identical without it.
  const [transcriptError, setTranscriptError] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [activeProgressStep, setActiveProgressStep] = useState(0);
  const [autoIntegrate, setAutoIntegrate] = useState(true);
  const [showIntakeDialog, setShowIntakeDialog] = useState(false);
  const [showChatHistory, setShowChatHistory] = useState(false);
  const [dataSourcesKey, setDataSourcesKey] = useState(0);
  const [sessionListKey, setSessionListKey] = useState(0);
  const [pendingUpload, setPendingUpload] = useState(false);
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([]);
  const [suggestionsSummary, setSuggestionsSummary] = useState<string>('');
  const [isLoadingSuggestions, setIsLoadingSuggestions] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const dataSourcesRef = useRef<DataSourcesPanelHandle>(null);
  const progressTimerRef = useRef<number | null>(null);
  const activeProgressSteps = (currentSession?.data_sources_count || 0) > 0
    ? ANALYSIS_PROGRESS_STEPS
    : CHAT_PROGRESS_STEPS;

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, activeProgressStep, isLoading]);

  useEffect(() => {
    return () => {
      if (progressTimerRef.current) window.clearInterval(progressTimerRef.current);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    const loadSuggestions = async () => {
      if (!currentSession?.id) {
        setSuggestedQuestions([]);
        setSuggestionsSummary('');
        return;
      }

      setIsLoadingSuggestions(true);
      try {
        const response = await analysisSessionsApi.getSuggestedQuestions(currentSession.id, 3);
        if (!cancelled) {
          setSuggestedQuestions(response.questions || []);
          setSuggestionsSummary(response.context_summary || '');
        }
      } catch (error) {
        console.error('[CorrelationAIPane] Failed to load suggested questions:', error);
        if (!cancelled) {
          setSuggestedQuestions([]);
          setSuggestionsSummary('');
        }
      } finally {
        if (!cancelled) {
          setIsLoadingSuggestions(false);
        }
      }
    };

    loadSuggestions();
    return () => {
      cancelled = true;
    };
  }, [currentSession?.id, currentSession?.data_sources_count, dataSourcesKey]);

  useEffect(() => {
    if (!pendingUpload || !currentSession) return;
    const timer = window.setTimeout(() => {
      dataSourcesRef.current?.openFilePicker();
      setPendingUpload(false);
    }, 100);
    return () => window.clearTimeout(timer);
  }, [pendingUpload, currentSession, dataSourcesKey]);

  const isSessionNotFound = (error: any) =>
    error?.response?.status === 404 &&
    String(error?.response?.data?.detail || '').toLowerCase().includes('session not found');

  const getErrorDetail = (error: any) =>
    error?.response?.data?.detail || error?.message || 'Unknown error';

  const createReplacementSession = async () => {
    const session = await analysisSessionsApi.createSession({});
    await analysisSessionsApi.getSession(session.id);
    setCurrentSession(session);
    setTranscriptError(null);
    setSessionListKey(prev => prev + 1);
    setDataSourcesKey(prev => prev + 1);
    return session;
  };

  const ensureActiveSession = async (): Promise<AnalysisSession> => {
    if (currentSession) {
      try {
        return await analysisSessionsApi.getSession(currentSession.id);
      } catch (error: any) {
        if (!isSessionNotFound(error)) {
          throw error;
        }
      }
    }
    return createReplacementSession();
  };

  useEffect(() => {
    let cancelled = false;

    const bootstrapSession = async () => {
      try {
        const response = await analysisSessionsApi.listSessions(20, 0, 'active');
        if (cancelled || currentSession || response.sessions.length === 0) {
          return;
        }
        const latest = response.sessions[0];
        setCurrentSession(latest);
        const sessionMessages = await analysisSessionsApi.getSessionMessages(latest.id, 100, 0);
        if (!cancelled) {
          setMessages(sessionMessages.items);
          setHistoryTruncated(sessionMessages.truncated);
        }
      } catch (error) {
        console.error('[CorrelationAIPane] Failed to bootstrap session:', error);
        // FS-481. `setCurrentSession(latest)` may already have run, so the pane can show a
        // named session with no messages — indistinguishable from a session nobody used.
        if (!cancelled) {
          setTranscriptError('Your last session could not be loaded — it is not an empty session. Reload to retry.');
        }
      }
    };

    bootstrapSession();
    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing; adding deps changes retrigger behavior (FS-54)
  }, []);

  const handleCreateNewSession = async () => {
    try {
      console.log('[CorrelationAIPane] Creating new session...');
      const session = await createReplacementSession();
      console.log('[CorrelationAIPane] Session created:', session);
      setMessages([]);
      setHistoryTruncated(false);
    } catch (error) {
      console.error('[CorrelationAIPane] Error creating session:', error);
      await alert({ title: 'Could not create session', message: 'Failed to create session. Check the console for details.' });
    }
  };

  const handleSessionSelect = async (session: AnalysisSession) => {
    setCurrentSession(session);
    setTranscriptError(null);
    try {
      const sessionMessages = await analysisSessionsApi.getSessionMessages(session.id, 100, 0);
      setMessages(sessionMessages.items);
      setHistoryTruncated(sessionMessages.truncated);
    } catch (error) {
      console.error('Error loading session messages:', error);
      // FS-481. The session is switched BEFORE its transcript arrives, so a failure here
      // used to leave the PREVIOUS session's conversation on screen under the new
      // session's name — the header, the data-sources panel and the suggested questions
      // all say session B while the messages are session A's. That is worse than showing
      // nothing: it is another investigation, read as this one. Clear it, and say why the
      // pane is empty so it is not mistaken for a session that was never used.
      setMessages([]);
      setHistoryTruncated(false);
      setTranscriptError('This session\'s history could not be loaded — it is not an empty session. Select it again to retry.');
    }
  };

  const handleAddIntakeData = async (intakeId: string) => {
    if (!currentSession) return;
    try {
      await analysisSessionsApi.addIntakeData(currentSession.id, intakeId);
      // Force refresh of data sources panel
      setDataSourcesKey(prev => prev + 1);
    } catch (error) {
      console.error('Error adding intake data:', error);
      // FS-481. Silently, the document simply never appears in the panel — and the next
      // question is answered from a data set the operator believes contains it.
      await alert({
        title: 'Could not attach that document',
        message: 'The document was not added to this session. Answers will not take it into account.',
      });
    }
  };

  const handleUploadExcel = async () => {
    try {
      await ensureActiveSession();
      if (dataSourcesRef.current) {
        dataSourcesRef.current.openFilePicker();
      } else {
        setPendingUpload(true);
      }
    } catch (error) {
      console.error('Error preparing session for upload:', error);
      await alert({ title: 'Upload unavailable', message: 'Could not start a session for upload. Check the backend/tunnel and try again.' });
    }
  };

  const handleSessionMissingForUpload = async () => {
    try {
      const session = await createReplacementSession();
      setMessages([]);
      setHistoryTruncated(false);
      return session.id;
    } catch (error) {
      console.error('Error recovering missing session:', error);
      return null;
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleFollowUpClick = (question: string) => {
    setInput(question);
    window.setTimeout(() => {
      document.getElementById('correlation-chat-input')?.focus();
    }, 0);
  };

  const handleSuggestedQuestionClick = (question: string) => {
    setInput(question);
    window.setTimeout(() => {
      handleSendMessageWithText(question);
    }, 0);
  };

  const handleSendMessageWithText = async (messageText?: string) => {
    const userText = (messageText ?? input).trim();
    if (!userText || isLoading) return;

    let activeSession: AnalysisSession;
    try {
      activeSession = await ensureActiveSession();
    } catch (error) {
      console.error('Error ensuring session before chat:', error);
      await alert({ title: 'Session unavailable', message: 'Could not create or load a session. Check the backend/tunnel and try again.' });
      return;
    }

    const userMessage: SessionMessage = {
      id: crypto.randomUUID(),
      session_id: activeSession.id,
      role: 'user',
      content: userText,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);
    setActiveProgressStep(0);
    const requestProgressSteps = activeProgressSteps;
    if (progressTimerRef.current) window.clearInterval(progressTimerRef.current);
    progressTimerRef.current = window.setInterval(() => {
      const maxStep = requestProgressSteps.length - 1;
      setActiveProgressStep((step) => Math.min(step + 1, maxStep));
    }, 1300);

    const appendAssistantMessage = (response: any, sessionId: string) => {
      setIsLoading(false);
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          session_id: sessionId,
          role: response.role,
          content: response.content || '',
          analysis: response.analysis,
          risk_score: normalizeRiskScore(response.risk_score),
          domains: response.domains,
          actions: response.actions,
          follow_up_questions: response.follow_up_questions || response.analysis?.follow_up_questions,
          timestamp: response.timestamp,
          // Carried through, never defaulted: the server sets this when the reply is a
          // heuristic or an error fallback rather than an inference, and dropping it
          // here would put the confident version back in front of the operator.
          simulated: response.simulated,
          simulation_reason: response.simulation_reason
        }
      ]);
    };

    try {
      let response;

      try {
        response = await analysisSessionsApi.sessionChat(activeSession.id, {
          message: userText,
          auto_integrate: autoIntegrate
        });
      } catch (error: any) {
        if (!isSessionNotFound(error)) {
          throw error;
        }

        activeSession = await createReplacementSession();
        setMessages((prev) =>
          prev.map((message) =>
            message.id === userMessage.id
              ? { ...message, session_id: activeSession.id }
              : message
          )
        );
        response = await analysisSessionsApi.sessionChat(activeSession.id, {
          message: userText,
          auto_integrate: autoIntegrate
        });
      }

      appendAssistantMessage(response, activeSession.id);

      if (messages.length === 2) {
        try {
          await analysisSessionsApi.generateSessionTitle(activeSession.id);
          const updatedSession = await analysisSessionsApi.getSession(activeSession.id);
          setCurrentSession(updatedSession);
        } catch (titleError) {
          console.warn('Failed to generate session title:', titleError);
        }
      }
    } catch (error: any) {
      console.error('Error sending message:', error);
      const detail = getErrorDetail(error);
      const isNetworkOrTimeout =
        error?.code === 'ECONNABORTED' ||
        String(detail).toLowerCase().includes('network') ||
        String(detail).toLowerCase().includes('timeout');
      const content = isNetworkOrTimeout
        ? 'The assistant could not reach the backend. Check that the SSH tunnel is running, the VM backend is up, and the first Gemma reply has enough time to complete.'
        : `The assistant could not complete this request: ${detail}`;

      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          session_id: activeSession.id,
          role: 'assistant',
          content,
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      if (progressTimerRef.current) {
        window.clearInterval(progressTimerRef.current);
        progressTimerRef.current = null;
      }
      setIsLoading(false);
    }
  };

  const handleSendMessage = async () => {
    await handleSendMessageWithText();
  };

  const renderSuggestedQuestions = (className = '') => {
    if (!currentSession || suggestedQuestions.length === 0) {
      return null;
    }

    return (
      <div className={`space-y-2 ${className}`}>
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Suggestions</p>
        {suggestionsSummary ? (
          <p className="text-xs text-gray-500">{suggestionsSummary}</p>
        ) : null}
        <div className="flex flex-col gap-2">
          {suggestedQuestions.map((question) => (
            <button
              key={question}
              type="button"
              onClick={() => handleSuggestedQuestionClick(question)}
              disabled={isLoading}
              className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-left text-sm leading-snug text-gray-800 shadow-sm transition hover:border-gray-300 hover:bg-white hover:text-gray-950 focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:opacity-60"
            >
              {question}
            </button>
          ))}
        </div>
      </div>
    );
  };

  const getFollowUpQuestions = (message: SessionMessage): string[] => {
    const questions = message.follow_up_questions || message.analysis?.follow_up_questions || [];
    return Array.isArray(questions)
      ? questions.filter((question): question is string => typeof question === 'string').slice(0, 3)
      : [];
  };

  const getRiskScoreVariant = (score: number) => {
    if (score > 75) return 'error';
    if (score > 50) return 'warning';
    if (score > 25) return 'info';
    return 'success';
  };

  const getRiskScoreLabel = (score: number) => {
    if (score > 75) return 'Critical';
    if (score > 50) return 'High';
    if (score > 25) return 'Medium';
    return 'Low';
  };

  const normalizeRiskScore = (score: unknown) => {
    if (score === null || score === undefined) return undefined;
    const numericScore = Number(score);
    return Number.isFinite(numericScore) ? numericScore : undefined;
  };

  return (
    <div className={`flex h-[calc(100vh-2rem)] w-full max-w-full gap-3 overflow-hidden ${className}`}>
      {/* Left Sidebar - Sessions (top) + Excel upload (bottom) */}
      <div className="w-72 shrink-0 min-w-0 flex flex-col h-full min-h-0 overflow-hidden border border-opsgrid-border rounded-lg bg-opsgrid-panel">
        <div className="h-[42%] min-h-[180px] max-h-[280px] overflow-hidden border-b border-opsgrid-border">
          <SessionList
            key={sessionListKey}
            onSessionSelect={handleSessionSelect}
            onNewSession={handleCreateNewSession}
            currentSessionId={currentSession?.id}
            className="h-full"
          />
        </div>
        {currentSession ? (
          <div className="flex-1 min-h-0 overflow-hidden">
            <DataSourcesPanel
              ref={dataSourcesRef}
              key={dataSourcesKey}
              sessionId={currentSession.id}
              onDataSourceAdded={() => setDataSourcesKey((prev) => prev + 1)}
              onSessionMissing={handleSessionMissingForUpload}
              className="h-full"
            />
          </div>
        ) : (
          <div className="flex-1 p-4 text-xs text-opsgrid-text-secondary">
            Click <strong>+ New</strong> above to create a session, then upload Excel here or use
            <strong> Upload Excel</strong> in the chat header.
          </div>
        )}
      </div>

      {/* Center - Chat Interface */}
      <div className="flex-1 min-w-0 min-h-0 bg-opsgrid-panel border border-opsgrid-border rounded-lg overflow-hidden flex flex-col">
        <div className="p-4 border-b border-opsgrid-border flex items-center justify-between gap-4 shrink-0 overflow-hidden">
          <div className="flex items-center gap-3 min-w-0 flex-1">
            <h2 className="text-lg font-semibold text-opsgrid-text truncate">
              {currentSession?.title || 'Correlation AI Assistant'}
            </h2>
            {currentSession && (
              <Badge
                variant="neutral"
                className="text-xs shrink-0 whitespace-nowrap bg-white text-gray-900 border border-gray-300"
              >
                {currentSession.data_sources_count} sources
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0 min-w-0">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="sm" onClick={handleUploadExcel}>
                  <Upload className="w-4 h-4 mr-2" />
                  Upload Excel
                </Button>
              </TooltipTrigger>
              <TooltipContent>Upload .xlsx, .xls, or .csv for this session</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="sm" onClick={() => setShowIntakeDialog(true)} disabled={!currentSession}>
                  <Inbox className="w-4 h-4 mr-2" />
                  Intake
                </Button>
              </TooltipTrigger>
              <TooltipContent>Add items from Intake Inbox (optional)</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="sm" onClick={() => setShowChatHistory(true)}>
                  <History className="w-4 h-4 mr-2" />
                  History
                </Button>
              </TooltipTrigger>
              <TooltipContent>View chat history and previous sessions</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={autoIntegrate}
                    onChange={(e) => setAutoIntegrate(e.target.checked)}
                    className="rounded"
                  />
                  Auto-integrate
                </label>
              </TooltipTrigger>
              {/*
                HONEST LABEL (FS-406). This used to read "Automatically create Kanban tasks
                from AI recommendations", which claimed an outcome the UI never checked: the
                background integration reports nothing back, so it can create nothing and
                this screen looks identical either way. The wording now says what is actually
                guaranteed, and points at the per-action Activate control, which does report
                what it created and where each system of record stands.
              */}
              <TooltipContent>
                Asks the analysis to hand its recommendations to the background Kanban
                integration. It does not report back, so use Activate on an individual
                recommendation when you need to see what was created.
              </TooltipContent>
            </Tooltip>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden p-4 bg-opsgrid-bg">
          {/* A transcript that failed to load, said out loud (FS-481). Above the branch
              below because that branch renders the SAME empty state for a session with no
              messages and a session whose messages could not be fetched. */}
          {transcriptError && (
            <div
              role="alert"
              className="mb-3 rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-500"
            >
              {transcriptError}
            </div>
          )}
          {!currentSession ? (
            <div className="h-full min-h-0 rounded-xl border border-gray-300 bg-white text-center text-gray-900 flex flex-col items-center justify-center px-8">
              <Plus className="w-12 h-12 mb-4 text-gray-400" />
              <p className="text-lg font-medium mb-2">Create a new session to start</p>
              <p className="text-sm text-gray-600">
                Sessions allow you to organize your analysis with data sources and context.
              </p>
            </div>
          ) : messages.length === 0 ? (
            <div className="h-full min-h-0 rounded-xl border border-gray-300 bg-white text-gray-900 flex flex-col items-center justify-center px-8 py-8">
              {isLoadingSuggestions ? (
                <div className="flex items-center gap-2 text-sm text-gray-500 mb-6">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Reading your uploads for suggestions...
                </div>
              ) : suggestedQuestions.length > 0 ? (
                <div className="w-full max-w-2xl">
                  <p className="text-lg font-medium mb-2 text-center">Ask anything about your data</p>
                  <p className="text-sm text-gray-600 mb-6 text-center">
                    Suggestions are based on the files and tabs you uploaded — not generic prompts.
                  </p>
                  {renderSuggestedQuestions()}
                </div>
              ) : (
                <>
                  <p className="text-lg font-medium mb-2">Start the conversation</p>
                  <p className="text-sm max-w-md text-gray-600 text-center">
                    Upload spreadsheets or documents, then Omnius will suggest questions tailored to your data.
                  </p>
                </>
              )}
            </div>
          ) : (
            <div className="space-y-4 overflow-x-hidden">
              {/* Say so when the pane is showing a page (FS-459). The list is oldest
                  first, so the messages missing are the RECENT ones — a user scrolling to
                  the bottom of this pane would otherwise believe they had reached the end
                  of the conversation. */}
              {historyTruncated && (
                <div
                  role="status"
                  className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300"
                >
                  This session has more messages than are shown here. The most recent turns
                  may be missing — start a new session to continue the conversation.
                </div>
              )}
              {messages.map((message, index) => {
                const followUpQuestions = message.role === 'assistant' ? getFollowUpQuestions(message) : [];

                return (
                <div key={index} className="space-y-2">
                  <div
                    className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                  <div
                    className={`max-w-[80%] rounded-lg p-4 ${
                      message.role === 'user'
                        ? 'bg-blue-500 text-white'
                        : 'bg-white text-gray-900 border border-gray-200 shadow-sm'
                    }`}
                  >
                    {message.role === 'assistant' && message.simulated && (
                      <div className="mb-3">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Badge variant="warning">Not a model inference</Badge>
                          </TooltipTrigger>
                          <TooltipContent>
                            {message.simulation_reason ||
                              'This reply was produced without the correlation model.'}
                          </TooltipContent>
                        </Tooltip>
                      </div>
                    )}

                    {message.role === 'assistant' && (() => {
                      const riskScore = normalizeRiskScore(message.risk_score);
                      if (riskScore === undefined) return null;

                      return (
                        <div className="mb-3">
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Badge variant={getRiskScoreVariant(riskScore)}>
                                {getRiskScoreLabel(riskScore)} Risk: {riskScore.toFixed(1)}/100
                              </Badge>
                            </TooltipTrigger>
                            <TooltipContent>AI-assessed risk severity (0-100)</TooltipContent>
                          </Tooltip>
                        </div>
                      );
                    })()}

                    {message.domains && message.domains.length > 0 && (
                      <div className="mb-2 flex flex-wrap gap-1">
                        {message.domains.map((domain) => (
                          <Tooltip key={domain}>
                            <TooltipTrigger asChild>
                              <Badge variant="info" className="text-xs">
                                {domain}
                              </Badge>
                            </TooltipTrigger>
                            <TooltipContent>Operational domain: {domain}</TooltipContent>
                          </Tooltip>
                        ))}
                      </div>
                    )}

                    <FormattedMessageContent
                      content={message.content}
                      isAssistant={message.role === 'assistant'}
                    />

                    {message.actions && message.actions.length > 0 && (
                      <div className="mt-3 pt-3 border-t border-gray-200">
                        <p className="text-xs font-medium text-gray-700 mb-2">Recommended Actions:</p>
                        {/*
                          Each line is activatable (FS-406). It used to be a bullet with a
                          green tick — which read as "done" for work that had not been
                          started and could not be started from here. Activating one creates
                          the Kanban task and a posting to every system of record its domain
                          implies, and the row then shows each of those individually,
                          including the ones that need a person told.
                        */}
                        <ul className="text-xs space-y-1.5">
                          {message.actions.map((action, idx) => (
                            <ActionableInsight
                              key={idx}
                              action={action}
                              index={idx}
                              sessionId={message.session_id || currentSession?.id}
                              messageId={message.id}
                              domain={message.domains?.[0]}
                            />
                          ))}
                        </ul>
                      </div>
                    )}

                    <p className="text-xs mt-2 opacity-70">
                      {new Date(message.timestamp).toLocaleTimeString()}
                    </p>
                  </div>
                </div>
                  {followUpQuestions.length > 0 && (
                    <div className="ml-8 flex max-w-[72%] flex-wrap gap-1.5">
                      {followUpQuestions.map((question) => (
                        <button
                          key={question}
                          type="button"
                          onClick={() => handleFollowUpClick(question)}
                          className="rounded-md border border-gray-300/80 bg-gray-100/90 px-2.5 py-1.5 text-left text-[11px] leading-snug text-gray-700 shadow-sm transition hover:bg-gray-200 hover:text-gray-950 focus:outline-none focus:ring-2 focus:ring-blue-400"
                        >
                          {question}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                );
              })}
              {isLoading && (
                <div className="flex justify-start">
                  <div className="bg-white border border-gray-200 shadow-sm rounded-lg p-4 max-w-[80%]">
                    <div className="flex items-center gap-2 mb-3">
                      <Loader2 className="w-4 h-4 animate-spin text-blue-500" />
                      <span className="text-sm font-medium text-gray-900">
                        {(currentSession?.data_sources_count || 0) > 0 ? 'Working through the analysis' : 'Working on a response'}
                      </span>
                    </div>
                    <div className="space-y-2">
                      {activeProgressSteps.map((step, stepIndex) => {
                        const isComplete = stepIndex < activeProgressStep;
                        const isActive = stepIndex === activeProgressStep;

                        return (
                          <div
                            key={step}
                            className={`flex items-center gap-2 text-xs ${
                              isActive ? 'text-gray-900' : 'text-gray-500'
                            }`}
                          >
                            {isComplete ? (
                              <CheckCircle className="w-3.5 h-3.5 text-green-500" />
                            ) : isActive ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-500" />
                            ) : (
                              <span className="w-3.5 h-3.5 rounded-full border border-gray-300" />
                            )}
                            <span>{step}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        <div className="p-4 border-t border-opsgrid-border shrink-0">
          <div className="flex gap-2 min-w-0">
            <Input
              id="correlation-chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder={
                (currentSession?.data_sources_count || 0) > 0
                  ? 'Ask anything about your uploaded data...'
                  : 'Ask about operational issues, correlations, or recommendations...'
              }
              disabled={isLoading}
              className="flex-1 min-w-0"
            />
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  data-testid="correlation-send"
                  onClick={handleSendMessage}
                  disabled={isLoading || !input.trim()}
                  className="px-4"
                >
                  {isLoading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent>Submit query to Correlation AI</TooltipContent>
            </Tooltip>
          </div>
        </div>
      </div>

      {/* Right Sidebar - Context and Real-Time Data */}
      <div className="w-64 shrink-0 min-w-0 flex flex-col gap-4 overflow-hidden">
        <ContextPanel />
        {currentSession && (
          <RealTimeDataPanel sessionId={currentSession.id} />
        )}
      </div>

      {/* Dialogs */}
      {currentSession && (
        <>
          <IntakeSelectorDialog
            isOpen={showIntakeDialog}
            onClose={() => setShowIntakeDialog(false)}
            onSelect={handleAddIntakeData}
          />
          <ChatHistoryModal
            isOpen={showChatHistory}
            onClose={() => setShowChatHistory(false)}
          />
        </>
      )}
    </div>
  );
};
