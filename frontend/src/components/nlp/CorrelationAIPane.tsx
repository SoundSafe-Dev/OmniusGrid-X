import React, { useState, useRef, useEffect } from 'react';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { Badge } from '../ui/Badge';
import { Tooltip, TooltipTrigger, TooltipContent } from '../ui';
import { analysisSessionsApi, AnalysisSession, SessionMessage } from '../../api/analysisSessions';
import { SessionList } from './SessionList';
import { DataSourcesPanel } from './DataSourcesPanel';
import { IntakeSelectorDialog } from './IntakeSelectorDialog';
import { ChatHistoryModal } from './ChatHistoryModal';
import { ContextPanel } from './ContextPanel';
import { RealTimeDataPanel } from './RealTimeDataPanel';
import { Send, Loader2, CheckCircle, History, Inbox, Plus } from 'lucide-react';

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
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleCreateNewSession = async () => {
    try {
      console.log('[CorrelationAIPane] Creating new session...');
      const session = await analysisSessionsApi.createSession({});
      console.log('[CorrelationAIPane] Session created:', session);
      setCurrentSession(session);
      setMessages([]);
      // Force refresh session list
      console.log('[CorrelationAIPane] Refreshing session list, key:', sessionListKey + 1);
      setSessionListKey(prev => prev + 1);
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

  const handleSendMessage = async () => {
    if (!input.trim() || !currentSession || isLoading) return;

    setIsLoading(true);
    try {
      const response = await analysisSessionsApi.sessionChat(currentSession.id, {
        message: input,
        auto_integrate: autoIntegrate
      });

      const assistantMessage: SessionMessage = {
        id: crypto.randomUUID(),
        session_id: currentSession.id,
        role: response.role,
        content: response.content,
        analysis: response.analysis,
        risk_score: response.risk_score,
        domains: response.domains,
        actions: response.actions,
        timestamp: response.timestamp
      };

      setMessages(prev => [...prev, assistantMessage]);
      
      // Auto-generate title after first few messages
      if (messages.length === 2) {
        await analysisSessionsApi.generateSessionTitle(currentSession.id);
        const updatedSession = await analysisSessionsApi.getSession(currentSession.id);
        setCurrentSession(updatedSession);
      }
    } catch (error) {
      console.error('Error sending message:', error);
    } finally {
      setInput('');
      setIsLoading(false);
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

  return (
    <div className={`flex h-[calc(100vh-2rem)] gap-4 ${className}`}>
      {/* Left Sidebar - Sessions and Data Sources */}
      <div className="w-72 flex flex-col gap-4">
        <SessionList
          key={sessionListKey}
          onSessionSelect={handleSessionSelect}
          onNewSession={handleCreateNewSession}
          currentSessionId={currentSession?.id}
        />
        {currentSession && (
          <DataSourcesPanel
            key={dataSourcesKey}
            sessionId={currentSession.id}
            onDataSourceAdded={() => {/* Refresh */}}
          />
        )}
      </div>

      {/* Center - Chat Interface */}
      <Card className="flex-1 flex flex-col">
        <div className="p-4 border-b border-opsgrid-border flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-opsgrid-text">
              {currentSession?.title || 'Correlation AI Assistant'}
            </h2>
            {currentSession && (
              <Badge variant="neutral" className="text-xs">
                {currentSession.data_sources_count} sources
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="sm" onClick={() => setShowIntakeDialog(true)}>
                  <Inbox className="w-4 h-4 mr-2" />
                  Add Data
                </Button>
              </TooltipTrigger>
              <TooltipContent>Upload operational data for AI analysis</TooltipContent>
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

        <div className="flex-1 overflow-y-auto p-4 bg-gray-50">
          {!currentSession ? (
            <div className="text-center text-gray-500 py-8">
              <Plus className="w-12 h-12 mx-auto mb-4 text-gray-400" />
              <p className="text-lg font-medium mb-2">Create a new session to start</p>
              <p className="text-sm">
                Sessions allow you to organize your analysis with data sources and context.
              </p>
            </div>
          ) : messages.length === 0 ? (
            <div className="text-center text-gray-500 py-8">
              <p className="text-lg font-medium mb-2">Start the conversation</p>
              <p className="text-sm">
                Ask me anything about your operations, upload data, and I'll provide actionable insights.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((message, index) => (
                <div
                  key={index}
                  className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[80%] rounded-lg p-4 ${
                      message.role === 'user'
                        ? 'bg-blue-500 text-white'
                        : 'bg-white border border-gray-200 shadow-sm'
                    }`}
                  >
                    {message.role === 'assistant' && message.risk_score !== undefined && (
                      <div className="mb-3">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Badge variant={getRiskScoreVariant(message.risk_score)}>
                              {getRiskScoreLabel(message.risk_score)} Risk: {message.risk_score.toFixed(1)}/100
                            </Badge>
                          </TooltipTrigger>
                          <TooltipContent>AI-assessed risk severity (0-100)</TooltipContent>
                        </Tooltip>
                      </div>
                    )}

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

                    <p className="text-sm whitespace-pre-wrap">{message.content}</p>

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

        <div className="p-4 border-t border-opsgrid-border">
          <div className="flex gap-2">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder={currentSession ? "Ask about operational issues, correlations, or recommendations..." : "Create a session to start"}
              disabled={!currentSession || isLoading}
              className="flex-1"
            />
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  onClick={handleSendMessage}
                  disabled={!currentSession || isLoading || !input.trim()}
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
      </Card>

      {/* Right Sidebar - Context and Real-Time Data */}
      <div className="w-72 flex flex-col gap-4">
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
