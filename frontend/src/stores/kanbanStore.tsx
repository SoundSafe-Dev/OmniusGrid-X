/**
 * Kanban Store - Zustand state management for kanban board
 */

import React, { createContext, useContext, useState, useCallback, useEffect, ReactNode } from 'react';

// Types
export interface TaskChecklistItem {
  text: string;
  completed: boolean;
}

export interface Task {
  id: string;
  board_id: string;
  column_id: string;
  position: number;
  title: string;
  description?: string;
  task_type: 'production_job' | 'maintenance_pm' | 'maintenance_cm' | 'quality_inspection' | 'safety_check' | 'alarm_response' | 'command_execution' | 'material_request' | 'changeover' | 'custom';
  priority: 'low' | 'medium' | 'high' | 'critical' | 'emergency';
  status: 'draft' | 'ready' | 'in_progress' | 'blocked' | 'completed' | 'cancelled';
  assigned_to?: string;
  assigned_by?: string;
  assigned_at?: string;
  planned_start?: string;
  planned_duration?: number;
  due_date?: string;
  actual_start?: string;
  actual_end?: string;
  asset_id?: string;
  operation_id?: string;
  alarm_id?: string;
  command_id?: string;
  parent_task_id?: string;
  rule_id?: string;
  progress_percent: number;
  time_logged_minutes: number;
  estimated_effort_minutes?: number;
  tags: string[];
  custom_fields: Record<string, any>;
  checklist_items: TaskChecklistItem[];
  color_code?: string;
  approval_status: 'pending' | 'approved' | 'rejected';
  approved_by?: string;
  approved_at?: string;
  rejection_reason?: string;
  completion_actions: Record<string, any>;
  completion_result: Record<string, any>;
  created_by?: string;
  created_at: string;
  updated_at: string;
  completed_at?: string;
  completed_by?: string;
}

export interface TaskColumn {
  id: string;
  board_id: string;
  name: string;
  position: number;
  wip_limit: number;
  column_type: 'backlog' | 'triage' | 'in_progress' | 'review' | 'rejected' | 'done';
  color: string;
  is_collapsed: boolean;
  auto_archive_days: number;
  created_at: string;
  updated_at: string;
  task_count?: number;
}

export interface TaskBoard {
  id: string;
  organization_id: string;
  name: string;
  board_type: string;
  default_view_config: Record<string, any>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface KanbanMetrics {
  total_tasks: number;
  tasks_by_column: Record<string, number>;
  tasks_by_priority: Record<string, number>;
  tasks_awaiting_approval: number;
  overdue_tasks: number;
  avg_cycle_time_minutes?: number;
  tasks_completed_today: number;
  active_escalations: number;
}

export interface KanbanFilters {
  view_type: 'all' | 'by_asset' | 'by_workcell' | 'by_type' | 'by_priority' | 'by_assignee';
  asset_id?: string;
  workcell_id?: string;
  task_type?: string;
  priority?: string;
  assignee_id?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
}

interface KanbanContextType {
  board: TaskBoard | null;
  columns: TaskColumn[];
  tasks: Task[];
  metrics: KanbanMetrics | null;
  filters: KanbanFilters;
  isLoading: boolean;
  error: string | null;
  setFilters: (filters: Partial<KanbanFilters>) => void;
  refreshBoard: () => Promise<void>;
  moveTask: (taskId: string, targetColumnId: string, position?: number) => Promise<void>;
  approveTask: (taskId: string, action: 'approve' | 'reject', reason?: string) => Promise<void>;
  startTask: (taskId: string) => Promise<void>;
  completeTask: (taskId: string) => Promise<void>;
  createTask: (taskData: Partial<Task>) => Promise<Task | null>;
  updateTask: (taskId: string, updates: Partial<Task>) => Promise<void>;
  deleteTask: (taskId: string) => Promise<void>;
}

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// Create context
const KanbanContext = createContext<KanbanContextType | null>(null);

// Provider component
export const KanbanProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [board, setBoard] = useState<TaskBoard | null>(null);
  const [columns, setColumns] = useState<TaskColumn[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [metrics, setMetrics] = useState<KanbanMetrics | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFiltersState] = useState<KanbanFilters>({
    view_type: 'all',
  });

  // Fetch board data
  const refreshBoard = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const queryParams = new URLSearchParams();
      if (filters.asset_id) queryParams.append('asset_id', filters.asset_id);
      if (filters.task_type) queryParams.append('task_type', filters.task_type);
      if (filters.priority) queryParams.append('priority', filters.priority);
      if (filters.assignee_id) queryParams.append('assignee_id', filters.assignee_id);
      if (filters.status) queryParams.append('status', filters.status);

