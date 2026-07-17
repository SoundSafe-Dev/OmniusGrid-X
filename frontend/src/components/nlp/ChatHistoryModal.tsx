import React, { useState, useEffect } from 'react';
import { analysisSessionsApi, SessionMessage, AnalysisSession } from '../../api/analysisSessions';
import { X, Search, Calendar } from 'lucide-react';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { Badge } from '../ui/Badge';

interface ChatHistoryModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const ChatHistoryModal: React.FC<ChatHistoryModalProps> = ({
  isOpen,
  onClose
}) => {
  const [messages, setMessages] = useState<SessionMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [sessionIdFilter, setSessionIdFilter] = useState<string | undefined>();
  const [sessions, setSessions] = useState<AnalysisSession[]>([]);

  useEffect(() => {
    if (isOpen) {
      loadSessions();
      loadChatHistory();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing; adding deps changes retrigger behavior (FS-54)
  }, [isOpen, sessionIdFilter]);

  const loadSessions = async () => {
    try {
      const response = await analysisSessionsApi.listSessions(50, 0, 'active');
      setSessions(response.sessions);
    } catch (error) {
      console.error('Error loading sessions:', error);
    }
  };

  const loadChatHistory = async () => {
    setIsLoading(true);
    try {
      const history = await analysisSessionsApi.getChatHistory(100, 0, sessionIdFilter);
      setMessages(history);
    } catch (error) {
      console.error('Error loading chat history:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      loadChatHistory();
      return;
    }

    setIsLoading(true);
    try {
      const results = await analysisSessionsApi.searchChatHistory(searchQuery, 50, 0, sessionIdFilter);
      setMessages(results);
    } catch (error) {
      console.error('Error searching chat history:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  const getSessionTitle = (sessionId: string) => {
    const session = sessions.find(s => s.id === sessionId);
    return session?.title || 'Unknown Session';
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-opsgrid-panel rounded-lg shadow-xl w-full max-w-4xl max-h-[80vh] flex flex-col">
        <div className="p-4 border-b border-opsgrid-border flex items-center justify-between">
          <h2 className="text-lg font-semibold text-opsgrid-text">Chat History</h2>
          <Button variant="outline" size="sm" onClick={onClose}>
            <X className="w-4 h-4" />
          </Button>
        </div>

        <div className="p-4 border-b border-opsgrid-border">
          <div className="flex gap-3">
            <div className="relative flex-1">
              <Search className="w-4 h-4 absolute left-3 top-1/2 transform -translate-y-1/2 text-opsgrid-text-secondary" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="Search chat history..."
                className="pl-9"
              />
            </div>
            <select
              value={sessionIdFilter || ''}
              onChange={(e) => setSessionIdFilter(e.target.value || undefined)}
              className="px-3 py-2 border border-opsgrid-border rounded-md bg-opsgrid-bg text-opsgrid-text text-sm"
            >
              <option value="">All Sessions</option>
              {sessions.map(session => (
                <option key={session.id} value={session.id}>
                  {session.title}
                </option>
              ))}
            </select>
            <Button onClick={handleSearch} disabled={isLoading}>
              Search
            </Button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {isLoading ? (
            <div className="text-center text-opsgrid-text-secondary py-8">Loading...</div>
          ) : messages.length === 0 ? (
            <div className="text-center text-opsgrid-text-secondary py-8">
              No chat history found
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`p-4 rounded-lg ${
                    message.role === 'user'
                      ? 'bg-blue-500/10 border border-blue-500/20 ml-8'
                      : 'bg-opsgrid-bg border border-opsgrid-border'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <Badge variant={message.role === 'user' ? 'info' : 'neutral'} className="text-xs">
                      {message.role === 'user' ? 'You' : 'AI Assistant'}
                    </Badge>
                    <span className="text-xs text-opsgrid-text-secondary">
                      {getSessionTitle(message.session_id)}
                    </span>
                    <div className="flex items-center gap-1 text-xs text-opsgrid-text-secondary ml-auto">
                      <Calendar className="w-3 h-3" />
                      {new Date(message.timestamp).toLocaleString()}
                    </div>
                  </div>
                  <p className="text-sm text-opsgrid-text whitespace-pre-wrap">{message.content}</p>
                  {message.domains && message.domains.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      {message.domains.map((domain) => (
                        <Badge key={domain} variant="info" className="text-xs">
                          {domain}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
