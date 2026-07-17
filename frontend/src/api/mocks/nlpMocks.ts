/**
 * Mock fixtures for the NLP / Correlation AI surfaces (analysis sessions,
 * intake inbox, user context) used when VITE_USE_MOCK=true.
 *
 * The dataset tells one coherent incident end-to-end so demos read as a story:
 * a delayed bearing shipment (logistics) leaves the Line 3 CNC spindle running
 * degraded (shop floor), driving scrap cost and an open SAP work order
 * (financials) that puts a customer order at risk (client-facing).
 *
 * All timestamps are fixed ISO literals so headless renders are deterministic.
 */

import type {
  AnalysisSession,
  SessionMessage,
  DataSource,
  SuggestedQuestionsResponse,
  SessionListResponse,
} from '../analysisSessions';
import type { UserContext } from '../userContext';
import type { IntakeItem } from '../nlpCorrelation';

const ORG_ID = 'org-1';
const USER_ID = 'user-demo-1';

export const MOCK_SESSION_ID = 'session-demo-1';

export const mockAnalysisSessions: AnalysisSession[] = [
  {
    id: MOCK_SESSION_ID,
    user_id: USER_ID,
    organization_id: ORG_ID,
    title: 'Line 3 Spindle Degradation — Cross-Source Investigation',
    description: 'Scrap-rate spike traced across logistics, telemetry, maintenance and ERP',
    status: 'active',
    created_at: '2026-07-08T13:05:00Z',
    updated_at: '2026-07-08T14:41:00Z',
    last_accessed_at: '2026-07-08T14:41:00Z',
    context_snapshot: { focus: 'line-3', window_days: 7 },
    goals_snapshot: { otif_target: 0.97, scrap_target: 0.015 },
    data_sources_count: 6,
    messages_count: 2,
  },
  {
    id: 'session-demo-2',
    user_id: USER_ID,
    organization_id: ORG_ID,
    title: 'Dock 2 Throughput Review',
    description: 'Inbound staging times vs carrier ETAs',
    status: 'active',
    created_at: '2026-07-06T09:12:00Z',
    updated_at: '2026-07-06T10:02:00Z',
    last_accessed_at: '2026-07-06T10:02:00Z',
    context_snapshot: {},
    goals_snapshot: {},
    data_sources_count: 3,
    messages_count: 5,
  },
];

export const mockSessionListResponse = (status?: string): SessionListResponse => ({
  sessions: status
    ? mockAnalysisSessions.filter((s) => s.status === status)
    : mockAnalysisSessions,
  total: mockAnalysisSessions.length,
});

export const mockSessionMessages: Record<string, SessionMessage[]> = {
  [MOCK_SESSION_ID]: [
    {
      id: 'msg-demo-1',
      session_id: MOCK_SESSION_ID,
      role: 'user',
      content:
        "Why did Line 3's scrap rate jump 3.4% last week? I've added the production log, compressor report and whiteboard photo.",
      timestamp: '2026-07-08T14:32:00Z',
    },
    {
      id: 'msg-demo-2',
      session_id: MOCK_SESSION_ID,
      role: 'assistant',
      risk_score: 78,
      domains: ['telemetry', 'maintenance', 'erp', 'quality', 'logistics', 'finance'],
      content: [
        '### What happened on Line 3',
        'Scrap rate rose **3.4%** between Jul 1–7. Correlating all six sources points to a single chain of events:',
        '1. **Logistics** — inbound shipment **SHP-2214** (spindle bearing stock) arrived 2 days late. **Dock Camera — Door 3** motion timestamps confirm material staged after 14:00 on Jul 2.',
        '2. **Shop floor** — the production log Downtime tab aligns with the QC Defects tab: asset_id=asset-8, vibration_level=7.8 mm/s against a 4.5 threshold, and the Compressor Room acoustic monitor shows a **+6 dB** rise. The whiteboard note "spindle whine after 13:00" matches the vibration onset.',
        '3. **Maintenance** — **Compressor_Service_Report.pdf** pages 4 and 7 flag progressive bearing wear; SAP work order **WO-4482** (bearing replacement) is still open, correlated **0.82** with the vibration trend.',
        '4. **Financials and customer** — estimated_cost_impact_usd=$18,400 in scrap so far. Invoice **INV-55810** risks a rework charge and customer order **SO-88231** slips 2 days unless the PM is pulled forward.',
      ].join('\n'),
      actions: [
        { description: 'Derate Line 3 spindle RPM by 15% until the PM window' },
        { description: 'Expedite SHP-2214 via alternate carrier (recovers 1 day)' },
        { description: 'Pull SAP bearing kit BOM-2231 for WO-4482' },
        { description: 'Notify account owner: SO-88231 ETA at risk' },
      ],
      follow_up_questions: [
        'Which other assets share this bearing wear profile?',
        'Show the 30-day acoustic trend for the compressor room',
        'Break down the $18.4k scrap cost by shift',
      ],
      timestamp: '2026-07-08T14:33:10Z',
    },
  ],
};

