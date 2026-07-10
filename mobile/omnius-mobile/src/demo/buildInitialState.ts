import type {
  ActiveAlarmsPayload,
  Alarm,
  Asset,
  DashboardOverview,
  KanbanColumn,
  KanbanMetrics,
  Task,
  TaskComment,
  YardTrailer,
} from '../api/types';
import { COL, DEMO_BOARD_ID, DEMO_ORG_ID } from './constants';

function isoMinsAgo(m: number): string {
  return new Date(Date.now() - m * 60_000).toISOString();
}

function isoDaysFromNow(d: number): string {
  return new Date(Date.now() + d * 86400_000).toISOString();
}

export type DemoState = {
  columns: KanbanColumn[];
  tasks: Task[];
  alarms: Alarm[];
  assets: Asset[];
  trailers: YardTrailer[];
  commentsByTaskId: Record<string, TaskComment[]>;
  liveTick: number;
};

export function buildInitialDemoState(): DemoState {
  const columns: KanbanColumn[] = [
    {
      id: COL.backlog,
      board_id: DEMO_BOARD_ID,
      name: 'Backlog',
      position: 0,
      column_type: 'backlog',
      color: '#475569',
      task_count: 0,
    },
    {
      id: COL.triage,
      board_id: DEMO_BOARD_ID,
      name: 'Triage',
      position: 1,
      column_type: 'triage',
      color: '#ca8a04',
      task_count: 0,
    },
    {
      id: COL.inProgress,
      board_id: DEMO_BOARD_ID,
      name: 'In progress',
      position: 2,
      column_type: 'in_progress',
      color: '#2563eb',
      task_count: 0,
    },
    {
      id: COL.review,
      board_id: DEMO_BOARD_ID,
      name: 'Review',
      position: 3,
      column_type: 'review',
      color: '#9333ea',
      task_count: 0,
    },
    {
      id: COL.done,
      board_id: DEMO_BOARD_ID,
      name: 'Done',
      position: 4,
      column_type: 'done',
      color: '#15803d',
      task_count: 0,
    },
  ];

  const typeMachine = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1';
  const typeVehicle = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2';

  const tasks: Task[] = [
    {
      id: 'tttttttt-0001-4000-8000-000000000001',
      board_id: DEMO_BOARD_ID,
      column_id: COL.backlog,
      title: 'Approve: hot work permit — Tank farm C',
      description:
        'OSHA requires dual sign-off before welding near diked area. Edge case: approval_status pending.',
      task_type: 'safety',
      priority: 'critical',
      status: 'open',
      approval_status: 'pending',
      asset_id: 'aaaaaaaa-0001-4000-8000-000000000001',
      assigned_at: isoMinsAgo(18),
      due_date: isoDaysFromNow(0),
      created_at: isoMinsAgo(120),
      updated_at: isoMinsAgo(18),
      completed_at: null,
    },
    {
      id: 'tttttttt-0002-4000-8000-000000000001',
      board_id: DEMO_BOARD_ID,
      column_id: COL.backlog,
      title: 'Line 2 changeover — blueberry → original',
      description: 'Kanban backlog item ready to start (no approval gate).',
      task_type: 'changeover',
      priority: 'high',
      status: 'open',
      approval_status: 'approved',
      asset_id: 'aaaaaaaa-0002-4000-8000-000000000001',
      assigned_at: isoMinsAgo(40),
      due_date: isoDaysFromNow(1),
      created_at: isoMinsAgo(200),
      updated_at: isoMinsAgo(40),
      completed_at: null,
    },
    {
      id: 'tttttttt-0003-4000-8000-000000000001',
      board_id: DEMO_BOARD_ID,
      column_id: COL.backlog,
      title: 'Empty description + low priority stress test',
      description: null,
      task_type: 'maintenance',
      priority: 'low',
      status: 'open',
      approval_status: 'approved',
      asset_id: null,
      assigned_at: null,
      due_date: null,
      created_at: isoMinsAgo(300),
      updated_at: isoMinsAgo(300),
      completed_at: null,
    },
    {
      id: 'tttttttt-0004-4000-8000-000000000001',
      board_id: DEMO_BOARD_ID,
      column_id: COL.triage,
      title: 'Dock door 7 sensor flapping — verify IO',
      description: 'Intermittent fault; triage before assigning maint crew.',
      task_type: 'diagnostic',
      priority: 'emergency',
      status: 'open',
      approval_status: 'not_required',
      asset_id: 'aaaaaaaa-0003-4000-8000-000000000001',
      assigned_at: isoMinsAgo(12),
      due_date: isoDaysFromNow(0),
      created_at: isoMinsAgo(45),
      updated_at: isoMinsAgo(12),
      completed_at: null,
    },
    {
      id: 'tttttttt-0005-4000-8000-000000000001',
      board_id: DEMO_BOARD_ID,
      column_id: COL.triage,
      title: 'Yard shuttle OT-4 blocked at Gate B (geofence)',
      description: 'Telematics shows dwell >45m; confirm with yard camera.',
      task_type: 'logistics',
      priority: 'high',
      status: 'open',
      approval_status: 'not_required',
      asset_id: 'aaaaaaaa-0004-4000-8000-000000000001',
      assigned_at: isoMinsAgo(25),
      due_date: null,
      created_at: isoMinsAgo(30),
      updated_at: isoMinsAgo(25),
      completed_at: null,
    },
    {
      id: 'tttttttt-0006-4000-8000-000000000001',
      board_id: DEMO_BOARD_ID,
      column_id: COL.inProgress,
      title: 'Rebuild palletizer gripper — Line 5',
      description: 'Supervisor accepted; in progress. Long title padding test ' + 'x'.repeat(20),
      task_type: 'maintenance',
      priority: 'high',
      status: 'in_progress',
      approval_status: 'approved',
      asset_id: 'aaaaaaaa-0005-4000-8000-000000000001',
      assigned_at: isoMinsAgo(90),
      due_date: isoDaysFromNow(2),
      created_at: isoMinsAgo(400),
      updated_at: isoMinsAgo(5),
      completed_at: null,
    },
    {
      id: 'tttttttt-0007-4000-8000-000000000001',
      board_id: DEMO_BOARD_ID,
      column_id: COL.inProgress,
      title: 'Stamp press — tonnage drift investigation',
      description: 'OEE dip correlated with PackML Execute dwell.',
      task_type: 'quality',
      priority: 'medium',
      status: 'in_progress',
      approval_status: 'approved',
      asset_id: 'aaaaaaaa-0006-4000-8000-000000000001',
      assigned_at: isoMinsAgo(200),
      due_date: isoDaysFromNow(3),
      created_at: isoMinsAgo(600),
      updated_at: isoMinsAgo(20),
      completed_at: null,
    },
    {
      id: 'tttttttt-0008-4000-8000-000000000001',
      board_id: DEMO_BOARD_ID,
      column_id: COL.review,
      title: 'Batch release BR-4481 — microbiology hold',
      description: 'Awaiting QA sign-off on lab results.',
      task_type: 'quality',
      priority: 'critical',
      status: 'review',
      approval_status: 'approved',
      asset_id: 'aaaaaaaa-0007-4000-8000-000000000001',
      assigned_at: isoMinsAgo(300),
      due_date: isoDaysFromNow(0),
      created_at: isoMinsAgo(800),
      updated_at: isoMinsAgo(60),
      completed_at: null,
    },
    {
      id: 'tttttttt-0009-4000-8000-000000000001',
      board_id: DEMO_BOARD_ID,
      column_id: COL.review,
      title: 'Contractor badge audit — night shift',
      description: 'Review column edge case: two tasks competing for attention.',
      task_type: 'compliance',
      priority: 'medium',
      status: 'review',
      approval_status: 'approved',
      asset_id: null,
      assigned_at: isoMinsAgo(400),
      due_date: null,
      created_at: isoMinsAgo(900),
      updated_at: isoMinsAgo(120),
      completed_at: null,
    },
    {
      id: 'tttttttt-0010-4000-8000-000000000001',
      board_id: DEMO_BOARD_ID,
      column_id: COL.done,
      title: 'Morning GEMBA — stamping hall',
      description: 'Completed today; reopen test target from Done.',
      task_type: 'operations',
      priority: 'low',
      status: 'done',
      approval_status: 'approved',
      asset_id: null,
      assigned_at: isoMinsAgo(500),
      due_date: null,
      created_at: isoMinsAgo(700),
      updated_at: isoMinsAgo(10),
      completed_at: isoMinsAgo(10),
    },
    {
      id: 'tttttttt-0011-4000-8000-000000000001',
      board_id: DEMO_BOARD_ID,
      column_id: COL.done,
      title: 'Red zone cleared — LOTO verified',
      description: 'Resolved earlier; appears under Completed segment.',
      task_type: 'safety',
      priority: 'high',
      status: 'done',
      approval_status: 'approved',
      asset_id: 'aaaaaaaa-0001-4000-8000-000000000001',
      assigned_at: isoMinsAgo(800),
      due_date: null,
      created_at: isoMinsAgo(1000),
      updated_at: isoMinsAgo(240),
      completed_at: isoMinsAgo(240),
    },
  ];

  const assets: Asset[] = [
    {
      id: 'aaaaaaaa-0001-4000-8000-000000000001',
      name: 'Tank farm C — skid loader (CAT-928)',
      organization_id: DEMO_ORG_ID,
      asset_type_id: typeVehicle,
      current_packml_state: 'Execute',
      is_active: true,
      last_seen: isoMinsAgo(2),
    },
    {
      id: 'aaaaaaaa-0002-4000-8000-000000000001',
      name: 'Line 2 Filler / Capper',
      organization_id: DEMO_ORG_ID,
      asset_type_id: typeMachine,
      current_packml_state: 'Idle',
      is_active: true,
      last_seen: isoMinsAgo(1),
    },
    {
      id: 'aaaaaaaa-0003-4000-8000-000000000001',
      name: 'Dock cluster 7 — IO gateway',
      organization_id: DEMO_ORG_ID,
      asset_type_id: typeMachine,
      current_packml_state: 'Held',
      is_active: true,
      last_seen: isoMinsAgo(4),
    },
    {
      id: 'aaaaaaaa-0004-4000-8000-000000000001',
      name: 'Yard shuttle OMNI-OT4',
      organization_id: DEMO_ORG_ID,
      asset_type_id: typeVehicle,
      current_packml_state: 'Execute',
      is_active: true,
      last_seen: isoMinsAgo(3),
    },
    {
      id: 'aaaaaaaa-0005-4000-8000-000000000001',
      name: 'Line 5 Palletizer (Fanuc)',
      organization_id: DEMO_ORG_ID,
      asset_type_id: typeMachine,
      current_packml_state: 'Complete',
      is_active: true,
      last_seen: isoMinsAgo(6),
    },
    {
      id: 'aaaaaaaa-0006-4000-8000-000000000001',
      name: 'Stamp press Line 3 (Schuler)',
      organization_id: DEMO_ORG_ID,
      asset_type_id: typeMachine,
      current_packml_state: 'Execute',
      is_active: false,
      last_seen: isoMinsAgo(400),
    },
    {
      id: 'aaaaaaaa-0007-4000-8000-000000000001',
      name: 'Pasteurizer P-12',
      organization_id: DEMO_ORG_ID,
      asset_type_id: typeMachine,
      current_packml_state: 'Idle',
      is_active: true,
      last_seen: isoMinsAgo(8),
    },
    {
      id: 'aaaaaaaa-0008-4000-8000-000000000001',
      name: 'Chiller yard unit Y-2 (inactive demo)',
      organization_id: DEMO_ORG_ID,
      asset_type_id: typeMachine,
      current_packml_state: 'Aborted',
      is_active: false,
      last_seen: isoMinsAgo(5000),
    },
  ];

  const trailers: YardTrailer[] = [
    {
      id: 'dddddddd-0001-4000-8000-000000000001',
      trailer_number: '53ft · OTR-8842 (reefer)',
      status: 'docked',
      yard_location: 'Door 12 — inbound produce',
      organization_id: DEMO_ORG_ID,
    },
    {
      id: 'dddddddd-0002-4000-8000-000000000001',
      trailer_number: 'Dry van · LTL-9910',
      status: 'yard',
      yard_location: 'Row C slot 4',
      organization_id: DEMO_ORG_ID,
    },
    {
      id: 'dddddddd-0003-4000-8000-000000000001',
      trailer_number: 'Flatbed · FB-2201 (steel coils)',
      status: 'checked_in',
      yard_location: 'Security lane 2',
      organization_id: DEMO_ORG_ID,
    },
    {
      id: 'dddddddd-0004-4000-8000-000000000001',
      trailer_number: 'Tanker · CHEM-441 (null location edge)',
      status: 'en_route',
      yard_location: null,
      organization_id: DEMO_ORG_ID,
    },
    {
      id: 'dddddddd-0005-4000-8000-000000000001',
      trailer_number: '53ft · INT-7720 (checked out)',
      status: 'checked_out',
      yard_location: null,
      organization_id: DEMO_ORG_ID,
    },
    {
      id: 'dddddddd-0006-4000-8000-000000000001',
      trailer_number: 'Intermodal · IMX-505 (held — paperwork)',
      status: 'held',
      yard_location: 'Holding pen B',
      organization_id: DEMO_ORG_ID,
    },
  ];

  const alarms: Alarm[] = [
    {
      id: 'eeeeeeee-0001-4000-8000-000000000001',
      asset_id: 'aaaaaaaa-0006-4000-8000-000000000001',
      alarm_code: 'PRESS-TON-DRIFT',
      severity: 'critical',
      message: 'Stamp press tonnage outside ±3σ band',
      description: 'Auto-latched on three consecutive cycles. Operator acknowledged HMI banner.',
      is_active: true,
      is_acknowledged: false,
      occurred_at: isoMinsAgo(6),
      acknowledged_at: null,
      acknowledged_comment: null,
      cleared_at: null,
    },
    {
      id: 'eeeeeeee-0002-4000-8000-000000000001',
      asset_id: 'aaaaaaaa-0003-4000-8000-000000000001',
      alarm_code: 'DOOR-SENSOR-FLAP',
      severity: 'high',
      message: 'Dock door 7 sensor oscillating (chattering)',
      description: 'Debounce window exceeded 50 transitions/min.',
      is_active: true,
      is_acknowledged: false,
      occurred_at: isoMinsAgo(14),
      acknowledged_at: null,
      acknowledged_comment: null,
      cleared_at: null,
    },
    {
      id: 'eeeeeeee-0003-4000-8000-000000000001',
      asset_id: 'aaaaaaaa-0004-4000-8000-000000000001',
      alarm_code: 'YARD-DWELL',
      severity: 'medium',
      message: 'Yard shuttle dwell exceeded policy (45 min)',
      description: 'Geofence Gate B. Confirm driver swap.',
      is_active: true,
      is_acknowledged: false,
      occurred_at: isoMinsAgo(22),
      acknowledged_at: null,
      acknowledged_comment: null,
      cleared_at: null,
    },
    {
      id: 'eeeeeeee-0004-4000-8000-000000000001',
      asset_id: 'aaaaaaaa-0002-4000-8000-000000000001',
      alarm_code: 'FILLER-SPEED',
      severity: 'high',
      message: 'Filler speed mismatch vs line encoder',
      description: 'Edge: acknowledged but still active until maintenance clears.',
      is_active: true,
      is_acknowledged: true,
      occurred_at: isoMinsAgo(40),
      acknowledged_at: isoMinsAgo(35),
      acknowledged_comment: 'Reduced rate 8%; watching trend',
      cleared_at: null,
    },
    {
      id: 'eeeeeeee-0005-4000-8000-000000000001',
      asset_id: 'aaaaaaaa-0005-4000-8000-000000000001',
      alarm_code: 'PALLET-JAM',
      severity: 'medium',
      message: 'Palletizer lane 2 soft jam',
      description: 'Cleared locally; history row for resolved tab.',
      is_active: false,
      is_acknowledged: true,
      occurred_at: isoMinsAgo(180),
      acknowledged_at: isoMinsAgo(175),
      acknowledged_comment: 'Removed skewed pallet',
      cleared_at: isoMinsAgo(170),
    },
    {
      id: 'eeeeeeee-0006-4000-8000-000000000001',
      asset_id: 'aaaaaaaa-0001-4000-8000-000000000001',
      alarm_code: 'TEMP-WATCH',
      severity: 'low',
      message: 'Tank farm ambient approaching high advisory',
      description: 'Non-latching advisory; resolved automatically.',
      is_active: false,
      is_acknowledged: false,
      occurred_at: isoMinsAgo(400),
      acknowledged_at: null,
      acknowledged_comment: null,
      cleared_at: isoMinsAgo(380),
    },
    {
      id: 'eeeeeeee-0007-4000-8000-000000000001',
      asset_id: 'aaaaaaaa-0007-4000-8000-000000000001',
      alarm_code: 'PASTEUR-HOLD',
      severity: 'critical',
      message: 'Pasteurizer hold timer exceeded',
      description: 'QA hold — batch correlation BR-4481.',
      is_active: true,
      is_acknowledged: true,
      occurred_at: isoMinsAgo(55),
      acknowledged_at: isoMinsAgo(50),
      acknowledged_comment: 'QA notified',
      cleared_at: null,
    },
    {
      id: 'eeeeeeee-0008-4000-8000-000000000001',
      asset_id: 'aaaaaaaa-0006-4000-8000-000000000001',
      alarm_code: 'LUBE-LOW',
      severity: 'low',
      message: 'Press centralized lube low (predictive)',
      description: 'Informational; included for severity spread.',
      is_active: true,
      is_acknowledged: false,
      occurred_at: isoMinsAgo(120),
      acknowledged_at: null,
      acknowledged_comment: null,
      cleared_at: null,
    },
  ];

  const commentsByTaskId: Record<string, TaskComment[]> = {
    'tttttttt-0006-4000-8000-000000000001': [
      {
        id: 'nnnnnnnn-0001-4000-8000-000000000001',
        content: 'Parts cage issued seal kit SK-221.',
        comment_type: 'comment',
        created_at: isoMinsAgo(120),
      },
      {
        id: 'nnnnnnnn-0002-4000-8000-000000000001',
        content: 'Second shift will finish torque pass.',
        comment_type: 'comment',
        created_at: isoMinsAgo(60),
      },
    ],
    'tttttttt-0001-4000-8000-000000000001': [
      {
        id: 'nnnnnnnn-0003-4000-8000-000000000001',
        content: 'Fire watch assigned: J. Rivera',
        comment_type: 'comment',
        created_at: isoMinsAgo(30),
      },
    ],
  };

  for (const c of columns) {
    c.task_count = tasks.filter((t) => t.column_id === c.id).length;
  }

  return {
    columns,
    tasks,
    alarms,
    assets,
    trailers,
    commentsByTaskId,
    liveTick: 0,
  };
}

