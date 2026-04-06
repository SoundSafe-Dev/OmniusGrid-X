import { FC } from 'react';

interface StatusIndicatorProps {
  status: 'online' | 'offline' | 'warning' | 'error' | 'maintenance';
  size?: 'sm' | 'md' | 'lg';
  showLabel?: boolean;
  label?: string;
  pulse?: boolean;
}

const statusConfig = {
  online: { color: 'bg-status-running', label: 'Online' },
  offline: { color: 'bg-status-offline', label: 'Offline' },
  warning: { color: 'bg-status-warning', label: 'Warning' },
  error: { color: 'bg-status-alarm', label: 'Error' },
  maintenance: { color: 'bg-status-maintenance', label: 'Maintenance' },
};

export const StatusIndicator: FC<StatusIndicatorProps> = ({
  status,
  size = 'md',
  showLabel = true,
  label,
  pulse = true,
}) => {
  const sizeClasses = {
    sm: 'w-2 h-2',
    md: 'w-2.5 h-2.5',
    lg: 'w-3 h-3',
  };

  const config = statusConfig[status];
  const displayLabel = label || config.label;

  return (
    <div className="flex items-center gap-2">
      <span
        className={`${sizeClasses[size]} rounded-full ${config.color} ${
          pulse && status === 'online' ? 'animate-pulse' : ''
        }`}
      />
      {showLabel && (
        <span className="text-sm text-opsgrid-text-secondary">{displayLabel}</span>
      )}
    </div>
  );
};

interface ConnectionStatusProps {
  connected: boolean;
  className?: string;
}

export const ConnectionStatus: FC<ConnectionStatusProps> = ({
  connected,
  className,
}) => {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <span
        className={`w-2 h-2 rounded-full ${
          connected ? 'bg-status-running animate-pulse' : 'bg-status-offline'
        }`}
      />
      <span className="text-sm text-opsgrid-text-secondary">
        {connected ? 'Live' : 'Disconnected'}
      </span>
    </div>
  );
};
