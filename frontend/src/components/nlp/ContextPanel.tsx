import React from 'react';
import { User, Target, Settings } from 'lucide-react';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';

interface ContextPanelProps {
  userContext?: {
    role?: string;
    department?: string;
    priorities?: string[];
  };
  goals?: Array<{
    title: string;
    progress: number;
    deadline?: string;
  }>;
  className?: string;
}

export const ContextPanel: React.FC<ContextPanelProps> = ({
  userContext,
  goals = [],
  className = ''
}) => {
  return (
    <div className={`flex flex-col h-full ${className}`}>
      <div className="p-4 border-b border-opsgrid-border">
        <h3 className="text-sm font-semibold text-opsgrid-text mb-3">Context</h3>
        
        {/* User Context */}
        {userContext && (
          <div className="space-y-2 mb-4">
            <div className="flex items-center gap-2">
              <User className="w-4 h-4 text-opsgrid-text-secondary" />
              <div className="flex-1">
                <p className="text-xs text-opsgrid-text-secondary">Role</p>
                <p className="text-sm text-opsgrid-text">{userContext.role || 'Not set'}</p>
              </div>
            </div>
            {userContext.department && (
              <div>
                <p className="text-xs text-opsgrid-text-secondary mb-1">Department</p>
                <p className="text-sm text-opsgrid-text">{userContext.department}</p>
              </div>
            )}
            {userContext.priorities && userContext.priorities.length > 0 && (
              <div>
                <p className="text-xs text-opsgrid-text-secondary mb-1">Priorities</p>
                <div className="flex flex-wrap gap-1">
                  {userContext.priorities.map((priority) => (
                    <Badge key={priority} variant="info" className="text-xs">
                      {priority}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Goals Section */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="flex items-center gap-2 mb-3">
          <Target className="w-4 h-4 text-opsgrid-text-secondary" />
          <h3 className="text-sm font-semibold text-opsgrid-text">Active Goals</h3>
        </div>
        
        {goals.length === 0 ? (
          <p className="text-xs text-opsgrid-text-secondary">No active goals</p>
        ) : (
          <div className="space-y-3">
            {goals.map((goal, index) => (
              <div key={index} className="p-3 bg-opsgrid-bg rounded border border-opsgrid-border">
                <div className="flex items-start justify-between mb-2">
                  <p className="text-sm font-medium text-opsgrid-text flex-1">{goal.title}</p>
                  <Badge variant={goal.progress >= 75 ? 'success' : goal.progress >= 50 ? 'warning' : 'info'} className="text-xs">
                    {goal.progress}%
                  </Badge>
                </div>
                <div className="w-full bg-opsgrid-border rounded-full h-2 mb-2">
                  <div
                    className="bg-opsgrid-primary h-2 rounded-full transition-all"
                    style={{ width: `${goal.progress}%` }}
                  />
                </div>
                {goal.deadline && (
                  <p className="text-xs text-opsgrid-text-secondary">
                    Deadline: {new Date(goal.deadline).toLocaleDateString()}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="p-4 border-t border-opsgrid-border">
        <Button variant="outline" size="sm" className="w-full">
          <Settings className="w-4 h-4 mr-2" />
          Manage Context
        </Button>
      </div>
    </div>
  );
};