export function metricsFromState(state: DemoState): KanbanMetrics {
  const tasks_by_column: Record<string, number> = {};
  for (const c of state.columns) {
    tasks_by_column[c.column_type] = 0;
  }
  for (const t of state.tasks) {
    const col = state.columns.find((c) => c.id === t.column_id);
    if (col) {
      tasks_by_column[col.column_type] = (tasks_by_column[col.column_type] ?? 0) + 1;
    }
  }
  const startOfDay = new Date();
  startOfDay.setHours(0, 0, 0, 0);
  const tasks_completed_today = state.tasks.filter(
    (t) =>
      t.completed_at != null &&
      new Date(t.completed_at) >= startOfDay &&
      state.columns.find((c) => c.id === t.column_id)?.column_type === 'done'
  ).length;
  const tasks_awaiting_approval = state.tasks.filter(
    (t) => t.approval_status === 'pending'
  ).length;
  return {
    total_tasks: state.tasks.length,
    tasks_by_column,
    tasks_completed_today,
    tasks_awaiting_approval,
  };
}

export function activeAlarmsPayload(state: DemoState): ActiveAlarmsPayload {
  const alarms = state.alarms.filter((a) => a.is_active && !a.is_acknowledged);
  return { count: alarms.length, alarms };
}

export function dashboardOverviewFromState(state: DemoState): DashboardOverview {
  const assets_by_state: Record<string, number> = {};
  for (const a of state.assets) {
    assets_by_state[a.current_packml_state] = (assets_by_state[a.current_packml_state] ?? 0) + 1;
  }
  const active = state.alarms.filter((x) => x.is_active);
  const critical = state.alarms.filter((x) => x.is_active && x.severity === 'critical');
  return {
    total_assets: state.assets.length,
    active_assets: state.assets.filter((a) => a.is_active).length,
    assets_by_state,
    active_alarms: active.length,
    critical_alarms: critical.length,
  };
}