export const mockDataSources: Record<string, DataSource[]> = {
  [MOCK_SESSION_ID]: [
    {
      id: 'ds-1',
      session_id: MOCK_SESSION_ID,
      source_type: 'upload',
      source_id: null,
      file_name: 'Q3_Production_Log.xlsx',
      data_type: 'spreadsheet',
      added_at: '2026-07-08T13:08:00Z',
    },
    {
      id: 'ds-2',
      session_id: MOCK_SESSION_ID,
      source_type: 'upload',
      source_id: null,
      file_name: 'Compressor_Service_Report.pdf',
      data_type: 'report',
      added_at: '2026-07-08T13:09:00Z',
    },
    {
      id: 'ds-3',
      session_id: MOCK_SESSION_ID,
      source_type: 'upload',
      source_id: null,
      file_name: 'Whiteboard_Shift_Handover_Jul8.jpg',
      data_type: 'image',
      added_at: '2026-07-08T13:10:00Z',
    },
    {
      id: 'ds-4',
      session_id: MOCK_SESSION_ID,
      source_type: 'platform',
      source_id: 'erp_work_orders',
      file_name: 'SAP work orders (live)',
      data_type: 'erp',
      added_at: '2026-07-08T13:11:00Z',
    },
    {
      id: 'ds-5',
      session_id: MOCK_SESSION_ID,
      source_type: 'platform',
      source_id: 'telemetry:asset-8',
      file_name: 'Vibration Sensor — CNC Spindle (live)',
      data_type: 'telemetry',
      added_at: '2026-07-08T13:11:30Z',
    },
    {
      id: 'ds-6',
      session_id: MOCK_SESSION_ID,
      source_type: 'platform',
      source_id: 'acoustic:asset-6',
      file_name: 'Acoustic Monitor — Compressor Room (live)',
      data_type: 'audio',
      added_at: '2026-07-08T13:12:00Z',
    },
  ],
};

export const mockSuggestedQuestions: SuggestedQuestionsResponse = {
  questions: [
    'What trends do you see across all six sources?',
    'Which shifts drive the QC defect clusters?',
    'How does the SHP-2214 delay affect open orders?',
  ],
  items: [
    { question: 'What trends do you see across all six sources?', category: 'correlation' },
    { question: 'Which shifts drive the QC defect clusters?', category: 'quality' },
    { question: 'How does the SHP-2214 delay affect open orders?', category: 'logistics' },
  ],
  context_summary: '6 sources · 4 domains correlated',
};

