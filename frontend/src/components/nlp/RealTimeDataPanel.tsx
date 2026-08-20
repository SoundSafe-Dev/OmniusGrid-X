import React, { useState, useEffect } from 'react';
import { ErrorState } from '../ui';
import { analysisSessionsApi } from '../../api/analysisSessions';
import { Activity, AlertTriangle, CheckSquare, FileText, RefreshCw } from 'lucide-react';
import { Button } from '../ui/Button';

interface RealTimeDataPanelProps {
  sessionId: string;
  className?: string;
}

export const RealTimeDataPanel: React.FC<RealTimeDataPanelProps> = ({
  sessionId,
  className = ''
}) => {
  const [telemetry, setTelemetry] = useState<any>(null);
  const [alarms, setAlarms] = useState<any>(null);
  const [kanban, setKanban] = useState<any>(null);
  const [registries, setRegistries] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(false);
  // Every tab's data starts as `null`, and a failed fetch left it that way — so the panel
  // rendered "No data available" for a request that never returned. The tab-level empty
  // states below ("No telemetry data", "No alarms", …) are reached only once data HAS
  // arrived, so the one gate here covers all five.
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'telemetry' | 'alarms' | 'kanban' | 'registries'>('telemetry');

  useEffect(() => {
    if (sessionId) {
      loadData();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing; adding deps changes retrigger behavior (FS-54)
  }, [sessionId, activeTab]);

  const loadData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      switch (activeTab) {
        case 'telemetry': {
          const telemetryData = await analysisSessionsApi.getSessionTelemetryContext(sessionId);
          setTelemetry(telemetryData);
          break;
        }
        case 'alarms': {
          const alarmsData = await analysisSessionsApi.getSessionAlarmsContext(sessionId);
          setAlarms(alarmsData);
          break;
        }
        case 'kanban': {
          const kanbanData = await analysisSessionsApi.getSessionKanbanContext(sessionId);
          setKanban(kanbanData);
          break;
        }
        case 'registries': {
          const registriesData = await analysisSessionsApi.getSessionRegistriesContext(sessionId);
          setRegistries(registriesData);
          break;
        }
      }
    } catch (err) {
      console.error('Error loading context data:', err);
      setError('Could not load this context.');
    } finally {
      setIsLoading(false);
    }
  };

  const tabs = [
    { id: 'telemetry' as const, label: 'Live', icon: Activity },
    { id: 'alarms' as const, label: 'Alarms', icon: AlertTriangle },
    { id: 'kanban' as const, label: 'Kanban', icon: CheckSquare },
    { id: 'registries' as const, label: 'Regs', icon: FileText },
  ];

  const renderContent = () => {
    if (isLoading) {
      return (
        <div className="flex items-center justify-center py-8">
          <RefreshCw className="w-6 h-6 animate-spin text-opsgrid-primary" />
        </div>
      );
    }

    const data = { telemetry, alarms, kanban, registries }[activeTab];

    if (error) {
      return (
        <div className="text-center py-8">
          <ErrorState
            message={error}
            onRetry={() => loadData()}
            retrying={isLoading}
          />
        </div>
      );
    }

    if (!data) {
      return (
        <div className="text-center py-8">
          <p className="text-sm text-opsgrid-text-secondary">No data available</p>
        </div>
      );
    }

    if (data.message) {
      return (
        <div className="text-center py-8">
          <p className="text-sm text-opsgrid-text-secondary">{data.message}</p>
        </div>
      );
    }

    // Render actual data based on active tab
    switch (activeTab) {
      case 'telemetry': {
        const telemetryItems = data.telemetry || [];
        if (telemetryItems.length === 0) {
          return <p className="text-sm text-opsgrid-text-secondary">No telemetry data</p>;
        }
        return (
          <div className="space-y-2">
            <p className="text-xs text-opsgrid-text-secondary">Count: {data.count || telemetryItems.length}</p>
            {telemetryItems.slice(0, 10).map((item: any, idx: number) => (
              <div key={idx} className="p-2 bg-opsgrid-bg rounded border border-opsgrid-border">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium text-opsgrid-text">{item.asset_name}</span>
                  <span className="text-xs text-opsgrid-text-secondary">{new Date(item.timestamp).toLocaleTimeString()}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-opsgrid-text">{item.metric_name}</span>
                  <span className="text-xs font-medium text-opsgrid-text">
                    {item.value} {item.unit || ''}
                  </span>
                </div>
                {item.packml_state && (
                  <span className="text-xs text-opsgrid-text-secondary mt-1">State: {item.packml_state}</span>
                )}
              </div>
            ))}
          </div>
        );

      }
      case 'alarms': {
        const alarmItems = data.alarms || [];
        if (alarmItems.length === 0) {
          return <p className="text-sm text-opsgrid-text-secondary">No alarms</p>;
        }
        return (
          <div className="space-y-2">
            <p className="text-xs text-opsgrid-text-secondary">Count: {data.count || alarmItems.length}</p>
            {alarmItems.slice(0, 10).map((item: any) => (
              <div key={item.id} className="p-2 bg-opsgrid-bg rounded border border-opsgrid-border">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium text-opsgrid-text">{item.asset_name}</span>
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    item.severity === 'critical' ? 'bg-red-100 text-red-800' :
                    item.severity === 'high' ? 'bg-orange-100 text-orange-800' :
                    item.severity === 'medium' ? 'bg-yellow-100 text-yellow-800' :
                    'bg-gray-100 text-gray-800'
                  }`}>
                    {item.severity}
                  </span>
                </div>
                <p className="text-xs text-opsgrid-text mb-1">{item.alarm_code}</p>
                {item.description && (
                  <p className="text-xs text-opsgrid-text-secondary">{item.description}</p>
                )}
                <div className="flex items-center gap-2 mt-1">
                  <span className={`text-xs ${item.is_active ? 'text-red-500' : 'text-green-500'}`}>
                    {item.is_active ? 'Active' : 'Cleared'}
                  </span>
                  {item.is_acknowledged && (
                    <span className="text-xs text-opsgrid-text-secondary">Acknowledged</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        );

      }
      case 'kanban': {
        const taskItems = data.tasks || [];
        if (taskItems.length === 0) {
          return <p className="text-sm text-opsgrid-text-secondary">No tasks</p>;
        }
        return (
          <div className="space-y-2">
            <p className="text-xs text-opsgrid-text-secondary">Count: {data.count || taskItems.length}</p>
            {taskItems.slice(0, 10).map((item: any) => (
              <div key={item.id} className="p-2 bg-opsgrid-bg rounded border border-opsgrid-border">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium text-opsgrid-text">{item.title}</span>
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    item.priority === 'critical' ? 'bg-red-100 text-red-800' :
                    item.priority === 'high' ? 'bg-orange-100 text-orange-800' :
                    item.priority === 'medium' ? 'bg-yellow-100 text-yellow-800' :
                    'bg-gray-100 text-gray-800'
                  }`}>
                    {item.priority}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs text-opsgrid-text-secondary">
                  <span>{item.status}</span>
                  {item.progress_percent !== undefined && (
                    <span>{item.progress_percent}%</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        );

      }
      case 'registries': {
        const registryItems = data.registry_items || [];
        if (registryItems.length === 0) {
          return <p className="text-sm text-opsgrid-text-secondary">No registry items</p>;
        }
        return (
          <div className="space-y-2">
            <p className="text-xs text-opsgrid-text-secondary">Count: {data.count || registryItems.length}</p>
            {registryItems.slice(0, 10).map((item: any) => (
              <div key={item.id} className="p-2 bg-opsgrid-bg rounded border border-opsgrid-border">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium text-opsgrid-text">{item.title}</span>
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    item.severity === 'critical' ? 'bg-red-100 text-red-800' :
                    item.severity === 'high' ? 'bg-orange-100 text-orange-800' :
                    item.severity === 'medium' ? 'bg-yellow-100 text-yellow-800' :
                    'bg-gray-100 text-gray-800'
                  }`}>
                    {item.severity}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs text-opsgrid-text-secondary">
                  <span>{item.status}</span>
                  {item.due_date && (
                    <span>Due: {new Date(item.due_date).toLocaleDateString()}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        );

      }
      default:
        return <p className="text-sm text-opsgrid-text-secondary">Unknown tab</p>;
    }
  };

  return (
    <div className={`flex flex-col h-full ${className}`}>
      <div className="p-4 border-b border-opsgrid-border">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-opsgrid-text">Real-Time Data</h3>
          <Button
            variant="outline"
            size="sm"
            onClick={loadData}
            disabled={isLoading}
            className="bg-white text-gray-900 border-gray-300 hover:bg-gray-100"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
        
        {/* Tabs */}
        <div className="grid grid-cols-4 gap-1 w-full">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`min-w-0 flex items-center justify-center gap-1 px-1.5 py-2 rounded-md text-[11px] transition-colors ${
                  activeTab === tab.id
                    ? 'bg-white text-gray-900 border border-gray-300'
                    : 'bg-opsgrid-bg text-opsgrid-text hover:bg-opsgrid-border'
                }`}
                title={tab.id === 'registries' ? 'Registries' : tab.label}
              >
                <Icon className="w-3 h-3 shrink-0" />
                <span className="truncate">{tab.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {renderContent()}
      </div>
    </div>
  );
};