      const response = await fetch(`${API_BASE}/api/v1/kanban/board?${queryParams.toString()}`, {
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('Failed to fetch board data');
      }

      const data = await response.json();
      setBoard(data.board);
      setColumns(data.columns);
      setTasks(data.tasks);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setIsLoading(false);
    }
  }, [filters]);

  // Fetch metrics
  const refreshMetrics = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/kanban/metrics`, {
        credentials: 'include',
      });

      if (response.ok) {
        const data = await response.json();
        setMetrics(data);
      }
    } catch (err) {
      console.error('Failed to fetch metrics:', err);
    }
  }, []);

  // Initial load and periodic refresh
  useEffect(() => {
    refreshBoard();
    refreshMetrics();

    // Set up polling for real-time updates
    const interval = setInterval(() => {
      refreshMetrics();
    }, 30000); // Every 30 seconds

    return () => clearInterval(interval);
  }, [refreshBoard, refreshMetrics]);

  // Update filters
  const setFilters = useCallback((newFilters: Partial<KanbanFilters>) => {
    setFiltersState(prev => ({ ...prev, ...newFilters }));
  }, []);

  // Move task
  const moveTask = useCallback(async (taskId: string, targetColumnId: string, position?: number) => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/kanban/tasks/${taskId}/move`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ target_column_id: targetColumnId, position }),
      });

      if (!response.ok) {
        throw new Error('Failed to move task');
      }

      // Update local state optimistically
      setTasks(prev => prev.map(t => 
        t.id === taskId 
          ? { ...t, column_id: targetColumnId, position: position ?? t.position }
          : t
      ));

      // Refresh to get server state
      await refreshBoard();
      await refreshMetrics();
    } catch (err) {
      throw err;
    }
  }, [refreshBoard, refreshMetrics]);

  // Approve/reject task
  const approveTask = useCallback(async (taskId: string, action: 'approve' | 'reject', reason?: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/kanban/tasks/${taskId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ action, reason }),
      });

      if (!response.ok) {
        throw new Error('Failed to approve/reject task');
      }

      await refreshBoard();
      await refreshMetrics();
    } catch (err) {
      throw err;
    }
  }, [refreshBoard, refreshMetrics]);

  // Start task
  const startTask = useCallback(async (taskId: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/kanban/tasks/${taskId}/start`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('Failed to start task');
      }

      await refreshBoard();
      await refreshMetrics();
    } catch (err) {
      throw err;
    }
  }, [refreshBoard, refreshMetrics]);

  // Complete task
  const completeTask = useCallback(async (taskId: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/kanban/tasks/${taskId}/complete`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('Failed to complete task');
      }

      await refreshBoard();
      await refreshMetrics();
    } catch (err) {
      throw err;
    }
  }, [refreshBoard, refreshMetrics]);

  // Create task
  const createTask = useCallback(async (taskData: Partial<Task>): Promise<Task | null> => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/kanban/tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(taskData),
      });

      if (!response.ok) {
        throw new Error('Failed to create task');
      }

      const newTask = await response.json();
      await refreshBoard();
      await refreshMetrics();
      return newTask;
    } catch (err) {
      console.error('Failed to create task:', err);
      return null;
    }
  }, [refreshBoard, refreshMetrics]);

  // Update task
  const updateTask = useCallback(async (taskId: string, updates: Partial<Task>) => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/kanban/tasks/${taskId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(updates),
      });

      if (!response.ok) {
        throw new Error('Failed to update task');
      }

      await refreshBoard();
    } catch (err) {
      throw err;
    }
  }, [refreshBoard]);

  // Delete task
  const deleteTask = useCallback(async (taskId: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/kanban/tasks/${taskId}`, {
        method: 'DELETE',
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('Failed to delete task');
      }

      await refreshBoard();
      await refreshMetrics();
    } catch (err) {
      throw err;
    }
  }, [refreshBoard, refreshMetrics]);

  const value: KanbanContextType = {
    board,
    columns,
    tasks,
    metrics,
    filters,
    isLoading,
    error,
    setFilters,
    refreshBoard,
    moveTask,
    approveTask,
    startTask,
    completeTask,
    createTask,
    updateTask,
    deleteTask,
  };

  return (
    <KanbanContext.Provider value={value}>
      {children}
    </KanbanContext.Provider>
  );
};

// Hook to use kanban context
export const useKanban = (): KanbanContextType => {
  const context = useContext(KanbanContext);
  if (!context) {
    throw new Error('useKanban must be used within a KanbanProvider');
  }
  return context;
};

export default KanbanContext;
