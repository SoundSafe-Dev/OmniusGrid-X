import React, { useState, useEffect } from 'react';
import { analysisSessionsApi, AnalysisSession } from '../../api/analysisSessions';
import { Plus, Trash2, Clock, FileText, MessageSquare } from 'lucide-react';
import { Button } from '../ui/Button';

interface SessionListProps {
  onSessionSelect: (session: AnalysisSession) => void;
  onNewSession: () => void;
  currentSessionId?: string;
  className?: string;
}

export const SessionList: React.FC<SessionListProps> = ({
  onSessionSelect,
  onNewSession,
  currentSessionId,
  className = ''
}) => {
  const [sessions, setSessions] = useState<AnalysisSession[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    loadSessions();
  }, []);

  const loadSessions = async () => {
    setIsLoading(true);
    try {
      const response = await analysisSessionsApi.listSessions(50, 0, 'active');
      setSessions(response.sessions);
    } catch (error) {
      console.error('Error loading sessions:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDeleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await analysisSessionsApi.deleteSession(sessionId);
      setSessions(sessions.filter(s => s.id !== sessionId));
    } catch (error) {
      console.error('Error deleting session:', error);
    }
  };

  const filteredSessions = sessions.filter(session =>
    session.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (session.description && session.description.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  return (
    <div className={`flex flex-col h-full ${className}`}>
      <div className="p-4 border-b border-opsgrid-border">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-opsgrid-text">Sessions</h3>
          <Button size="sm" onClick={onNewSession}>
            <Plus className="w-4 h-4 mr-1" />
            New
          </Button>
        </div>
        <input
          type="text"
          placeholder="Search sessions..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full px-3 py-2 text-sm border border-opsgrid-border rounded-md bg-opsgrid-bg text-opsgrid-text"
        />
      </div>

      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="p-4 text-center text-opsgrid-text-secondary text-sm">
            Loading sessions...
          </div>
        ) : filteredSessions.length === 0 ? (
          <div className="p-4 text-center text-opsgrid-text-secondary text-sm">
            No sessions found
          </div>
        ) : (
          <div className="p-2 space-y-1">
            {filteredSessions.map((session) => (
              <div
                key={session.id}
                onClick={() => onSessionSelect(session)}
                className={`p-3 rounded-lg cursor-pointer transition-colors ${
                  currentSessionId === session.id
                    ? 'bg-opsgrid-primary/20 border border-opsgrid-primary'
                    : 'hover:bg-opsgrid-border'
                }`}
              >
                <div className="flex items-start justify-between mb-2">
                  <h4 className="text-sm font-medium text-opsgrid-text line-clamp-2">
                    {session.title}
                  </h4>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={(e) => handleDeleteSession(session.id, e)}
                    className="ml-2 px-2"
                  >
                    <Trash2 className="w-3 h-3" />
                  </Button>
                </div>
                {session.description && (
                  <p className="text-xs text-opsgrid-text-secondary line-clamp-2 mb-2">
                    {session.description}
                  </p>
                )}
                <div className="flex items-center gap-3 text-xs text-opsgrid-text-secondary">
                  <div className="flex items-center gap-1">
                    <MessageSquare className="w-3 h-3" />
                    <span>{session.messages_count}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <FileText className="w-3 h-3" />
                    <span>{session.data_sources_count}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    <span>{new Date(session.last_accessed_at).toLocaleDateString()}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
