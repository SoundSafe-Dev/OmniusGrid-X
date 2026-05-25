/**
 * KanbanColumn - Individual column component for kanban board
 */

import React, { useState } from 'react';
import { TaskColumn as TaskColumnType, Task } from '../../stores/kanbanStore';
import { KanbanCard } from './KanbanCard';
import { AlertCircle, ChevronDown, ChevronRight } from 'lucide-react';
import { Tooltip, TooltipTrigger, TooltipContent } from '../ui';

interface KanbanColumnProps {
  column: TaskColumnType;
  tasks: Task[];
  onTaskClick: (taskId: string) => void;
  onDragStart: (taskId: string) => void;
  onDragOver: (columnId: string) => void;
  onDragLeave: () => void;
  onDrop: (columnId: string) => void;
  isDragOver: boolean;
}

// Task type labels for display
const typeLabels: Record<string, string> = {
  production_job: 'Production',
  maintenance_pm: 'Preventive Maint.',
  maintenance_cm: 'Corrective Maint.',
  quality_inspection: 'Quality',
  safety_check: 'Safety',
  alarm_response: 'Alarm',
  command_execution: 'Command',
  material_request: 'Material',
  changeover: 'Changeover',
  custom: 'Custom',
};

export const KanbanColumn: React.FC<KanbanColumnProps> = ({
  column,
  tasks,
  onTaskClick,
  onDragStart,
  onDragOver,
  onDragLeave,
  onDrop,
  isDragOver,
}) => {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onDragOver(column.id);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onDrop(column.id);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    // Only trigger if actually leaving the column (not just entering a child element)
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX;
    const y = e.clientY;

    if (x < rect.left || x >= rect.right || y < rect.top || y >= rect.bottom) {
      onDragLeave();
    }
  };

  const toggleGroup = (taskType: string) => {
    setCollapsedGroups((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(taskType)) {
        newSet.delete(taskType);
      } else {
        newSet.add(taskType);
      }
      return newSet;
    });
  };

  const wipWarning = column.wip_limit > 0 && tasks.length > column.wip_limit;

  const getColumnDescription = (columnType: string) => {
    switch (columnType) {
      case 'backlog': return 'Tasks awaiting prioritization';
      case 'triage': return 'Tasks being assessed and prioritized';
      case 'in_progress': return 'Tasks currently being worked on';
      case 'review': return 'Tasks awaiting approval or verification';
      case 'done': return 'Completed tasks';
      case 'rejected': return 'Tasks that were cancelled or rejected';
      default: return columnType;
    }
  };

  // Group tasks by type
  const groupedTasks = tasks.reduce((acc: Record<string, Task[]>, task) => {
    const type = task.task_type;
    if (!acc[type]) {
      acc[type] = [];
    }
    acc[type].push(task);
    return acc;
  }, {});

  return (
    <div
      className={`flex flex-col w-80 min-w-[320px] max-w-[320px] rounded-lg transition-colors ${
        isDragOver ? 'bg-blue-50 dark:bg-blue-900/20 ring-2 ring-blue-400' : ''
      }`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Column Header */}
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className="flex items-center justify-between p-3 rounded-t-lg"
            style={{ backgroundColor: column.color + '20' }}
          >
            <div className="flex items-center gap-2">
              <div
                className="w-3 h-3 rounded-full"
                style={{ backgroundColor: column.color }}
              />
              <h3 className="font-semibold text-gray-900 dark:text-white text-sm">
                {column.name}
              </h3>
              <span className="text-xs text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-700 px-2 py-0.5 rounded-full">
                {tasks.length}
              </span>
            </div>

            <div className="flex items-center gap-2">
              {wipWarning && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="flex items-center text-orange-600 dark:text-orange-400">
                      <AlertCircle className="w-4 h-4" />
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>WIP limit exceeded</TooltipContent>
                </Tooltip>
              )}
              <button className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                <ChevronDown className="w-4 h-4" />
              </button>
            </div>
          </div>
        </TooltipTrigger>
        <TooltipContent>{getColumnDescription(column.column_type)}</TooltipContent>
      </Tooltip>

      {/* WIP Limit Indicator */}
      {column.wip_limit > 0 && (
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="px-3 py-1 bg-gray-50 dark:bg-gray-800/50 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-gray-500 dark:text-gray-400">WIP Limit</span>
                <span className={`font-medium ${wipWarning ? 'text-orange-600' : 'text-gray-700 dark:text-gray-300'}`}>
                  {tasks.length} / {column.wip_limit}
                </span>
              </div>
              <div className="mt-1 h-1 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${
                    wipWarning ? 'bg-orange-500' : 'bg-green-500'
                  }`}
                  style={{ width: `${Math.min((tasks.length / column.wip_limit) * 100, 100)}%` }}
                />
              </div>
            </div>
          </TooltipTrigger>
          <TooltipContent>Work In Progress limit: maximum {column.wip_limit} tasks in this column</TooltipContent>
        </Tooltip>
      )}

      {/* Tasks Container */}
      <div
        className={`flex-1 p-2 overflow-y-auto min-h-[200px] max-h-[calc(100vh-300px)] rounded-b-lg ${
          column.column_type === 'backlog'
            ? 'bg-gray-100 dark:bg-gray-800/50'
            : column.column_type === 'triage'
            ? 'bg-yellow-50 dark:bg-yellow-900/10'
            : column.column_type === 'in_progress'
            ? 'bg-blue-50 dark:bg-blue-900/10'
            : column.column_type === 'review'
            ? 'bg-purple-50 dark:bg-purple-900/10'
            : column.column_type === 'rejected'
            ? 'bg-red-50 dark:bg-red-900/10'
            : 'bg-green-50 dark:bg-green-900/10'
        }`}
      >
        {tasks.length === 0 ? (
          <div className="h-24 flex items-center justify-center text-gray-400 text-sm">
            No tasks
          </div>
        ) : (
          Object.entries(groupedTasks).map(([taskType, tasksInGroup]) => (
            <div key={taskType} className="mb-3">
              {/* Group Header */}
              <button
                onClick={() => toggleGroup(taskType)}
                className="w-full flex items-center justify-between px-2 py-1 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700 rounded mb-1 transition-colors"
              >
                <div className="flex items-center gap-1">
                  {collapsedGroups.has(taskType) ? (
                    <ChevronRight className="w-3 h-3" />
                  ) : (
                    <ChevronDown className="w-3 h-3" />
                  )}
                  <span>{typeLabels[taskType] || taskType}</span>
                  <span className="text-gray-400">({tasksInGroup.length})</span>
                </div>
              </button>

              {/* Group Tasks */}
              {!collapsedGroups.has(taskType) && (
                <div className="space-y-2">
                  {tasksInGroup.map((task: Task, index: number) => (
                    <KanbanCard
                      key={task.id}
                      task={task}
                      index={index}
                      onClick={() => onTaskClick(task.id)}
                      onDragStart={() => onDragStart(task.id)}
                    />
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default KanbanColumn;
