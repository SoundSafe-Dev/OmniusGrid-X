import React, { useState, useEffect } from 'react';
import { analysisSessionsApi, AnalysisSession } from '../../api/analysisSessions';
import { Plus, Trash2, Clock, FileText, MessageSquare, RefreshCw } from 'lucide-react';
import { Button } from '../ui/Button';
import { useDialog } from '../ui';

interface SessionListProps {
  onSessionSelect: (session: AnalysisSession) => void;
  onNewSession: () => void;
  currentSessionId?: string;
  className?: string;
  refreshTrigger?: number;
}

export const SessionList: React.FC<SessionListProps> = ({
  onSessionSelect,
  onNewSession,
  currentSessionId,
  className = '',
  refreshTrigger
}) => {
  const { confirm, alert } = useDialog();
  const [sessions, setSessions] = useState<AnalysisSession[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  // The catch below already clears the list "to avoid showing stale data", which is right —
  // and left "No sessions found" as the only thing on screen. Clearing and saying nothing
  // happened are different acts.
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const loadSessions = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await analysisSessionsApi.listSessions(50, 0, 'active');
      setSessions(response.sessions);
    } catch (error) {
      console.error('[SessionList] Error loading sessions:', error);
      // On error, clear sessions to avoid showing stale data
      setSessions([]);
      setError('Could not load sessions.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadSessions();
  }, [refreshTrigger]);

  const handleDeleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    // Immediately remove from local state for better UX
    setSessions(sessions.filter(s => s.id !== sessionId));
    
    try {
      await analysisSessionsApi.deleteSession(sessionId);
      // Reload sessions to ensure backend state is reflected
      await loadSessions();
    } catch (error: any) {
      console.error('Error deleting session:', error);
      // If session doesn't exist (404), it's already gone, which is fine
      if (error.response?.status !== 404) {
        // On other errors, reload to sync state
        await loadSessions();
      }
    }
  };

  const handleCleanupOrphaned = async () => {
    const ok = await confirm({
      title: 'Delete all sessions',
      message: 'This will delete ALL sessions to fix database corruption. Continue?',
      confirmLabel: 'Delete all',
      destructive: true,
    });
    if (!ok) return;

    try {
      const result = await analysisSessionsApi.cleanupOrphanedSessions();
      await alert({
        title: 'Cleanup complete',
        message: `Cleaned up ${result.deleted_count} orphaned sessions.`,
      });
      await loadSessions();
    } catch (error) {
      console.error('[SessionList] Error cleaning up orphaned sessions:', error);
      await alert({
        title: 'Cleanup failed',
        message: 'Failed to clean up orphaned sessions. Check the console for details.',
      });
    }
  };

  const filteredSessions = sessions.filter(session =>
    session.title?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (session.description && session.description.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  return (
    <div className={`flex flex-col h-full ${className}`}>
      <div className="p-4 border-b border-opsgrid-border">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-opsgrid-text">Sessions</h3>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={handleCleanupOrphaned}>
              <RefreshCw className="w-4 h-4 mr-1" />
              Clean
            </Button>
            <Button size="sm" onClick={onNewSession}>
              <Plus className="w-4 h-4 mr-1" />
              New
            </Button>
          </div>
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
        ) : error ? (
          <div className="p-4 text-center text-status-alarm text-sm">{error}</div>
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
