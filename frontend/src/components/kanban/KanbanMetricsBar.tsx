/**
 * KanbanMetricsBar - Quick stats bar for kanban board
 */

import React from 'react';
import { KanbanMetrics } from '../../stores/kanbanStore';
import { CheckCircle2, Clock, AlertCircle, Activity, Users } from 'lucide-react';

interface KanbanMetricsBarProps {
  metrics: KanbanMetrics;
  className?: string;
}

export const KanbanMetricsBar: React.FC<KanbanMetricsBarProps> = ({
  metrics,
  className = '',
}) => {
  const statCards = [
    {
      label: 'Total Tasks',
      value: metrics.total_tasks,
      icon: Activity,
      color: 'text-blue-600 dark:text-blue-400',
      bgColor: 'bg-blue-50 dark:bg-blue-900/20',
    },
    {
      label: 'Completed Today',
      value: metrics.tasks_completed_today,
      icon: CheckCircle2,
      color: 'text-green-600 dark:text-green-400',
      bgColor: 'bg-green-50 dark:bg-green-900/20',
    },
    {
      label: 'Awaiting Approval',
      value: metrics.tasks_awaiting_approval,
      icon: Clock,
      color: 'text-yellow-600 dark:text-yellow-400',
      bgColor: 'bg-yellow-50 dark:bg-yellow-900/20',
    },
    {
      label: 'Overdue',
      value: metrics.overdue_tasks,
      icon: AlertCircle,
      color: 'text-red-600 dark:text-red-400',
      bgColor: 'bg-red-50 dark:bg-red-900/20',
    },
    {
      label: 'Active Escalations',
      value: metrics.active_escalations,
      icon: Users,
      color: 'text-orange-600 dark:text-orange-400',
      bgColor: 'bg-orange-50 dark:bg-orange-900/20',
    },
  ];

  return (
    <div className={`flex flex-wrap gap-3 ${className}`}>
      {statCards.map((stat) => {
        const Icon = stat.icon;
        return (
          <div
            key={stat.label}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg ${stat.bgColor}`}
          >
            <Icon className={`w-4 h-4 ${stat.color}`} />
            <div>
              <div className={`text-lg font-semibold ${stat.color}`}>
                {stat.value}
              </div>
              <div className="text-xs text-gray-600 dark:text-gray-400">
                {stat.label}
              </div>
            </div>
          </div>
        );
      })}

      {/* Cycle Time */}
      {metrics.avg_cycle_time_minutes && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-purple-50 dark:bg-purple-900/20">
          <Clock className="w-4 h-4 text-purple-600 dark:text-purple-400" />
          <div>
            <div className="text-lg font-semibold text-purple-600 dark:text-purple-400">
              {formatCycleTime(metrics.avg_cycle_time_minutes)}
            </div>
            <div className="text-xs text-gray-600 dark:text-gray-400">
              Avg Cycle Time
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// Helper function to format cycle time
function formatCycleTime(minutes: number): string {
  if (minutes < 60) {
    return `${Math.round(minutes)}m`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    return `${hours}h`;
  }
  const days = Math.round(hours / 24);
  return `${days}d`;
}

export default KanbanMetricsBar;
