/**
 * Kanban Board Page - Actionable Decision-Making Interface
 * Main entry point for the unified kanban system
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../hooks/useAuth';
import { KanbanBoard } from '../components/kanban/KanbanBoard';
import { KanbanFilters } from '../components/kanban/KanbanFilters';
import { KanbanMetricsBar } from '../components/kanban/KanbanMetricsBar';
import { CreateTaskModal } from '../components/kanban/CreateTaskModal';
import { TaskDetailModal } from '../components/kanban/TaskDetailModal';
import { KanbanProvider, useKanban, Task } from '../stores/kanbanStore';
import { Button } from '../components/ui/Button';
import { Tooltip, TooltipTrigger, TooltipContent } from '../components/ui';
import { ExportButton } from '../components/common';
import { Plus, Filter, LayoutGrid, List, AlertCircle, RefreshCw } from 'lucide-react';

// Inner component that uses kanban context
const KanbanContent: React.FC = () => {
  const { isAdmin } = useAuth();
  const { 
    board, 
    columns, 
    tasks, 
    metrics, 
    filters, 
    isLoading, 
    error,
    setFilters, 
    refreshBoard,
    moveTask 
  } = useKanban();
  
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'board' | 'list'>('board');
  const [showFilters, setShowFilters] = useState(false);

  // Initial load
  useEffect(() => {
    refreshBoard();
  }, [refreshBoard]);

  // Handle task click
  const handleTaskClick = useCallback((taskId: string) => {
    setSelectedTaskId(taskId);
  }, []);

  // Close task detail modal
  const handleCloseTaskDetail = useCallback(() => {
    setSelectedTaskId(null);
  }, []);

  // Handle drag and drop
  const handleDragEnd = useCallback(async (taskId: string, targetColumnId: string, position?: number) => {
    try {
      await moveTask(taskId, targetColumnId, position);
    } catch (error) {
      console.error('Failed to move task:', error);
    }
  }, [moveTask]);

  // Get selected task
  const selectedTask = selectedTaskId ? tasks.find((t: Task) => t.id === selectedTaskId) : null;

  return (
    <div className="h-full flex flex-col bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-4 py-3">
        <div className="flex items-center justify-between">
          <Tooltip>
            <TooltipTrigger asChild>
              <div>
                <h1 className="text-xl font-semibold text-gray-900 dark:text-white">
                  Operations Board
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Actionable decision-making kanban
                </p>
              </div>
            </TooltipTrigger>
            <TooltipContent>Kanban board for managing operational tasks and decisions</TooltipContent>
          </Tooltip>

          <div className="flex items-center gap-3">
            {isAdmin && (
              <ExportButton
                endpoint="/api/v1/exports/kanban/tasks"
                format="xlsx"
                label="Export"
                filename="kanban_tasks.xlsx"
              />
            )}
            {/* View Toggle */}
            <div className="flex items-center bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => setViewMode('board')}
                    className={`p-2 rounded-md transition-colors ${
                      viewMode === 'board'
                        ? 'bg-white dark:bg-gray-600 shadow-sm text-blue-600'
                        : 'text-gray-600 dark:text-gray-400 hover:text-gray-900'
                    }`}
                  >
                    <LayoutGrid className="w-4 h-4" />
                  </button>
                </TooltipTrigger>
                <TooltipContent>Switch to board view</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => setViewMode('list')}
                    className={`p-2 rounded-md transition-colors ${
                      viewMode === 'list'
                        ? 'bg-white dark:bg-gray-600 shadow-sm text-blue-600'
                        : 'text-gray-600 dark:text-gray-400 hover:text-gray-900'
                    }`}
                  >
                    <List className="w-4 h-4" />
                  </button>
                </TooltipTrigger>
                <TooltipContent>Switch to list view</TooltipContent>
              </Tooltip>
            </div>

            {/* Filter Toggle */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant={showFilters ? 'primary' : 'outline'}
                  size="sm"
                  onClick={() => setShowFilters(!showFilters)}
                  className="flex items-center gap-2"
                >
                  <Filter className="w-4 h-4" />
                  Filters
                </Button>
              </TooltipTrigger>
              <TooltipContent>Toggle filter panel</TooltipContent>
            </Tooltip>

            {/* Create Task Button */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => setIsCreateModalOpen(true)}
                  className="flex items-center gap-2"
                >
                  <Plus className="w-4 h-4" />
                  New Task
                </Button>
              </TooltipTrigger>
              <TooltipContent>Create a new task</TooltipContent>
            </Tooltip>
          </div>
        </div>

        {/* Metrics Bar */}
        {metrics && (
          <KanbanMetricsBar 
            metrics={metrics}
            className="mt-3"
          />
        )}
      </div>

      {/* Filters Panel */}
      {showFilters && (
        <KanbanFilters 
          filters={filters}
          onFiltersChange={setFilters}
          className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700"
        />
      )}

      {/* Main Board Area */}
      <div className="flex-1 overflow-hidden">
        {isLoading ? (
          <div className="h-full flex items-center justify-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
          </div>
        ) : error ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <Tooltip>
                <TooltipTrigger asChild>
                  <AlertCircle className="w-12 h-12 text-red-500 mx-auto mb-4" />
                </TooltipTrigger>
                <TooltipContent>Error loading kanban board</TooltipContent>
              </Tooltip>
              <p className="text-gray-600 dark:text-gray-400 mb-4">{error}</p>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="primary"
                    onClick={refreshBoard}
                    className="flex items-center gap-2 mx-auto"
                  >
                    <RefreshCw className="w-4 h-4" />
                    Retry
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Retry loading the kanban board</TooltipContent>
              </Tooltip>
            </div>
          </div>
        ) : (
          <KanbanBoard
            board={board}
            columns={columns}
            tasks={tasks}
            onTaskClick={handleTaskClick}
            onDragEnd={handleDragEnd}
            viewMode={viewMode}
          />
        )}
      </div>

      {/* Create Task Modal */}
      <CreateTaskModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        boardId={board?.id}
        defaultColumnId={columns.find(c => c.column_type === 'backlog')?.id}
      />

      {/* Task Detail Modal */}
      {selectedTask && (
        <TaskDetailModal
          isOpen={!!selectedTaskId}
          onClose={handleCloseTaskDetail}
          task={selectedTask}
          columns={columns}
        />
      )}
    </div>
  );
};

// Main page component with provider
const KanbanPage: React.FC = () => {
  return (
    <KanbanProvider>
      <KanbanContent />
    </KanbanProvider>
  );
};

export default KanbanPage;
