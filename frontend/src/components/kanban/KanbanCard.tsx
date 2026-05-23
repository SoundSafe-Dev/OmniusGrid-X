/**
 * KanbanCard - Individual task card component
 */

import React from 'react';
import { Task } from '../../stores/kanbanStore';
import {
  AlertCircle,
  Clock,
  CheckSquare,
  MessageSquare,
  Wrench,
  Factory,
  ShieldCheck,
  AlertTriangle,
  Play,
  Package,
  ArrowRightLeft,
  Settings,
  User as UserIcon
} from 'lucide-react';

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
    e.dataTransfer.setData('text/plain', task.id);
    onDragStart();
  };

  // Calculate checklist progress
  const checklistTotal = task.checklist_items?.length || 0;
  const checklistCompleted = task.checklist_items?.filter((i: { completed: boolean }) => i.completed).length || 0;

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

  // Type labels and icons
  const typeConfig: Record<string, { label: string; icon: any; color: string }> = {
    production_job: { label: 'Production', icon: Factory, color: 'bg-blue-100 text-blue-600' },
    maintenance_pm: { label: 'Preventive', icon: Wrench, color: 'bg-green-100 text-green-600' },
    maintenance_cm: { label: 'Corrective', icon: Wrench, color: 'bg-orange-100 text-orange-600' },
    quality_inspection: { label: 'Quality', icon: ShieldCheck, color: 'bg-purple-100 text-purple-600' },
    safety_check: { label: 'Safety', icon: ShieldCheck, color: 'bg-red-100 text-red-600' },
    alarm_response: { label: 'Alarm', icon: AlertTriangle, color: 'bg-red-200 text-red-700' },
    command_execution: { label: 'Command', icon: Play, color: 'bg-indigo-100 text-indigo-600' },
    material_request: { label: 'Material', icon: Package, color: 'bg-yellow-100 text-yellow-600' },
    changeover: { label: 'Changeover', icon: ArrowRightLeft, color: 'bg-teal-100 text-teal-600' },
    custom: { label: 'Custom', icon: Settings, color: 'bg-gray-100 text-gray-600' },
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
          {(() => {
            const config = typeConfig[task.task_type] || typeConfig.custom;
            const Icon = config.icon;
            return (
              <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${config.color} dark:bg-opacity-20`}>
                <Icon className="w-3 h-3 mr-1" />
                {config.label}
              </span>
            );
          })()}
          
          {isOverdue && (
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400">
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
              <span className="text-gray-500 dark:text-gray-400">Progress</span>
              <span className={`font-medium ${
                task.progress_percent === 100 ? 'text-green-600' : 'text-gray-700 dark:text-gray-300'
              }`}>{task.progress_percent}%</span>
            </div>
            <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  task.progress_percent === 100 
                    ? 'bg-gradient-to-r from-green-400 to-green-600' 
                    : 'bg-gradient-to-r from-blue-400 to-blue-600'
                }`}
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
              <div className="flex items-center gap-1.5">
                <div className="w-5 h-5 rounded-full bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center text-white text-[10px] font-medium">
                  DA
                </div>
                <span className="text-xs text-gray-600 dark:text-gray-400">Dev Admin</span>
              </div>
            ) : (
              <div className="flex items-center gap-1.5">
                <div className="w-5 h-5 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center">
                  <UserIcon className="w-3 h-3 text-gray-400" />
                </div>
                <span className="text-xs text-gray-400 italic">Unassigned</span>
              </div>
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
