/**
 * KanbanCard - Individual task card component
 */

import React from 'react';
import { Task } from '../../stores/kanbanStore';
import { AlertCircle, Clock, User, CheckSquare, Paperclip, MessageSquare } from 'lucide-react';

interface KanbanCardProps {
  task: Task;
  index: number;
  onClick: () => void;
  onDragStart: () => void;
}

export const KanbanCard: React.FC<KanbanCardProps> = ({
  task,
  onClick,
  onDragStart,
}) => {
  const handleDragStart = (e: React.DragEvent) => {
    e.dataTransfer.effectAllowed = 'move';
    onDragStart();
  };

  // Calculate checklist progress
  const checklistTotal = task.checklist_items?.length || 0;
  const checklistCompleted = task.checklist_items?.filter((i: { completed: boolean }) => i.completed).length || 0;
  const checklistProgress = checklistTotal > 0 ? (checklistCompleted / checklistTotal) * 100 : 0;

  // Check if overdue
  const isOverdue = task.due_date && new Date(task.due_date) < new Date() && task.status !== 'completed';

  // Priority colors
  const priorityColors: Record<string, string> = {
    low: 'bg-gray-100 text-gray-600 border-gray-300',
    medium: 'bg-blue-100 text-blue-600 border-blue-300',
    high: 'bg-orange-100 text-orange-600 border-orange-300',
    critical: 'bg-red-100 text-red-600 border-red-300',
    emergency: 'bg-red-200 text-red-700 border-red-400 animate-pulse',
  };

  // Type labels
  const typeLabels: Record<string, string> = {
    production_job: 'Production',
    maintenance_pm: 'Preventive Maintenance',
    maintenance_cm: 'Corrective Maintenance',
    quality_inspection: 'Quality Check',
    safety_check: 'Safety Audit',
    alarm_response: 'Alarm Response',
    command_execution: 'Command',
    material_request: 'Material Request',
    changeover: 'Changeover',
    custom: 'Custom',
  };

  return (
    <div
      draggable
      onDragStart={handleDragStart}
      onClick={onClick}
      className={`bg-white dark:bg-gray-800 rounded-lg shadow-sm border cursor-pointer hover:shadow-md transition-shadow group ${
        isOverdue ? 'border-red-300 dark:border-red-600' : 'border-gray-200 dark:border-gray-700'
      } ${task.approval_status === 'pending' ? 'ring-1 ring-yellow-400' : ''}`}
    >
      {/* Card Header - Priority Indicator */}
      <div className={`h-1 rounded-t-lg ${priorityColors[task.priority].split(' ')[0]}`} />

      <div className="p-3 space-y-2">
        {/* Title & Priority */}
        <div className="flex items-start justify-between gap-2">
          <h4 className="font-medium text-gray-900 dark:text-white text-sm leading-tight line-clamp-2">
            {task.title}
          </h4>
          {task.approval_status === 'pending' && (
            <span className="flex-shrink-0 px-1.5 py-0.5 text-xs font-medium bg-yellow-100 text-yellow-800 rounded">
              Pending
            </span>
          )}
        </div>

        {/* Task Type Badge */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
            {typeLabels[task.task_type] || task.task_type}
          </span>
          
          {isOverdue && (
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-600">
              <AlertCircle className="w-3 h-3 mr-1" />
              Overdue
            </span>
          )}
        </div>

        {/* Description Preview */}
        {task.description && (
          <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
            {task.description}
          </p>
        )}

        {/* Progress Bar */}
        {task.progress_percent > 0 && (
          <div className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-gray-500">Progress</span>
              <span className="text-gray-700 dark:text-gray-300">{task.progress_percent}%</span>
            </div>
            <div className="h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all"
                style={{ width: `${task.progress_percent}%` }}
              />
            </div>
          </div>
        )}

        {/* Checklist Progress */}
        {checklistTotal > 0 && (
          <div className="flex items-center gap-1 text-xs text-gray-500">
            <CheckSquare className="w-3 h-3" />
            <span>{checklistCompleted}/{checklistTotal}</span>
          </div>
        )}

        {/* Footer - Metadata */}
        <div className="flex items-center justify-between pt-2 border-t border-gray-100 dark:border-gray-700">
          <div className="flex items-center gap-2">
            {/* Assignee */}
            {task.assigned_to ? (
              <div className="flex items-center gap-1 text-xs text-gray-500">
                <User className="w-3 h-3" />
                <span>Assigned</span>
              </div>
            ) : (
              <span className="text-xs text-gray-400 italic">Unassigned</span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {/* Time Logged */}
            {task.time_logged_minutes > 0 && (
              <div className="flex items-center gap-1 text-xs text-gray-500">
                <Clock className="w-3 h-3" />
                <span>{formatDuration(task.time_logged_minutes)}</span>
              </div>
            )}

            {/* Due Date */}
            {task.due_date && (
              <div className={`text-xs ${isOverdue ? 'text-red-500 font-medium' : 'text-gray-500'}`}>
                {new Date(task.due_date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
              </div>
            )}

            {/* Comments indicator (placeholder) */}
            <div className="flex items-center gap-1 text-xs text-gray-400">
              <MessageSquare className="w-3 h-3" />
            </div>
          </div>
        </div>

        {/* Linked Entities */}
        {(task.asset_id || task.alarm_id || task.operation_id) && (
          <div className="flex items-center gap-1 pt-1">
            {task.asset_id && (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-indigo-100 text-indigo-600">
                Asset
              </span>
            )}
            {task.alarm_id && (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-red-100 text-red-600">
                Alarm
              </span>
            )}
            {task.operation_id && (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-green-100 text-green-600">
                Operation
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

// Helper function to format duration
function formatDuration(minutes: number): string {
  if (minutes < 60) {
    return `${minutes}m`;
  }
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (remainingMinutes === 0) {
    return `${hours}h`;
  }
  return `${hours}h ${remainingMinutes}m`;
}

export default KanbanCard;
