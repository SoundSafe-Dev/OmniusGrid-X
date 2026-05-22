import React, { useState, useEffect } from 'react';
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
  const [activeTab, setActiveTab] = useState<'telemetry' | 'alarms' | 'kanban' | 'registries'>('telemetry');

  useEffect(() => {
    if (sessionId) {
      loadData();
    }
  }, [sessionId, activeTab]);

  const loadData = async () => {
    setIsLoading(true);
    try {
      switch (activeTab) {
        case 'telemetry':
          const telemetryData = await analysisSessionsApi.getSessionTelemetryContext(sessionId);
          setTelemetry(telemetryData);
          break;
        case 'alarms':
          const alarmsData = await analysisSessionsApi.getSessionAlarmsContext(sessionId);
          setAlarms(alarmsData);
          break;
        case 'kanban':
          const kanbanData = await analysisSessionsApi.getSessionKanbanContext(sessionId);
          setKanban(kanbanData);
          break;
        case 'registries':
          const registriesData = await analysisSessionsApi.getSessionRegistriesContext(sessionId);
          setRegistries(registriesData);
          break;
      }
    } catch (error) {
      console.error('Error loading context data:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const tabs = [
    { id: 'telemetry' as const, label: 'Telemetry', icon: Activity },
    { id: 'alarms' as const, label: 'Alarms', icon: AlertTriangle },
    { id: 'kanban' as const, label: 'Kanban', icon: CheckSquare },
    { id: 'registries' as const, label: 'Registries', icon: FileText },
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

    if (!data || data.message) {
      return (
        <div className="text-center py-8">
          <p className="text-sm text-opsgrid-text-secondary">
            {data?.message || 'No data available'}
          </p>
          <p className="text-xs text-opsgrid-text-secondary mt-2">
            Integration to be implemented
          </p>
        </div>
      );
    }

    // Render actual data when integration is complete
    return (
      <div className="space-y-2">
        <p className="text-xs text-opsgrid-text-secondary">
          {activeTab.charAt(0).toUpperCase() + activeTab.slice(1)} data will be displayed here
        </p>
      </div>
    );
  };

  return (
    <div className={`flex flex-col h-full ${className}`}>
      <div className="p-4 border-b border-opsgrid-border">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-opsgrid-text">Real-Time Data</h3>
          <Button variant="outline" size="sm" onClick={loadData} disabled={isLoading}>
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
        
        {/* Tabs */}
        <div className="flex gap-1">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-3 py-2 rounded-md text-xs transition-colors ${
                  activeTab === tab.id
                    ? 'bg-opsgrid-primary text-white'
                    : 'bg-opsgrid-bg text-opsgrid-text hover:bg-opsgrid-border'
                }`}
              >
                <Icon className="w-3 h-3" />
                {tab.label}
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
