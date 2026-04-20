import { FC, useState, useCallback } from 'react';
import { Send, AlertTriangle, Pause, Play, Thermometer, Gauge } from 'lucide-react';
import { useMutation, useQueryClient } from 'react-query';
import { api } from '../../api';
import { Button, Card, Badge, Input } from '../ui';

interface CommandPanelProps {
  assetId: string;
  assetName: string;
  currentState?: string;
}

type CommandAction = 'pause_job' | 'resume_job' | 'set_speed' | 'set_temperature' | 'emergency_stop';

interface CommandOption {
  action: CommandAction;
  label: string;
  icon: React.ReactNode;
  description: string;
  variant: 'primary' | 'danger' | 'outline';
  requiresParam: boolean;
  paramLabel?: string;
  paramPlaceholder?: string;
  paramType?: 'number' | 'text';
  paramMin?: number;
  paramMax?: number;
}

const COMMAND_OPTIONS: CommandOption[] = [
  {
    action: 'pause_job',
    label: 'Pause Job',
    icon: <Pause className="w-4 h-4" />,
    description: 'Pause current printing/processing job',
    variant: 'danger',
    requiresParam: false,
  },
  {
    action: 'resume_job',
    label: 'Resume Job',
    icon: <Play className="w-4 h-4" />,
    description: 'Resume paused job',
    variant: 'primary',
    requiresParam: false,
  },
  {
    action: 'set_speed',
    label: 'Set Speed',
    icon: <Gauge className="w-4 h-4" />,
    description: 'Adjust print/processing speed',
    variant: 'primary',
    requiresParam: true,
    paramLabel: 'Speed %',
    paramPlaceholder: '50-150',
    paramType: 'number',
    paramMin: 10,
    paramMax: 200,
  },
  {
    action: 'set_temperature',
    label: 'Set Temperature',
    icon: <Thermometer className="w-4 h-4" />,
    description: 'Adjust nozzle/bed temperature',
    variant: 'primary',
    requiresParam: true,
    paramLabel: 'Temperature °C',
    paramPlaceholder: 'e.g., 210',
    paramType: 'number',
    paramMin: 0,
    paramMax: 400,
  },
];

