/**
 * CreateTaskModal - Modal for creating new tasks
 */

import React, { useState } from 'react';
import { useKanban, Task } from '../../stores/kanbanStore';
import { Button } from '../ui/Button';
import { X } from 'lucide-react';

interface CreateTaskModalProps {
  isOpen: boolean;
  onClose: () => void;
  boardId?: string;
  defaultColumnId?: string;
}

export const CreateTaskModal: React.FC<CreateTaskModalProps> = ({
  isOpen,
  onClose,
  boardId,
  defaultColumnId,
}) => {
  const { createTask } = useKanban();
  const [isSubmitting, setIsSubmitting] = useState(false);
  // `createTask` answers `null` when the write fails and logs to the console — so without
  // this the modal simply stopped spinning and sat there with the form still filled. A
  // refused create and a slow one looked identical, and the only sensible thing a user can
  // do with that is press the button again.
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [formData, setFormData] = useState<Partial<Task>>({
    title: '',
    description: '',
    task_type: 'custom',
    priority: 'medium',
    column_id: defaultColumnId,
    board_id: boardId,
    tags: [],
    checklist_items: [],
  });

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.title || !formData.board_id || !formData.column_id) return;

    setIsSubmitting(true);
    setSubmitError(null);
    try {
      const newTask = await createTask(formData);
      if (!newTask) {
        // Deliberately does not claim the task was not created: `createTask` catches the
        // POST and the board refresh together, so a null answer can also mean the write
        // landed and only the re-read failed. A confident "nothing was saved" would be wrong
        // exactly when it matters — and would invite a duplicate task.
        setSubmitError(
          'The task was not created, or the board could not be refreshed. Close this and '
          + 'check the board before trying again.',
        );
        return;
      }

      setFormData({
        title: '',
        description: '',
        task_type: 'custom',
        priority: 'medium',
        column_id: defaultColumnId,
        board_id: boardId,
        tags: [],
        checklist_items: [],
      });
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Create New Task
          </h2>
          <button
            aria-label="Close create task dialog"
            onClick={onClose}
            className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
          >
            <X className="w-5 h-5 text-gray-500" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {submitError && (
            <p className="text-sm text-status-alarm" role="alert">
              {submitError}
            </p>
          )}
          {/* Title */}
          <div>
            <label htmlFor="createtaskmodal-title" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Title *
            </label>
            <input
              id="createtaskmodal-title"
              type="text"
              value={formData.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
              placeholder="Enter task title"
              required
            />
          </div>

          {/* Description */}
          <div>
            <label htmlFor="createtaskmodal-description" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Description
            </label>
            <textarea
              id="createtaskmodal-description"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              rows={3}
              className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
              placeholder="Enter task description"
            />
          </div>

          {/* Task Type & Priority */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="createtaskmodal-task-type" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Task Type
              </label>
              <select
              id="createtaskmodal-task-type"
                value={formData.task_type}
                onChange={(e) => setFormData({ ...formData, task_type: e.target.value as any })}
                className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
              >
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

            <div>
              <label htmlFor="createtaskmodal-priority" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Priority
              </label>
              <select
              id="createtaskmodal-priority"
                value={formData.priority}
                onChange={(e) => setFormData({ ...formData, priority: e.target.value as any })}
                className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
                <option value="emergency">Emergency</option>
              </select>
            </div>
          </div>

          {/* Due Date & Duration */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="createtaskmodal-due-date" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Due Date
              </label>
              <input
              id="createtaskmodal-due-date"
                type="datetime-local"
                value={formData.due_date || ''}
                onChange={(e) => setFormData({ ...formData, due_date: e.target.value })}
                className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
              />
            </div>

            <div>
              <label htmlFor="createtaskmodal-estimated-duration-minutes" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Estimated Duration (minutes)
              </label>
              <input
              id="createtaskmodal-estimated-duration-minutes"
                type="number"
                value={formData.estimated_effort_minutes || ''}
                onChange={(e) => setFormData({ ...formData, estimated_effort_minutes: parseInt(e.target.value) || undefined })}
                className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                placeholder="e.g., 60"
              />
            </div>
          </div>

          {/* Tags */}
          <div>
            <label htmlFor="createtaskmodal-tags-comma-separated" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Tags (comma-separated)
            </label>
            <input
              id="createtaskmodal-tags-comma-separated"
              type="text"
              value={formData.tags?.join(', ') || ''}
              onChange={(e) => setFormData({ ...formData, tags: e.target.value.split(',').map(t => t.trim()).filter(Boolean) })}
              className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
              placeholder="urgent, line-1, maintenance"
            />
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-4 border-t border-gray-200 dark:border-gray-700">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={isSubmitting}>
              Create Task
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default CreateTaskModal;