export const mockUserContext: UserContext = {
  id: USER_ID,
  email: 'ops.director@omniusgrid.io',
  full_name: 'Jordan Reyes',
  role: 'Operations Director',
  department: 'Manufacturing Operations',
  priorities: ['Reduce unplanned downtime', 'OTIF ≥ 97%', 'Scrap < 1.5%'],
  user_context: { scope: 'multi-departmental', sites: ['Plant A'] },
  user_goals: [
    {
      id: 'goal-1',
      title: 'Cut Line 3 unplanned downtime 20%',
      progress: 62,
      deadline: '2026-09-30T00:00:00Z',
    },
    {
      id: 'goal-2',
      title: 'Inbound dock-to-stage under 45 min',
      progress: 78,
      deadline: '2026-08-15T00:00:00Z',
    },
    {
      id: 'goal-3',
      title: 'Scrap rate below 1.5% plant-wide',
      progress: 40,
      deadline: '2026-12-31T00:00:00Z',
    },
  ],
};

// ---- RealTimeDataPanel session context tabs ----

export const mockTelemetryContext = {
  count: 4,
  telemetry: [
    {
      asset_name: 'Vibration Sensor — CNC Spindle',
      timestamp: '2026-07-08T14:30:00Z',
      metric_name: 'vibration_rms',
      value: 7.8,
      unit: 'mm/s',
      packml_state: 'Execute',
    },
    {
      asset_name: 'Acoustic Monitor — Compressor Room',
      timestamp: '2026-07-08T14:30:00Z',
      metric_name: 'audio_rms',
      value: 71.2,
      unit: 'dB',
    },
    {
      asset_name: 'CNC Mill #1',
      timestamp: '2026-07-08T14:29:00Z',
      metric_name: 'spindle_load',
      value: 84,
      unit: '%',
      packml_state: 'Execute',
    },
    {
      asset_name: 'Dock Camera — Door 3',
      timestamp: '2026-07-08T14:28:00Z',
      metric_name: 'motion_score',
      value: 0.31,
    },
  ],
};

export const mockAlarmsContext = {
  count: 2,
  alarms: [
    {
      id: 'ctx-alarm-1',
      asset_name: 'Vibration Sensor — CNC Spindle',
      severity: 'critical',
      alarm_code: 'VIB_RMS_HIGH',
      description: 'Vibration above 4.5 mm/s for 30+ min',
      is_active: true,
      is_acknowledged: true,
    },
    {
      id: 'ctx-alarm-2',
      asset_name: 'Acoustic Monitor — Compressor Room',
      severity: 'high',
      alarm_code: 'AUDIO_ANOMALY',
      description: 'Acoustic signature +6 dB over baseline',
      is_active: true,
      is_acknowledged: false,
    },
  ],
};

export const mockKanbanContext = {
  count: 3,
  tasks: [
    {
      id: 'ctx-task-1',
      title: 'Replace spindle bearing kit (WO-4482)',
      priority: 'critical',
      status: 'in_progress',
      progress_percent: 35,
    },
    {
      id: 'ctx-task-2',
      title: 'Expedite SHP-2214 alternate carrier',
      priority: 'high',
      status: 'ready',
      progress_percent: 0,
    },
    {
      id: 'ctx-task-3',
      title: 'Contain lot QL-3391',
      priority: 'high',
      status: 'in_progress',
      progress_percent: 60,
    },
  ],
};

export const mockRegistriesContext = {
  count: 2,
  registry_items: [
    {
      id: 'ctx-reg-1',
      title: 'Bearing wear advisory — Compressor_Service_Report p.4/7',
      severity: 'high',
      status: 'open',
      due_date: '2026-07-11T00:00:00Z',
    },
    {
      id: 'ctx-reg-2',
      title: 'CT-PAT carrier compliance check — SHP-2214',
      severity: 'medium',
      status: 'open',
      due_date: '2026-07-10T00:00:00Z',
    },
  ],
};

// ---- Intake Inbox ----

