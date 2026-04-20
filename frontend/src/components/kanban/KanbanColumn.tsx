/**
 * KanbanColumn - Individual column component for kanban board
 */

import React from 'react';
import { TaskColumn as TaskColumnType, Task } from '../../stores/kanbanStore';
import { KanbanCard } from './KanbanCard';
import { AlertCircle, ChevronDown, ChevronRight } from 'lucide-react';

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
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    onDragOver(column.id);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    onDrop(column.id);
  };

  const wipWarning = column.wip_limit > 0 && tasks.length > column.wip_limit;

  return (
    <div
      className={`flex flex-col w-80 min-w-[320px] max-w-[320px] rounded-lg transition-colors ${
        isDragOver ? 'bg-blue-50 dark:bg-blue-900/20 ring-2 ring-blue-400' : ''
      }`}
      onDragOver={handleDragOver}
      onDragLeave={onDragLeave}
      onDrop={handleDrop}
    >
      {/* Column Header */}
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
            <div className="flex items-center text-orange-600 dark:text-orange-400" title="WIP limit exceeded">
              <AlertCircle className="w-4 h-4" />
            </div>
          )}
          <button className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
            <ChevronDown className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* WIP Limit Indicator */}
      {column.wip_limit > 0 && (
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
      )}

      {/* Tasks Container */}
      <div
        className={`flex-1 p-2 space-y-2 overflow-y-auto min-h-[200px] max-h-[calc(100vh-300px)] rounded-b-lg ${
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
          tasks.map((task: Task, index: number) => (
            <KanbanCard
              key={task.id}
              task={task}
              index={index}
              onClick={() => onTaskClick(task.id)}
              onDragStart={() => onDragStart(task.id)}
            />
          ))
        )}
      </div>
    </div>
  );
};

export default KanbanColumn;
