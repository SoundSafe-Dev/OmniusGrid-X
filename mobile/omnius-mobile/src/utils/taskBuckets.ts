import type { KanbanColumn, Task } from '../api/types';

export type TaskSegment = 'new' | 'in_progress' | 'completed';

const NEW_TYPES = new Set(['backlog', 'triage']);
const PROGRESS_TYPES = new Set(['in_progress', 'review']);

export function taskSegment(columnMap: Map<string, KanbanColumn>, task: Task): TaskSegment {
  const col = columnMap.get(task.column_id);
  const t = col?.column_type ?? '';
  if (t === 'done') return 'completed';
  if (PROGRESS_TYPES.has(t)) return 'in_progress';
  return 'new';
}

export function filterTasksBySegment(
  tasks: Task[],
  columns: KanbanColumn[],
  segment: TaskSegment
): Task[] {
  const map = new Map(columns.map((c) => [c.id, c]));
  return tasks.filter((task) => taskSegment(map, task) === segment);
}

export function columnIdByType(columns: KanbanColumn[], type: string): string | undefined {
  return columns.find((c) => c.column_type === type)?.id;
}

export type TaskPrimaryAction = 'approve' | 'start' | 'complete' | 'reopen' | null;

export function primaryTaskAction(columnMap: Map<string, KanbanColumn>, task: Task): TaskPrimaryAction {
  const col = columnMap.get(task.column_id);
  const t = col?.column_type ?? '';
  if (t === 'done') return 'reopen';
  if (t === 'in_progress' || t === 'review') return 'complete';
  if (t === 'backlog' && task.approval_status === 'pending') return 'approve';
  if (t === 'backlog' && task.approval_status !== 'pending') return 'start';
  if (t === 'triage') return 'start';
  return 'start';
}
