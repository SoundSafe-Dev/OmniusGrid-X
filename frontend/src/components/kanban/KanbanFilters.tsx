/**
 * KanbanFilters - Filter panel for kanban board
 */

import React from 'react';
import { KanbanFilters as KanbanFiltersType } from '../../stores/kanbanStore';
import { X, Filter } from 'lucide-react';

interface KanbanFiltersProps {
  filters: KanbanFiltersType;
  onFiltersChange: (filters: Partial<KanbanFiltersType>) => void;
  className?: string;
}

export const KanbanFilters: React.FC<KanbanFiltersProps> = ({
  filters,
  onFiltersChange,
  className = '',
}) => {
  const clearFilters = () => {
    onFiltersChange({
      view_type: 'all',
      asset_id: undefined,
      task_type: undefined,
      priority: undefined,
      assignee_id: undefined,
      status: undefined,
      date_from: undefined,
      date_to: undefined,
    });
  };

  const hasActiveFilters =
    filters.asset_id ||
    filters.task_type ||
    filters.priority ||
    filters.assignee_id ||
    filters.status ||
    filters.date_from ||
    filters.date_to;

  return (
    <div className={`p-4 ${className}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-gray-500" />
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
            Filters
          </span>
        </div>
        {hasActiveFilters && (
          <button
            onClick={clearFilters}
            className="flex items-center gap-1 text-xs text-red-600 hover:text-red-700"
          >
            <X className="w-3 h-3" />
            Clear all
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {/* View Type */}
        <div>
          <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
            View
          </label>
          <select
            value={filters.view_type}
            onChange={(e) => onFiltersChange({ view_type: e.target.value as any })}
            className="w-full text-sm border border-gray-300 dark:border-gray-600 rounded-md px-2 py-1.5 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
          >
            <option value="all">All Tasks</option>
            <option value="by_asset">By Asset</option>
            <option value="by_type">By Type</option>
            <option value="by_priority">By Priority</option>
            <option value="by_assignee">By Assignee</option>
          </select>
        </div>

        {/* Task Type */}
        <div>
          <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
            Task Type
          </label>
          <select
            value={filters.task_type || ''}
            onChange={(e) => onFiltersChange({ task_type: e.target.value || undefined })}
            className="w-full text-sm border border-gray-300 dark:border-gray-600 rounded-md px-2 py-1.5 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
          >
            <option value="">All Types</option>
            <option value="production_job">Production Job</option>
            <option value="maintenance_pm">Preventive Maintenance</option>
            <option value="maintenance_cm">Corrective Maintenance</option>
            <option value="quality_inspection">Quality Inspection</option>
            <option value="safety_check">Safety Check</option>
            <option value="alarm_response">Alarm Response</option>
            <option value="command_execution">Command Execution</option>
            <option value="changeover">Changeover</option>
            <option value="custom">Custom</option>
          </select>
        </div>

        {/* Priority */}
        <div>
          <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
            Priority
          </label>
          <select
            value={filters.priority || ''}
            onChange={(e) => onFiltersChange({ priority: e.target.value || undefined })}
            className="w-full text-sm border border-gray-300 dark:border-gray-600 rounded-md px-2 py-1.5 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
          >
            <option value="">All Priorities</option>
            <option value="emergency">Emergency</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>

        {/* Status */}
        <div>
          <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
            Status
          </label>
          <select
            value={filters.status || ''}
            onChange={(e) => onFiltersChange({ status: e.target.value || undefined })}
            className="w-full text-sm border border-gray-300 dark:border-gray-600 rounded-md px-2 py-1.5 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
          >
            <option value="">All Statuses</option>
            <option value="draft">Draft</option>
            <option value="ready">Ready</option>
            <option value="in_progress">In Progress</option>
            <option value="blocked">Blocked</option>
            <option value="completed">Completed</option>
          </select>
        </div>

        {/* Date Range */}
        <div>
          <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
            From Date
          </label>
          <input
            type="date"
            value={filters.date_from || ''}
            onChange={(e) => onFiltersChange({ date_from: e.target.value || undefined })}
            className="w-full text-sm border border-gray-300 dark:border-gray-600 rounded-md px-2 py-1.5 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
            To Date
          </label>
          <input
            type="date"
            value={filters.date_to || ''}
            onChange={(e) => onFiltersChange({ date_to: e.target.value || undefined })}
            className="w-full text-sm border border-gray-300 dark:border-gray-600 rounded-md px-2 py-1.5 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
          />
        </div>
      </div>
    </div>
  );
};

export default KanbanFilters;
