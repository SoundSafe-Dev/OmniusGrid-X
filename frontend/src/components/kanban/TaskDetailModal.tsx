/**
 * TaskDetailModal - Modal for viewing and editing task details
 */

import React, { useState } from 'react';
import { useKanban, Task, TaskColumn } from '../../stores/kanbanStore';
import { Button } from '../ui/Button';
import { X, Play, CheckCircle, AlertCircle, User, Clock, Calendar, ArrowRightLeft } from 'lucide-react';

interface TaskDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  task: Task | null;
  columns: TaskColumn[];
}

export const TaskDetailModal: React.FC<TaskDetailModalProps> = ({
  isOpen,
  onClose,
  task,
  columns,
}) => {
  const { updateTask, approveTask, startTask, completeTask, deleteTask, moveTask } = useKanban();
  const [isEditing, setIsEditing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formData, setFormData] = useState<Partial<Task>>({});

  if (!isOpen || !task) return null;

  const currentColumn = columns.find((c: TaskColumn) => c.id === task.column_id);

  const handleApprove = async () => {
    setIsSubmitting(true);
    try {
      await approveTask(task.id, 'approve');
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReject = async () => {
    const reason = prompt('Enter rejection reason:');
    if (!reason) return;
    
    setIsSubmitting(true);
    try {
      await approveTask(task.id, 'reject', reason);
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleStart = async () => {
    setIsSubmitting(true);
    try {
      await startTask(task.id);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleComplete = async () => {
    setIsSubmitting(true);
    try {
      await completeTask(task.id);
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleMove = async (targetColumnId: string) => {
    setIsSubmitting(true);
    try {
      await moveTask(task.id, targetColumnId);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSave = async () => {
    setIsSubmitting(true);
    try {
      await updateTask(task.id, formData);
      setIsEditing(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm('Are you sure you want to delete this task?')) return;
    
    setIsSubmitting(true);
    try {
      await deleteTask(task.id);
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  // Priority badge
  const getPriorityColor = (priority: string) => {
    const colors: Record<string, string> = {
      low: 'bg-gray-100 text-gray-600',
      medium: 'bg-blue-100 text-blue-600',
      high: 'bg-orange-100 text-orange-600',
      critical: 'bg-red-100 text-red-600',
      emergency: 'bg-red-200 text-red-700 animate-pulse',
    };
    return colors[priority] || colors.medium;
  };

  // Type label
  const typeLabels: Record<string, string> = {
    production_job: 'Production Job',
    maintenance_pm: 'Preventive Maintenance',
    maintenance_cm: 'Corrective Maintenance',
    quality_inspection: 'Quality Inspection',
    safety_check: 'Safety Check',
    alarm_response: 'Alarm Response',
    command_execution: 'Command Execution',
    material_request: 'Material Request',
    changeover: 'Changeover',
    custom: 'Custom',
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-2">
            <span className={`px-2 py-1 rounded-full text-xs font-medium ${getPriorityColor(task.priority)}`}>
              {task.priority}
            </span>
            <span className="px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
              {typeLabels[task.task_type] || task.task_type}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
          >
            <X className="w-5 h-5 text-gray-500" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {/* Title */}
          {isEditing ? (
            <input
              type="text"
              value={formData.title || task.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              className="w-full text-xl font-semibold border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
            />
          ) : (
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
              {task.title}
            </h2>
          )}

          {/* Status & Column */}
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-1 text-gray-600 dark:text-gray-400">
              <ArrowRightLeft className="w-4 h-4" />
              <span>Column:</span>
              <select
                value={task.column_id}
                onChange={(e) => handleMove(e.target.value)}
                className="ml-1 border border-gray-300 dark:border-gray-600 rounded px-2 py-1 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                disabled={isSubmitting}
              >
                {columns.map((col: TaskColumn) => (
                  <option key={col.id} value={col.id}>
                    {col.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-1 text-gray-600 dark:text-gray-400">
              <span>Status:</span>
              <span className="font-medium text-gray-900 dark:text-white capitalize">
                {task.status.replace('_', ' ')}
              </span>
            </div>
          </div>

          {/* Approval Status */}
          {task.approval_status === 'pending' && (
            <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-3">
              <div className="flex items-center gap-2 text-yellow-800 dark:text-yellow-200">
                <AlertCircle className="w-5 h-5" />
                <span className="font-medium">This task is awaiting approval</span>
              </div>
              <div className="mt-2 flex gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  onClick={handleApprove}
                  loading={isSubmitting}
                >
                  Approve
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={handleReject}
                  loading={isSubmitting}
                >
                  Reject
                </Button>
              </div>
            </div>
          )}

          {/* Description */}
          <div>
            <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Description
            </h3>
            {isEditing ? (
              <textarea
                value={formData.description || task.description || ''}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                rows={4}
                className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
              />
            ) : (
              <p className="text-gray-600 dark:text-gray-400">
                {task.description || 'No description provided'}
              </p>
            )}
          </div>

          {/* Task Details Grid */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                <Clock className="inline w-4 h-4 mr-1" />
                Time Logged
              </h3>
              <p className="text-gray-900 dark:text-white">
                {formatDuration(task.time_logged_minutes)}
              </p>
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                <Calendar className="inline w-4 h-4 mr-1" />
                Due Date
              </h3>
              <p className="text-gray-900 dark:text-white">
                {task.due_date
                  ? new Date(task.due_date).toLocaleString()
                  : 'No due date'}
              </p>
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                <User className="inline w-4 h-4 mr-1" />
                Assigned To
              </h3>
              <p className="text-gray-900 dark:text-white">
                {task.assigned_to ? 'Assigned' : 'Unassigned'}
              </p>
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Progress
              </h3>
              <div className="flex items-center gap-2">
                <div className="flex-1 h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full"
                    style={{ width: `${task.progress_percent}%` }}
                  />
                </div>
                <span className="text-sm text-gray-700 dark:text-gray-300">
                  {task.progress_percent}%
                </span>
              </div>
            </div>
          </div>

          {/* Linked Entities */}
          {(task.asset_id || task.alarm_id || task.operation_id) && (
            <div>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Linked Entities
              </h3>
              <div className="flex flex-wrap gap-2">
                {task.asset_id && (
                  <span className="px-3 py-1 bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300 rounded-full text-sm">
                    Asset: {task.asset_id.slice(0, 8)}...
                  </span>
                )}
                {task.alarm_id && (
                  <span className="px-3 py-1 bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300 rounded-full text-sm">
                    Alarm: {task.alarm_id.slice(0, 8)}...
                  </span>
                )}
                {task.operation_id && (
                  <span className="px-3 py-1 bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300 rounded-full text-sm">
                    Operation: {task.operation_id.slice(0, 8)}...
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Tags */}
          {task.tags && task.tags.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Tags
              </h3>
              <div className="flex flex-wrap gap-1">
                {task.tags.map((tag: string) => (
                  <span
                    key={tag}
                    className="px-2 py-1 bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300 rounded text-xs"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex flex-wrap justify-between gap-2 pt-4 border-t border-gray-200 dark:border-gray-700">
            <div className="flex gap-2">
              {isEditing ? (
                <>
                  <Button
                    variant="outline"
                    onClick={() => setIsEditing(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    onClick={handleSave}
                    loading={isSubmitting}
                  >
                    Save Changes
                  </Button>
                </>
              ) : (
                <Button
                  variant="outline"
                  onClick={() => setIsEditing(true)}
                >
                  Edit
                </Button>
              )}
              <Button
                variant="danger"
                onClick={handleDelete}
                loading={isSubmitting}
              >
                Delete
              </Button>
            </div>

            <div className="flex gap-2">
              {task.status === 'ready' && (
                <Button
                  variant="primary"
                  onClick={handleStart}
                  loading={isSubmitting}
                  className="flex items-center gap-1"
                >
                  <Play className="w-4 h-4" />
                  Start Work
                </Button>
              )}
              {(task.status === 'in_progress' || task.status === 'ready') && (
                <Button
                  variant="primary"
                  onClick={handleComplete}
                  loading={isSubmitting}
                  className="flex items-center gap-1 bg-green-600 hover:bg-green-700"
                >
                  <CheckCircle className="w-4 h-4" />
                  Complete
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

// Helper function to format duration
function formatDuration(minutes: number): string {
  if (minutes < 60) {
    return `${minutes} minutes`;
  }
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (remainingMinutes === 0) {
    return `${hours} hour${hours > 1 ? 's' : ''}`;
  }
  return `${hours}h ${remainingMinutes}m`;
}

export default TaskDetailModal;