export const CommandPanel: FC<CommandPanelProps> = ({
  assetId,
  assetName,
  currentState,
}) => {
  const [selectedCommand, setSelectedCommand] = useState<CommandOption | null>(null);
  const [paramValue, setParamValue] = useState<string>('');
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const queryClient = useQueryClient();

  const submitCommand = useMutation({
    mutationFn: async (data: {
      action: CommandAction;
      parameters: Record<string, any>;
    }) => {
      const response = await api.post('/commands/submit', {
        asset_id: assetId,
        command_type: 'operator',
        action_id: data.action,
        parameters: data.parameters,
      });
      return response.data;
    },
    onSuccess: () => {
      setFeedback({ type: 'success', message: 'Command submitted successfully' });
      setSelectedCommand(null);
      setParamValue('');
      queryClient.invalidateQueries({ queryKey: ['commands', assetId] });
      setTimeout(() => setFeedback(null), 3000);
    },
    onError: (error: any) => {
      setFeedback({
        type: 'error',
        message: error.response?.data?.detail || 'Failed to submit command',
      });
      setTimeout(() => setFeedback(null), 5000);
    },
  });

  const emergencyStop = useMutation({
    mutationFn: async () => {
      const response = await api.post(`/commands/asset/${assetId}/emergency-stop`);
      return response.data;
    },
    onSuccess: () => {
      setFeedback({ type: 'success', message: 'EMERGENCY STOP initiated' });
      setTimeout(() => setFeedback(null), 5000);
    },
    onError: (error: any) => {
      setFeedback({
        type: 'error',
        message: error.response?.data?.detail || 'Emergency stop failed',
      });
    },
  });

  const handleCommandSubmit = useCallback(() => {
    if (!selectedCommand) return;

    const parameters: Record<string, any> = {};
    
    if (selectedCommand.requiresParam) {
      if (!paramValue) {
        setFeedback({ type: 'error', message: `Please enter ${selectedCommand.paramLabel}` });
        return;
      }
      
      const numValue = parseFloat(paramValue);
      if (isNaN(numValue)) {
        setFeedback({ type: 'error', message: 'Please enter a valid number' });
        return;
      }
      
      if (selectedCommand.paramMin !== undefined && numValue < selectedCommand.paramMin) {
        setFeedback({ type: 'error', message: `Value must be at least ${selectedCommand.paramMin}` });
        return;
      }
      
      if (selectedCommand.paramMax !== undefined && numValue > selectedCommand.paramMax) {
        setFeedback({ type: 'error', message: `Value must be at most ${selectedCommand.paramMax}` });
        return;
      }
      
      if (selectedCommand.action === 'set_speed') {
        parameters.speed_percent = numValue;
      } else if (selectedCommand.action === 'set_temperature') {
        parameters.target_temp = numValue;
        parameters.component = 'nozzle'; // Could be made selectable
      }
    }

    submitCommand.mutate({ action: selectedCommand.action, parameters });
  }, [selectedCommand, paramValue, submitCommand]);

  return (
    <Card className="w-full">
      <div className="p-4">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold text-opsgrid-text">Command Control</h3>
            <p className="text-sm text-opsgrid-text-secondary">{assetName}</p>
          </div>
          {currentState && (
            <Badge variant="neutral">State: {currentState}</Badge>
          )}
        </div>

        {/* Emergency Stop */}
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-red-500" />
              <span className="text-sm font-medium text-red-500">Emergency Stop</span>
            </div>
            <Button
              variant="danger"
              size="sm"
              onClick={() => emergencyStop.mutate()}
              loading={emergencyStop.isLoading}
            >
              STOP NOW
            </Button>
          </div>
          <p className="text-xs text-opsgrid-text-secondary mt-1">
            Immediately halts all operations. Use with caution.
          </p>
        </div>

        {/* Command Selection */}
        <div className="grid grid-cols-2 gap-2 mb-4">
          {COMMAND_OPTIONS.map((cmd) => (
            <button
              key={cmd.action}
              onClick={() => {
                setSelectedCommand(cmd);
                setParamValue('');
              }}
              className={`
                p-3 rounded-lg border text-left transition-all
                ${selectedCommand?.action === cmd.action
                  ? 'border-opsgrid-primary bg-opsgrid-primary/10'
                  : 'border-opsgrid-border hover:border-opsgrid-primary/50'
                }
              `}
            >
              <div className="flex items-center gap-2 mb-1">
                {cmd.icon}
                <span className="font-medium text-sm text-opsgrid-text">{cmd.label}</span>
              </div>
              <p className="text-xs text-opsgrid-text-secondary">{cmd.description}</p>
            </button>
          ))}
        </div>

        {/* Parameter Input */}
        {selectedCommand?.requiresParam && (
          <div className="mb-4 p-3 bg-opsgrid-bg rounded-lg">
            <label className="block text-sm font-medium text-opsgrid-text mb-2">
              {selectedCommand.paramLabel}
            </label>
            <Input
              type={selectedCommand.paramType}
              value={paramValue}
              onChange={(e) => setParamValue(e.target.value)}
              placeholder={selectedCommand.paramPlaceholder}
              min={selectedCommand.paramMin}
              max={selectedCommand.paramMax}
              className="w-full"
            />
            {(selectedCommand.paramMin !== undefined || selectedCommand.paramMax !== undefined) && (
              <p className="text-xs text-opsgrid-text-secondary mt-1">
                Range: {selectedCommand.paramMin ?? 'N/A'} - {selectedCommand.paramMax ?? 'N/A'}
              </p>
            )}
          </div>
        )}

        {/* Submit Button */}
        {selectedCommand && (
          <div className="flex gap-2">
            <Button
              variant={selectedCommand.variant}
              className="flex-1"
              onClick={handleCommandSubmit}
              loading={submitCommand.isLoading}
            >
              {!submitCommand.isLoading && <Send className="w-4 h-4 mr-2" />}
              Send Command
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setSelectedCommand(null);
                setParamValue('');
              }}
            >
              Cancel
            </Button>
          </div>
        )}

        {/* Feedback */}
        {feedback && (
          <div
            className={`mt-4 p-3 rounded-lg ${
              feedback.type === 'success'
                ? 'bg-green-500/10 border border-green-500/30 text-green-500'
                : 'bg-red-500/10 border border-red-500/30 text-red-500'
            }`}
          >
            <p className="text-sm">{feedback.message}</p>
          </div>
        )}

        {/* Command History Link */}
        <div className="mt-4 pt-4 border-t border-opsgrid-border">
          <p className="text-xs text-opsgrid-text-secondary">
            Commands are logged and tracked. View command history in the asset details page.
          </p>
        </div>
      </div>
    </Card>
  );
};

export default CommandPanel;
