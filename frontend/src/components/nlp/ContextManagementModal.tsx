import React, { useState, useEffect } from 'react';
import { X, Plus, Trash2, Save, Loader2 } from 'lucide-react';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { Badge } from '../ui/Badge';
import { userContextApi, UserContext, UserGoal } from '../../api/userContext';

interface ContextManagementModalProps {
  isOpen: boolean;
  onClose: () => void;
  onContextUpdated: () => void;
  initialContext?: UserContext;
}

export const ContextManagementModal: React.FC<ContextManagementModalProps> = ({
  isOpen,
  onClose,
  onContextUpdated,
  initialContext
}) => {
  const [department, setDepartment] = useState('');
  const [priorities, setPriorities] = useState<string[]>([]);
  const [priorityInput, setPriorityInput] = useState('');
  const [goals, setGoals] = useState<UserGoal[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  // Four handlers here mutate and reported failure only to the console (FS-478). This is a
  // MODAL: it closes on success, so "nothing happened and the dialog is still open" is the
  // only signal a user gets, and it is the same thing they see while the request is still
  // in flight. Same class the useMutation sweep covers — these are hand-rolled handlers,
  // which that sweep cannot see.
  const [actionError, setActionError] = useState<string | null>(null);
  const [newGoalTitle, setNewGoalTitle] = useState('');
  const [newGoalProgress, setNewGoalProgress] = useState(0);
  const [newGoalDeadline, setNewGoalDeadline] = useState('');

  useEffect(() => {
    if (initialContext) {
      setDepartment(initialContext.department || '');
      setPriorities(initialContext.priorities || []);
      setGoals(initialContext.user_goals || []);
    }
  }, [initialContext]);

  const handleAddPriority = () => {
    if (priorityInput.trim() && !priorities.includes(priorityInput.trim())) {
      setPriorities([...priorities, priorityInput.trim()]);
      setPriorityInput('');
    }
  };

  const handleRemovePriority = (priority: string) => {
    setPriorities(priorities.filter(p => p !== priority));
  };

  const handleAddGoal = async () => {
    if (!newGoalTitle.trim()) return;

    try {
      await userContextApi.addUserGoal({
        title: newGoalTitle,
        progress: newGoalProgress,
        deadline: newGoalDeadline || undefined
      });
      
      // Refresh context
      const updatedContext = await userContextApi.getUserContext();
      setGoals(updatedContext.user_goals);
      
      setNewGoalTitle('');
      setNewGoalProgress(0);
      setNewGoalDeadline('');
    } catch (error) {
      console.error('Error adding goal:', error);
      setActionError('Could not add the goal. Nothing was changed.');
    }
  };

  const handleUpdateGoal = async (goalId: string, updates: Partial<UserGoal>) => {
    try {
      await userContextApi.updateGoal(goalId, {
        title: updates.title || '',
        progress: updates.progress || 0,
        deadline: updates.deadline || undefined
      });
      
      // Refresh context
      const updatedContext = await userContextApi.getUserContext();
      setGoals(updatedContext.user_goals);
    } catch (error) {
      console.error('Error updating goal:', error);
      setActionError('Could not update the goal. Nothing was changed.');
    }
  };

  const handleDeleteGoal = async (goalId: string) => {
    try {
      await userContextApi.deleteGoal(goalId);
      
      // Refresh context
      const updatedContext = await userContextApi.getUserContext();
      setGoals(updatedContext.user_goals);
    } catch (error) {
      console.error('Error deleting goal:', error);
      setActionError('Could not delete the goal. Nothing was changed.');
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await userContextApi.updateUserContext({
        department,
        priorities
      });
      
      onContextUpdated();
      onClose();
    } catch (error) {
      console.error('Error saving context:', error);
      setActionError('Could not save your context. Nothing was changed.');
    } finally {
      setIsSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col">
        <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Manage Context</h2>
          <Button variant="outline" size="sm" onClick={onClose}>
            <X className="w-4 h-4" />
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {/* A failed add, update, delete or save, said out loud (FS-478). At the top of
              the scrollable body so it is visible wherever the user was working — a modal
              that simply stays open is indistinguishable from one still saving. */}
          {actionError && (
            <div
              role="alert"
              className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-500"
            >
              {actionError}
            </div>
          )}
          {/* User Context Section */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white">User Information</h3>
            
            <div>
              <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">Department</label>
              <Input
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                placeholder="e.g., Operations"
                className="w-full"
              />
            </div>

            <div>
              <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">Priorities</label>
              <div className="flex gap-2 mb-2">
                <Input
                  value={priorityInput}
                  onChange={(e) => setPriorityInput(e.target.value)}
                  onKeyPress={(e) => e.key === 'Enter' && handleAddPriority()}
                  placeholder="Add priority..."
                  className="flex-1"
                />
                <Button onClick={handleAddPriority} size="sm">
                  <Plus className="w-4 h-4" />
                </Button>
              </div>
              <div className="flex flex-wrap gap-2">
                {priorities.map((priority) => (
                  <Badge key={priority} variant="info" className="flex items-center gap-1">
                    {priority}
                    <button
                      onClick={() => handleRemovePriority(priority)}
                      className="ml-1 hover:text-red-500"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </Badge>
                ))}
              </div>
            </div>
          </div>

          {/* Goals Section */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Active Goals</h3>
            
            {/* Add New Goal */}
            <div className="p-4 bg-gray-50 dark:bg-gray-700 rounded-lg space-y-3">
              <Input
                value={newGoalTitle}
                onChange={(e) => setNewGoalTitle(e.target.value)}
                placeholder="Goal title..."
                className="w-full"
              />
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">Progress (%)</label>
                  <Input
                    type="number"
                    min="0"
                    max="100"
                    value={newGoalProgress}
                    onChange={(e) => setNewGoalProgress(parseInt(e.target.value) || 0)}
                    className="w-full"
                  />
                </div>
                <div className="flex-1">
                  <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">Deadline</label>
                  <Input
                    type="date"
                    value={newGoalDeadline}
                    onChange={(e) => setNewGoalDeadline(e.target.value)}
                    className="w-full"
                  />
                </div>
              </div>
              <Button onClick={handleAddGoal} size="sm" className="w-full">
                <Plus className="w-4 h-4 mr-2" />
                Add Goal
              </Button>
            </div>

            {/* Existing Goals */}
            <div className="space-y-3">
              {goals.map((goal) => (
                <div key={goal.id} className="p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
                  <div className="flex items-start justify-between mb-2">
                    <Input
                      value={goal.title}
                      onChange={(e) => handleUpdateGoal(goal.id, { title: e.target.value })}
                      className="flex-1 mr-2"
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleDeleteGoal(goal.id)}
                      className="px-2"
                    >
                      <Trash2 className="w-3 h-3" />
                    </Button>
                  </div>
                  <div className="flex gap-3 items-center">
                    <div className="flex-1">
                      <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">Progress: {goal.progress}%</label>
                      <input
                        type="range"
                        min="0"
                        max="100"
                        value={goal.progress}
                        onChange={(e) => handleUpdateGoal(goal.id, { progress: parseInt(e.target.value) })}
                        className="w-full"
                      />
                    </div>
                    <div className="flex-1">
                      <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">Deadline</label>
                      <Input
                        type="date"
                        value={goal.deadline ? goal.deadline.split('T')[0] : ''}
                        onChange={(e) => handleUpdateGoal(goal.id, { deadline: e.target.value })}
                        className="w-full"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="p-4 border-t border-gray-200 dark:border-gray-700 flex justify-end gap-3">
          <Button variant="outline" onClick={onClose} disabled={isSaving}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={isSaving}>
            {isSaving ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Saving...
              </>
            ) : (
              <>
                <Save className="w-4 h-4 mr-2" />
                Save Changes
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
};
