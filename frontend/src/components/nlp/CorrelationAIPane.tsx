import React, { useState, useRef, useEffect } from 'react';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { Badge } from '../ui/Badge';
import { Tooltip, TooltipTrigger, TooltipContent } from '../ui';
import { analysisSessionsApi, AnalysisSession, SessionMessage } from '../../api/analysisSessions';
import { SessionList } from './SessionList';
import { DataSourcesPanel, DataSourcesPanelHandle } from './DataSourcesPanel';
import { IntakeSelectorDialog } from './IntakeSelectorDialog';
import { ChatHistoryModal } from './ChatHistoryModal';
import { ContextPanel } from './ContextPanel';
import { RealTimeDataPanel } from './RealTimeDataPanel';
import { Send, Loader2, CheckCircle, History, Inbox, Plus, Upload } from 'lucide-react';

interface CorrelationAIPaneProps {
  className?: string;
}

export const CorrelationAIPane: React.FC<CorrelationAIPaneProps> = ({ className }) => {
  const [currentSession, setCurrentSession] = useState<AnalysisSession | null>(null);
  const [messages, setMessages] = useState<SessionMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [autoIntegrate, setAutoIntegrate] = useState(true);
  const [showIntakeDialog, setShowIntakeDialog] = useState(false);
  const [showChatHistory, setShowChatHistory] = useState(false);
  const [dataSourcesKey, setDataSourcesKey] = useState(0);
  const [sessionListKey, setSessionListKey] = useState(0);
  const [pendingUpload, setPendingUpload] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const dataSourcesRef = useRef<DataSourcesPanelHandle>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

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
          setMessages(sessionMessages);
        }
      } catch (error) {
        console.error('[CorrelationAIPane] Failed to bootstrap session:', error);
      }
    };

    bootstrapSession();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleCreateNewSession = async () => {
    try {
      console.log('[CorrelationAIPane] Creating new session...');
      const session = await createReplacementSession();
      console.log('[CorrelationAIPane] Session created:', session);
      setMessages([]);
    } catch (error) {
      console.error('[CorrelationAIPane] Error creating session:', error);
      alert('Failed to create session. Check console for details.');
    }
  };

  const handleSessionSelect = async (session: AnalysisSession) => {
    setCurrentSession(session);
    try {
      const sessionMessages = await analysisSessionsApi.getSessionMessages(session.id, 100, 0);
      setMessages(sessionMessages);
    } catch (error) {
      console.error('Error loading session messages:', error);
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
      alert('Could not start a session for upload. Check backend/tunnel and try again.');
    }
  };

  const handleSendMessage = async () => {
    if (!input.trim() || isLoading) return;

    let activeSession: AnalysisSession;
    try {
      activeSession = await ensureActiveSession();
    } catch (error) {
      console.error('Error ensuring session before chat:', error);
      alert('Could not create or load a session. Check backend/tunnel and try again.');
      return;
    }

    const userText = input.trim();
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

    const appendAssistantMessage = (response: any, sessionId: string) => {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          session_id: sessionId,
          role: response.role,
          content: response.content,
          analysis: response.analysis,
          risk_score: normalizeRiskScore(response.risk_score),
          domains: response.domains,
          actions: response.actions,
          timestamp: response.timestamp
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
      
      // Title generation is cosmetic; never turn a successful assistant reply into a chat error.
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
      setIsLoading(false);
    }
  };

  const handleSessionMissingForUpload = async () => {
    try {
      const session = await createReplacementSession();
      setMessages([]);
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
              <TooltipContent>Automatically create Kanban tasks from AI recommendations</TooltipContent>
            </Tooltip>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden p-4 bg-[#161616]">
          {!currentSession ? (
            <div className="h-full min-h-0 rounded-xl border border-gray-300 bg-white text-center text-gray-900 flex flex-col items-center justify-center px-8">
              <Plus className="w-12 h-12 mb-4 text-gray-400" />
              <p className="text-lg font-medium mb-2">Create a new session to start</p>
              <p className="text-sm text-gray-600">
                Sessions allow you to organize your analysis with data sources and context.
              </p>
            </div>
          ) : messages.length === 0 ? (
            <div className="h-full min-h-0 rounded-xl border border-gray-300 bg-white text-center text-gray-900 flex flex-col items-center justify-center px-8">
              <p className="text-lg font-medium mb-2">Start the conversation</p>
              <p className="text-sm max-w-md text-gray-600">
                Ask me anything about your operations, upload data, and I'll provide actionable insights.
              </p>
            </div>
          ) : (
            <div className="space-y-4 overflow-x-hidden">
              {messages.map((message, index) => (
                <div
                  key={index}
                  className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[80%] rounded-lg p-4 ${
                      message.role === 'user'
                        ? 'bg-blue-500 text-white'
                        : 'bg-white text-gray-900 border border-gray-200 shadow-sm'
                    }`}
                  >
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

                    <p className={`text-sm whitespace-pre-wrap ${message.role === 'assistant' ? 'text-gray-900' : 'text-white'}`}>
                      {message.content}
                    </p>

                    {message.actions && message.actions.length > 0 && (
                      <div className="mt-3 pt-3 border-t border-gray-200">
                        <p className="text-xs font-medium text-gray-700 mb-2">Recommended Actions:</p>
                        <ul className="text-xs space-y-1">
                          {message.actions.map((action, idx) => (
                            <li key={idx} className="flex items-start gap-2">
                              <CheckCircle className="w-3 h-3 mt-0.5 text-green-500" />
                              <span>{action.description || JSON.stringify(action)}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <p className="text-xs mt-2 opacity-70">
                      {new Date(message.timestamp).toLocaleTimeString()}
                    </p>
                  </div>
                </div>
              ))}
              {isLoading && (
                <div className="flex justify-start">
                  <div className="bg-white border border-gray-200 shadow-sm rounded-lg p-4">
                    <div className="flex items-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin text-blue-500" />
                      <span className="text-sm text-gray-600">Analyzing...</span>
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
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Ask about operational issues, correlations, or recommendations..."
              disabled={isLoading}
              className="flex-1 min-w-0"
            />
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
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