export const mockIntakeItems: IntakeItem[] = [
  {
    id: 'intake-1',
    title: 'Q3 Production Log',
    description: 'Multi-tab production log: Output, Downtime, QC Defects',
    data_type: 'spreadsheet',
    category: 'production',
    file_name: 'Q3_Production_Log.xlsx',
    status: 'analyzed',
    analysis_result: {
      risk_score: 78,
      domains_analyzed: ['quality', 'telemetry', 'maintenance'],
      analysis:
        '3 tabs, 1,412 rows. Two anomaly clusters found: downtime rows on Line 3 align with QC defect spikes after Jul 2. Correlated with vibration telemetry on asset-8.',
    },
    created_at: '2026-07-08T13:08:00Z',
    analyzed_at: '2026-07-08T13:12:00Z',
  },
  {
    id: 'intake-2',
    title: 'Compressor Service Report',
    description: 'Vendor service report, June inspection',
    data_type: 'report',
    category: 'maintenance',
    file_name: 'Compressor_Service_Report.pdf',
    status: 'analyzed',
    analysis_result: {
      risk_score: 64,
      domains_analyzed: ['maintenance', 'acoustics'],
      analysis:
        'Pages 4 and 7 flag progressive bearing wear. Recommendation matches open SAP work order WO-4482 and the compressor-room acoustic trend.',
    },
    created_at: '2026-07-08T12:50:00Z',
    analyzed_at: '2026-07-08T12:57:00Z',
  },
  {
    id: 'intake-3',
    title: 'Shift Handover Whiteboard',
    description: 'Photo of the Jul 8 shift handover whiteboard',
    data_type: 'image',
    category: 'operations',
    file_name: 'Whiteboard_Shift_Handover_Jul8.jpg',
    status: 'analyzed',
    analysis_result: {
      risk_score: 41,
      domains_analyzed: ['operations', 'maintenance'],
      analysis:
        'OCR extracted 9 notes. "Spindle whine after 13:00" matches the vibration onset on asset-8; "Door 3 staging late again" matches dock camera timestamps.',
    },
    created_at: '2026-07-08T13:02:00Z',
    analyzed_at: '2026-07-08T13:06:00Z',
  },
  {
    id: 'intake-4',
    title: 'SAP Work Orders Export',
    description: 'Open work orders export from SAP S/4HANA',
    data_type: 'spreadsheet',
    category: 'erp',
    file_name: 'SAP_WorkOrders_Export.csv',
    status: 'analyzed',
    analysis_result: {
      risk_score: 55,
      domains_analyzed: ['erp', 'maintenance', 'finance'],
      analysis:
        'WO-4482 (spindle bearing replacement) open 11 days. Parts pending against delayed shipment SHP-2214; invoice INV-55810 flagged for rework-charge risk.',
    },
    created_at: '2026-07-08T11:40:00Z',
    analyzed_at: '2026-07-08T11:47:00Z',
  },
  {
    id: 'intake-5',
    title: 'Compressor Room Audio Sample',
    description: '10-minute acoustic capture, compressor room',
    data_type: 'document',
    category: 'acoustics',
    file_name: 'Compressor_Room_Audio_Sample.wav',
    status: 'analyzed',
    analysis_result: {
      risk_score: 67,
      domains_analyzed: ['acoustics', 'telemetry'],
      analysis:
        'Signature +6 dB over baseline with harmonics consistent with bearing wear. Matches vibration_rms trend on asset-8 (correlation 0.82).',
    },
    created_at: '2026-07-08T10:20:00Z',
    analyzed_at: '2026-07-08T10:31:00Z',
  },
  {
    id: 'intake-6',
    title: 'Bay 2 Dock Camera Clip',
    description: 'Door 3 staging footage, Jul 2 shift change',
    data_type: 'document',
    category: 'logistics',
    file_name: 'Bay2_Dock_Camera_Clip.mp4',
    status: 'analyzing',
    created_at: '2026-07-08T14:36:00Z',
  },
];

export const mockIntakeList = (status?: string): { items: IntakeItem[]; total: number } => {
  const items = status ? mockIntakeItems.filter((i) => i.status === status) : mockIntakeItems;
  return { items, total: items.length };
};
