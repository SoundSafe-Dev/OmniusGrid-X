// Mock API data for demo mode when backend is unavailable
import { 
  Asset, Alarm, TelemetryPoint, DashboardOverview, 
  ActiveAlarmsResponse, OEEMetrics, FleetOEE, User,
  Workcell, Organization, PackMLState, AssetType
} from '../types';

// Simulated network delay; override with VITE_MOCK_DELAY=0 for deterministic renders
const MOCK_DELAY = Number(import.meta.env.VITE_MOCK_DELAY ?? 500);

const mockAssets: Asset[] = [
  {
    id: 'asset-1',
    name: 'Printer #1 (Bambu Labs X1)',
    assetTypeId: 'printer',
    organizationId: 'org-1',
    workcellId: 'workcell-1',
    vendor: 'Bambu Labs',
    model: 'X1 Carbon',
    serialNumber: 'BLX1001',
    currentPackmlState: 'Execute',
    connectionConfig: { protocol: 'MQTT', endpoint: '192.168.1.100' },
    isInMaintenance: false,
    isActive: true,
    lastSeen: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'asset-2',
    name: 'Printer #2 (Bambu Labs X1)',
    assetTypeId: 'printer',
    organizationId: 'org-1',
    workcellId: 'workcell-1',
    vendor: 'Bambu Labs',
    model: 'X1 Carbon',
    serialNumber: 'BLX1002',
    currentPackmlState: 'Idle',
    connectionConfig: { protocol: 'MQTT', endpoint: '192.168.1.101' },
    isInMaintenance: false,
    isActive: true,
    lastSeen: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'asset-3',
    name: 'Printer #3 (QIDI X-Max 3)',
    assetTypeId: 'printer',
    organizationId: 'org-1',
    workcellId: 'workcell-1',
    vendor: 'QIDI',
    model: 'X-Max 3',
    serialNumber: 'QX3001',
    currentPackmlState: 'Held',
    connectionConfig: { protocol: 'ScreenScrape', endpoint: '192.168.1.102' },
    isInMaintenance: false,
    isActive: true,
    lastSeen: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'asset-4',
    name: 'Conveyor Belt A',
    assetTypeId: 'conveyor',
    organizationId: 'org-1',
    workcellId: 'workcell-2',
    vendor: 'Siemens',
    model: 'SIMATIC CF-100',
    serialNumber: 'SCF2001',
    currentPackmlState: 'Execute',
    connectionConfig: { protocol: 'OPC-UA', endpoint: 'opc.tcp://192.168.1.200' },
    isInMaintenance: false,
    isActive: true,
    lastSeen: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'asset-5',
    name: 'CNC Mill #1',
    assetTypeId: 'cnc',
    organizationId: 'org-1',
    workcellId: 'workcell-3',
    vendor: 'Haas',
    model: 'VF-2',
    serialNumber: 'HAAS001',
    currentPackmlState: 'Idle',
    connectionConfig: { protocol: 'MTConnect', endpoint: '192.168.1.150' },
    isInMaintenance: false,
    isActive: true,
    lastSeen: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  // Demo sensor assets (sensor taxonomy, migration 024): audio / video / machinery.
  {
    id: 'asset-6',
    name: 'Acoustic Monitor — Compressor Room',
    assetTypeId: 'audio_sensor',
    organizationId: 'org-1',
    workcellId: 'workcell-3',
    vendor: 'SoundSafe',
    model: 'AM-100',
    serialNumber: 'SSAM100-01',
    currentPackmlState: 'Execute',
    connectionConfig: { protocol: 'edge-audio', endpoint: 'edge-agent:audio0' },
    sensorClass: 'audio',
    mediaConfig: { sample_rate: 16000, channels: 1 },
    isInMaintenance: false,
    isActive: true,
    lastSeen: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'asset-7',
    name: 'Dock Camera — Door 3',
    assetTypeId: 'video_camera',
    organizationId: 'org-1',
    workcellId: 'workcell-2',
    vendor: 'Axis',
    model: 'M2025',
    serialNumber: 'AXM2025-03',
    currentPackmlState: 'Execute',
    connectionConfig: { protocol: 'mjpeg', endpoint: '192.168.1.203' },
    sensorClass: 'video',
    mediaConfig: { stream_url: 'http://192.168.1.203/mjpeg', snapshot_interval: 30 },
    isInMaintenance: false,
    isActive: true,
    lastSeen: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'asset-8',
    name: 'Vibration Sensor — CNC Spindle',
    assetTypeId: 'vibration_sensor',
    organizationId: 'org-1',
    workcellId: 'workcell-3',
    vendor: 'IFM',
    model: 'VVB001',
    serialNumber: 'IFMVVB-08',
    currentPackmlState: 'Execute',
    connectionConfig: { protocol: 'io-link', endpoint: '192.168.1.150' },
    sensorClass: 'machinery',
    isInMaintenance: false,
    isActive: true,
    lastSeen: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockAlarms: Alarm[] = [
  {
    id: 'alarm-1',
    assetId: 'asset-3',
    assetName: 'Printer #3 (QIDI X-Max 3)',
    alarmCode: 'TEMP_HIGH',
    severity: 'high',
    message: 'Nozzle temperature exceeds safe threshold',
    description: 'The nozzle temperature has exceeded 280°C, which is above the safe operating limit.',
    isActive: true,
    isAcknowledged: false,
    occurredAt: new Date(Date.now() - 3600000).toISOString(),
  },
  {
    id: 'alarm-2',
    assetId: 'asset-1',
    assetName: 'Printer #1 (Bambu Labs X1)',
    alarmCode: 'FILAMENT_RUNOUT',
    severity: 'medium',
    message: 'Filament runout detected',
    description: 'The AMS has detected that filament has run out on spool 1.',
    isActive: true,
    isAcknowledged: true,
    acknowledgedBy: 'user-1',
    acknowledgedAt: new Date(Date.now() - 1800000).toISOString(),
    acknowledgedComment: 'Replenished filament',
    occurredAt: new Date(Date.now() - 7200000).toISOString(),
  },
  {
    id: 'alarm-3',
    assetId: 'asset-5',
    assetName: 'CNC Mill #1',
    alarmCode: 'SPINDLE_WARN',
    severity: 'low',
    message: 'Spindle bearing temperature elevated',
    description: 'Spindle bearing temperature is at 65°C, approaching warning threshold.',
    isActive: true,
    isAcknowledged: false,
    occurredAt: new Date(Date.now() - 10800000).toISOString(),
  },
  {
    id: 'alarm-4',
    assetId: 'asset-2',
    assetName: 'Printer #2 (Bambu Labs X1)',
    alarmCode: 'BED_LEVEL_FAIL',
    severity: 'critical',
    message: 'Bed leveling failed after 3 attempts',
    description: 'Automatic bed leveling procedure failed. Manual calibration required.',
    isActive: false,
    isAcknowledged: true,
    acknowledgedBy: 'user-1',
    acknowledgedAt: new Date(Date.now() - 86400000).toISOString(),
    acknowledgedComment: 'Recalibrated bed manually',
    occurredAt: new Date(Date.now() - 90000000).toISOString(),
    clearedAt: new Date(Date.now() - 85000000).toISOString(),
  },
];

const mockUsers: User[] = [
  {
    id: 'user-1',
    email: 'admin@omniusgrid.com',
    name: 'System Administrator',
    role: 'admin',
    organizationId: 'org-1',
    isActive: true,
    lastLoginAt: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'user-2',
    email: 'operator@omniusgrid.com',
    name: 'Line Operator',
    role: 'operator',
    organizationId: 'org-1',
    isActive: true,
    lastLoginAt: new Date(Date.now() - 86400000).toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockWorkcells: Workcell[] = [
  {
    id: 'workcell-1',
    organizationId: 'org-1',
    name: '3D Printing Line A',
    description: 'Bambu Labs and QIDI 3D printers',
    location: 'Building A, Floor 1',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'workcell-2',
    organizationId: 'org-1',
    name: 'Assembly Line B',
    description: 'Conveyor and packaging systems',
    location: 'Building A, Floor 2',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'workcell-3',
    organizationId: 'org-1',
    name: 'Machining Center',
    description: 'CNC mills and lathes',
    location: 'Building B, Floor 1',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockOrganizations: Organization[] = [
  {
    id: 'org-1',
    name: 'Main Factory',
    slug: 'main-factory',
    settings: { timezone: 'America/Chicago', language: 'en' },
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockAssetTypes: AssetType[] = [
  {
    id: 'printer',
    name: '3D Printer',
    category: 'additive_manufacturing',
    packmlConfig: { states: ['Idle', 'Execute', 'Held', 'Stopped'] },
    telemetrySchema: { temperature: 'number', progress: 'number' },
    actionSpace: ['start', 'stop', 'pause', 'resume'],
    createdAt: new Date().toISOString(),
  },
  {
    id: 'conveyor',
    name: 'Conveyor Belt',
    category: 'material_handling',
    packmlConfig: { states: ['Idle', 'Execute', 'Stopped'] },
    telemetrySchema: { speed: 'number', load: 'number' },
    actionSpace: ['start', 'stop', 'set_speed'],
    createdAt: new Date().toISOString(),
  },
  {
    id: 'cnc',
    name: 'CNC Machine',
    category: 'subtractive_manufacturing',
    packmlConfig: { states: ['Idle', 'Execute', 'Held', 'Stopped'] },
    telemetrySchema: { spindle_rpm: 'number', feed_rate: 'number' },
    actionSpace: ['start', 'stop', 'pause', 'home'],
    createdAt: new Date().toISOString(),
  },
  // Sensor taxonomy demo types (migration 024). These match the AssetType
  // interface (unlike the older entries above, which predate it).
  {
    id: 'audio_sensor',
    name: 'Acoustic Sensor',
    category: 'acoustic_monitoring',
    description: 'Audio feature telemetry (RMS, peak frequency, band energies)',
    capabilities: ['audio_rms', 'audio_peak_hz', 'fft_bands'],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'video_camera',
    name: 'Video Camera',
    category: 'visual_monitoring',
    description: 'Frame metrics (brightness, motion score) + live feed',
    capabilities: ['mjpeg_stream', 'motion_score', 'snapshots'],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'vibration_sensor',
    name: 'Vibration Sensor',
    category: 'condition_monitoring',
    description: 'Machinery condition metrics (vibration RMS, temperature, load)',
    capabilities: ['vibration_rms', 'temperature', 'load_percent'],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockDashboardOverview: DashboardOverview = {
  totalAssets: 24,
  activeAssets: 18,
  assetsByState: {
    Execute: 9,
    Idle: 6,
    Starting: 1,
    Held: 2,
    Suspended: 2,
    Stopped: 3,
    Aborted: 1,
  },
  activeAlarms: 3,
  criticalAlarms: 1,
};

// Pages adapted to the real API read raw snake_case fields (occurred_at,
// asset_name, alarm_code); mirror the camelCase fixtures onto those keys.
const withAssetSnakeAliases = (asset: Asset): Asset =>
  ({
    ...asset,
    current_packml_state: asset.currentPackmlState,
    is_active: asset.isActive,
    is_in_maintenance: asset.isInMaintenance,
    last_seen: asset.lastSeen,
    serial_number: asset.serialNumber,
  } as Asset);

const withAlarmSnakeAliases = (alarm: Alarm): Alarm =>
  ({
    ...alarm,
    asset_name: alarm.assetName,
    alarm_code: alarm.alarmCode,
    occurred_at: alarm.occurredAt,
    is_active: alarm.isActive,
    is_acknowledged: alarm.isAcknowledged,
  } as Alarm);

const mockActiveAlarms: ActiveAlarmsResponse = {
  count: 3,
  bySeverity: {
    critical: 1,
    high: 1,
    medium: 1,
    low: 0,
  },
  alarms: mockAlarms.filter(a => a.isActive),
};

const mockFleetOEE: FleetOEE = {
  timeRange: 'Last 24 hours',
  assetCount: 8,
  fleetAverageAvailability: 0.91,
  fleetAveragePerformance: 0.85,
  fleetAverageOee: 0.78,
  assets: [
    { assetId: 'asset-1', assetName: 'Printer #1 (Bambu Labs X1)', availability: 0.94, oee: 0.86 },
    { assetId: 'asset-2', assetName: 'Printer #2 (Bambu Labs X1)', availability: 0.92, oee: 0.81 },
    { assetId: 'asset-3', assetName: 'Printer #3 (QIDI X-Max 3)', availability: 0.89, oee: 0.77 },
    { assetId: 'asset-4', assetName: 'Conveyor Belt A', availability: 0.97, oee: 0.90 },
    { assetId: 'asset-5', assetName: 'CNC Mill #1', availability: 0.83, oee: 0.64 },
    { assetId: 'asset-6', assetName: 'Acoustic Monitor — Compressor Room', availability: 0.99, oee: 0.88 },
    { assetId: 'asset-7', assetName: 'Dock Camera — Door 3', availability: 0.98, oee: 0.87 },
    { assetId: 'asset-8', assetName: 'Vibration Sensor — CNC Spindle', availability: 0.86, oee: 0.61 },
  ],
};

const mockOEEMetrics: OEEMetrics = {
  oee: 0.78,
  availability: 0.91,
  performance: 0.85,
  quality: 0.99,
  runTimeMinutes: 480,
  plannedProductionTimeMinutes: 525,
  idealCycleTimeSeconds: 120,
  totalCount: 2400,
  goodCount: 2376,
  rejectedCount: 24,
};

// Helper to simulate async delay
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

// Deterministic helpers: demo values must be stable across mounts/renders
const round1 = (n: number) => Math.round(n * 10) / 10;
const deterministicNoise = (i: number) => {
  const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
};

// Mock API implementation
export const mockApi = {
  // Assets
  getAssets: async (): Promise<{ items: Asset[]; total: number; skip: number; limit: number; hasMore: boolean }> => {
    await delay(MOCK_DELAY);
    return {
      items: mockAssets.map(withAssetSnakeAliases),
      total: mockAssets.length,
      skip: 0,
      limit: 100,
      hasMore: false,
    };
  },
  
  getAsset: async (id: string): Promise<Asset | undefined> => {
    await delay(MOCK_DELAY);
    const asset = mockAssets.find(a => a.id === id);
    return asset && withAssetSnakeAliases(asset);
  },
  
  // Alarms
  getAlarms: async (): Promise<{ items: Alarm[]; total: number }> => {
    await delay(MOCK_DELAY);
    return { items: mockAlarms.map(withAlarmSnakeAliases), total: mockAlarms.length };
  },

  getActiveAlarms: async (): Promise<ActiveAlarmsResponse> => {
    await delay(MOCK_DELAY);
    return { ...mockActiveAlarms, alarms: mockActiveAlarms.alarms.map(withAlarmSnakeAliases) };
  },
  
  acknowledgeAlarm: async (id: string): Promise<void> => {
    await delay(MOCK_DELAY);
    const alarm = mockAlarms.find(a => a.id === id);
    if (alarm) {
      alarm.isAcknowledged = true;
      alarm.acknowledgedAt = new Date().toISOString();
    }
  },
  
  // Dashboard
  getDashboardOverview: async (): Promise<DashboardOverview> => {
    await delay(MOCK_DELAY);
    return mockDashboardOverview;
  },
  
  getFleetOEE: async (): Promise<FleetOEE> => {
    await delay(MOCK_DELAY);
    return mockFleetOEE;
  },
  
  getAssetOEE: async (_assetId: string): Promise<OEEMetrics> => {
    await delay(MOCK_DELAY);
    return mockOEEMetrics;
  },
  
  // Telemetry
  getLatestTelemetry: async (assetId: string): Promise<Record<string, TelemetryPoint>> => {
    await delay(MOCK_DELAY);
    
    const asset = mockAssets.find(a => a.id === assetId);
    const timestamp = new Date().toISOString();
    
    // Machine-specific telemetry based on asset type
    switch (asset?.assetTypeId) {
      case 'printer':
        return {
          'nozzle_temp': { metricName: 'nozzle_temp', value: round1(245.5 + 10 / 2), unit: '°C', timestamp },
          'bed_temp': { metricName: 'bed_temp', value: round1(65.0 + 5 / 2), unit: '°C', timestamp },
          'progress': { metricName: 'progress', value: round1(67.3 + 10 / 2), unit: '%', timestamp },
          'print_speed': { metricName: 'print_speed', value: round1(150.0 + 20 / 2), unit: 'mm/s', timestamp },
          'layer_height': { metricName: 'layer_height', value: 0.2, unit: 'mm', timestamp },
          'filament_used': { metricName: 'filament_used', value: 1234.5, unit: 'g', timestamp },
        };
      
      case 'conveyor':
        return {
          'speed': { metricName: 'speed', value: round1(2.5 + 0.5 / 2), unit: 'm/s', timestamp },
          'load': { metricName: 'load', value: round1(85.2 + 10 / 2), unit: '%', timestamp },
          'temperature': { metricName: 'temperature', value: round1(45.3 + 5 / 2), unit: '°C', timestamp },
          'vibration': { metricName: 'vibration', value: round1(0.8 + 0.2 / 2), unit: 'g', timestamp },
          'power_consumption': { metricName: 'power_consumption', value: round1(3.2 + 0.5 / 2), unit: 'kW', timestamp },
        };
      
      case 'cnc':
        return {
          'spindle_rpm': { metricName: 'spindle_rpm', value: round1(12000 + 1000 / 2), unit: 'RPM', timestamp },
          'feed_rate': { metricName: 'feed_rate', value: round1(500.0 + 50 / 2), unit: 'mm/min', timestamp },
          'spindle_load': { metricName: 'spindle_load', value: round1(75.3 + 10 / 2), unit: '%', timestamp },
          'tool_temperature': { metricName: 'tool_temperature', value: round1(35.2 + 3 / 2), unit: '°C', timestamp },
          'cutting_force': { metricName: 'cutting_force', value: round1(1250.5 + 100 / 2), unit: 'N', timestamp },
          'position_x': { metricName: 'position_x', value: 150.5, unit: 'mm', timestamp },
          'position_y': { metricName: 'position_y', value: 75.3, unit: 'mm', timestamp },
          'position_z': { metricName: 'position_z', value: -25.8, unit: 'mm', timestamp },
        };
      
      case 'audio_sensor':
        return {
          'audio_rms': { metricName: 'audio_rms', value: round1(0.18 + 0.1 / 2), unit: '', timestamp },
          'audio_peak_hz': { metricName: 'audio_peak_hz', value: round1(820 + 240 / 2), unit: 'Hz', timestamp },
          'audio_band_low': { metricName: 'audio_band_low', value: round1(0.32 + 0.1 / 2), unit: '', timestamp },
          'audio_band_mid': { metricName: 'audio_band_mid', value: round1(0.45 + 0.15 / 2), unit: '', timestamp },
          'audio_band_high': { metricName: 'audio_band_high', value: round1(0.12 + 0.08 / 2), unit: '', timestamp },
        };

      case 'video_camera':
        return {
          'frame_brightness': { metricName: 'frame_brightness', value: round1(118 + 30 / 2), unit: '', timestamp },
          'motion_score': { metricName: 'motion_score', value: 0.31, unit: '', timestamp },
          'frames_analyzed': { metricName: 'frames_analyzed', value: 14200 + 42, unit: '', timestamp },
        };

      case 'vibration_sensor':
        return {
          'vibration_rms': { metricName: 'vibration_rms', value: round1(1.8 + 0.9 / 2), unit: 'mm/s', timestamp },
          'temperature': { metricName: 'temperature', value: round1(52 + 8 / 2), unit: '°C', timestamp },
          'load_percent': { metricName: 'load_percent', value: round1(68 + 20 / 2), unit: '%', timestamp },
        };

      default:
        return {
          'status': { metricName: 'status', value: 1, unit: '', timestamp },
          'temperature': { metricName: 'temperature', value: round1(25.0 + 5 / 2), unit: '°C', timestamp },
        };
    }
  },
  
  getTelemetryHistory: async (assetId: string, metricName: string): Promise<TelemetryPoint[]> => {
    await delay(MOCK_DELAY);
    
    const asset = mockAssets.find(a => a.id === assetId);
    
    // Generate machine-specific historical data
    const generateHistory = (baseValue: number, variance: number, unit: string) => {
      return Array.from({ length: 50 }, (_, i) => ({
        metricName,
        value: round1(baseValue + (deterministicNoise(i) - 0.5) * variance),
        unit,
        timestamp: new Date(Date.now() - (49 - i) * 60000).toISOString(),
      }));
    };
    
    switch (asset?.assetTypeId) {
      case 'printer':
        switch (metricName) {
          case 'nozzle_temp':
            return generateHistory(245, 20, '°C');
          case 'bed_temp':
            return generateHistory(65, 10, '°C');
          case 'progress':
            return generateHistory(50, 30, '%');
          case 'print_speed':
            return generateHistory(150, 50, 'mm/s');
          default:
            return generateHistory(100, 20, '');
        }
      
      case 'conveyor':
        switch (metricName) {
          case 'speed':
            return generateHistory(2.5, 1, 'm/s');
          case 'load':
            return generateHistory(80, 20, '%');
          case 'temperature':
            return generateHistory(45, 10, '°C');
          case 'vibration':
            return generateHistory(0.8, 0.4, 'g');
          case 'power_consumption':
            return generateHistory(3.2, 1, 'kW');
          default:
            return generateHistory(50, 20, '');
        }
      
      case 'cnc':
        switch (metricName) {
          case 'spindle_rpm':
            return generateHistory(12000, 2000, 'RPM');
          case 'feed_rate':
            return generateHistory(500, 200, 'mm/min');
          case 'spindle_load':
            return generateHistory(75, 25, '%');
          case 'tool_temperature':
            return generateHistory(35, 10, '°C');
          case 'cutting_force':
            return generateHistory(1250, 300, 'N');
          default:
            return generateHistory(100, 50, '');
        }
      
      default:
        return generateHistory(25, 10, '°C');
    }
  },
  
  // Workcells & Organizations
  getWorkcells: async (): Promise<Workcell[]> => {
    await delay(MOCK_DELAY);
    return mockWorkcells;
  },
  
  getOrganizations: async (): Promise<Organization[]> => {
    await delay(MOCK_DELAY);
    return mockOrganizations;
  },
  
  // Asset Types
  getAssetTypes: async (): Promise<AssetType[]> => {
    await delay(MOCK_DELAY);
    return mockAssetTypes;
  },
  
  // Users
  getUsers: async (): Promise<{ items: User[]; total: number }> => {
    await delay(MOCK_DELAY);
    return { items: mockUsers, total: mockUsers.length };
  },
  
  // AI Engines - Tactical
  getTacticalStatus: async () => {
    await delay(MOCK_DELAY);
    return {
      modelLoaded: true,
      modelVersion: 'v2.1.0',
      averageLatencyMs: 45.2,
      totalInferences: 154320,
      inferencesPerMinute: 120,
    };
  },
  
  // AI Engines - Strategic
  getStrategicRecommendations: async () => {
    await delay(MOCK_DELAY);
    return [
      {
        recommendationId: 'rec-1',
        assetId: 'asset-1',
        assetName: 'Printer #1',
        description: 'Increase print speed by 10% during off-peak hours',
        priority: 8,
        confidence: 0.92,
        expectedImpact: { oeeImprovement: 0.05, costSavings: 1200 },
        status: 'pending',
        validUntil: new Date(Date.now() + 86400000 * 7).toISOString(),
        createdAt: new Date().toISOString(),
      },
      {
        recommendationId: 'rec-2',
        assetId: 'asset-3',
        assetName: 'Printer #3',
        description: 'Schedule preventive maintenance for next weekend',
        priority: 9,
        confidence: 0.88,
        expectedImpact: { oeeImprovement: 0.03, timeSavings: 4 },
        status: 'pending',
        validUntil: new Date(Date.now() + 86400000 * 3).toISOString(),
        createdAt: new Date().toISOString(),
      },
    ];
  },
  
  // AI Engines - MLOps
  getMLOpsStatus: async () => {
    await delay(MOCK_DELAY);
    return {
      currentModel: 'manufacturing-optimizer-v2.1.0.pt',
      lastDeploymentAt: new Date(Date.now() - 86400000 * 2).toISOString(),
      cachedModels: [
        'manufacturing-optimizer-v2.1.0.pt',
        'manufacturing-optimizer-v2.0.5.pt',
        'manufacturing-optimizer-v1.9.0.pt',
      ],
      deploymentHistory: [
        { version: 'manufacturing-optimizer-v2.1.0.pt', deployedAt: new Date(Date.now() - 86400000 * 2).toISOString() },
        { version: 'manufacturing-optimizer-v2.0.5.pt', deployedAt: new Date(Date.now() - 86400000 * 30).toISOString(), rolledBackAt: new Date(Date.now() - 86400000 * 2).toISOString() },
      ],
      pollIntervalSeconds: 300,
      lastPollAt: new Date().toISOString(),
    };
  },
  
  // AI Engines - Cloud Gateway
  getCloudGatewayStatus: async () => {
    await delay(MOCK_DELAY);
    return {
      connected: true,
      lastSyncAt: new Date().toISOString(),
      connectionUptimeSeconds: 86400 * 5,
      mTlsCertificateExpiry: new Date(Date.now() + 86400000 * 90).toISOString(),
      egressStats: {
        totalBytesSent: 157286400,
        compressionRatio: 0.85,
        averageBandwidthKbps: 256,
        queueDepth: 12,
      },
    };
  },
};
