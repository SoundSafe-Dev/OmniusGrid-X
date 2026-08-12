/**
 * KanbanBoard - Main kanban board component with drag-and-drop
 */

import React, { useState, useCallback } from 'react';
import { TaskColumn as TaskColumnType, Task } from '../../stores/kanbanStore';
import { KanbanColumn } from './KanbanColumn';
import { Tooltip, TooltipTrigger, TooltipContent } from '../ui';

interface KanbanBoardProps {
  board: { id: string } | null;
  columns: TaskColumnType[];
  tasks: Task[];
  onTaskClick: (taskId: string) => void;
  onDragEnd: (taskId: string, targetColumnId: string, position?: number) => Promise<void>;
  viewMode: 'board' | 'list';
}

export const KanbanBoard: React.FC<KanbanBoardProps> = ({
  board,
  columns,
  tasks,
  onTaskClick,
  onDragEnd,
  viewMode,
}) => {
  const [draggedTaskId, setDraggedTaskId] = useState<string | null>(null);
  const [dragOverColumnId, setDragOverColumnId] = useState<string | null>(null);

  const handleDragStart = useCallback((taskId: string) => {
    setDraggedTaskId(taskId);
  }, []);

  const handleDragOver = useCallback((columnId: string) => {
    setDragOverColumnId(columnId);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOverColumnId(null);
  }, []);

  const handleDrop = useCallback(async (columnId: string) => {
    if (!draggedTaskId) return;
    try {
      await onDragEnd(draggedTaskId, columnId);
    } catch (error) {
      // NOT RETHROWN, AND THE PREVIOUS COMMENT HERE WAS WRONG ABOUT WHY. It said "the
      // error still propagates to the caller" — but the caller is `KanbanColumn`'s
      // `onDrop`, typed `(columnId: string) => void` and invoked from a DOM drop handler
      // that discards the returned promise. Nothing can catch it, so a rejection became an
      // unhandled rejection, which is how it showed up: one error in an otherwise green
      // test run, sitting there ready to mask a real one.
      //
      // `Kanban.tsx` already catches this and shows the user "That task could not be moved
      // — it is still in the column it started in", so today the promise never rejects in
      // production. That makes this the trap rather than the failure — and the log is what
      // keeps a future `onDragEnd` that forgets to catch from failing in silence.
      console.error('Failed to move task:', error);
    } finally {
      // FINALLY, NOT AFTER THE AWAIT. `onDragEnd` rejects when the store's move is refused
      // — a WIP limit, a permission, a dropped connection — and the resets used to sit
      // after it, so a rejection skipped them. The board kept holding the task with the
      // target column still highlighted, and **the next drop anywhere moved that task**
      // rather than the one being dragged. The gesture has ended either way; whether it
      // succeeded is a separate question.
      setDraggedTaskId(null);
      setDragOverColumnId(null);
    }
  }, [draggedTaskId, onDragEnd]);

  if (!board) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-gray-500">No board available</div>
      </div>
    );
  }

  if (viewMode === 'list') {
    return (
      <div className="h-full overflow-auto p-4">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow">
          {tasks.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              No tasks found
            </div>
          ) : (
            <table className="w-full">
              <thead className="bg-gray-50 dark:bg-gray-700">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Task</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Priority</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Assignee</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Due Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {tasks.map((task) => (
                  <tr
                    key={task.id}
                    onClick={() => onTaskClick(task.id)}
                    className="hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-900 dark:text-white">{task.title}</div>
                      <div className="text-sm text-gray-500 truncate max-w-xs">
                        {task.description || 'No description'}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                        {task.task_type?.replace('_', ' ')}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <PriorityBadge priority={task.priority} />
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={task.status} />
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                      {task.assigned_to ? 'Assigned' : 'Unassigned'}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                      {task.due_date ? new Date(task.due_date).toLocaleDateString() : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-x-auto overflow-y-hidden">
      <div className="flex h-full gap-4 p-4 min-w-max">
        {columns
          .sort((a: TaskColumnType, b: TaskColumnType) => a.position - b.position)
          .map((column: TaskColumnType) => {
            const columnTasks = tasks
              .filter((t: Task) => t.column_id === column.id)
              .sort((a: Task, b: Task) => a.position - b.position);

            return (
              <KanbanColumn
                key={column.id}
                column={column}
                tasks={columnTasks}
                onTaskClick={onTaskClick}
                onDragStart={handleDragStart}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                isDragOver={dragOverColumnId === column.id}
              />
            );
          })}
      </div>
    </div>
  );
};

// Helper components
const PriorityBadge: React.FC<{ priority: string }> = ({ priority }) => {
  const colors: Record<string, string> = {
    low: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300',
    medium: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
    high: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
    critical: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
    emergency: 'bg-red-200 text-red-900 dark:bg-red-800 dark:text-red-100 animate-pulse',
  };

  const getPriorityDescription = (p: string) => {
    switch (p) {
      case 'low': return 'Low priority, can be deferred';
      case 'medium': return 'Medium priority, address soon';
      case 'high': return 'High priority, address promptly';
      case 'critical': return 'Critical priority, immediate action';
      case 'emergency': return 'Emergency, requires immediate intervention';
      default: return p;
    }
  };

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${colors[priority] || colors.medium}`}>
          {priority}
        </span>
      </TooltipTrigger>
      <TooltipContent>{getPriorityDescription(priority)}</TooltipContent>
    </Tooltip>
  );
};

const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const colors: Record<string, string> = {
    draft: 'bg-gray-100 text-gray-800',
    ready: 'bg-blue-100 text-blue-800',
    in_progress: 'bg-yellow-100 text-yellow-800',
    blocked: 'bg-red-100 text-red-800',
    completed: 'bg-green-100 text-green-800',
    cancelled: 'bg-gray-100 text-gray-600',
  };

  const getStatusDescription = (s: string) => {
    switch (s) {
      case 'draft': return 'Task is being defined';
      case 'ready': return 'Task is ready to start';
      case 'in_progress': return 'Task is actively being worked on';
      case 'blocked': return 'Task is blocked by dependency';
      case 'completed': return 'Task has been completed';
      case 'cancelled': return 'Task was cancelled';
      default: return s;
    }
  };

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${colors[status] || colors.draft}`}>
          {status?.replace('_', ' ')}
        </span>
      </TooltipTrigger>
      <TooltipContent>{getStatusDescription(status)}</TooltipContent>
    </Tooltip>
  );
};

export default KanbanBoard;
