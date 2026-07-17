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
  // FS-130: full lifecycle state so the indicator can show "Reconnecting…"
  // during the backoff window instead of a flat Disconnected. Optional to keep
  // existing <ConnectionStatus connected={...} /> call sites working.
  state?: 'connecting' | 'connected' | 'disconnected' | 'reconnecting';
  pollingFallback?: boolean;
  className?: string;
}

export const ConnectionStatus: FC<ConnectionStatusProps> = ({
  connected,
  state,
  pollingFallback = false,
  className,
}) => {
  const effectiveState = state ?? (connected ? 'connected' : 'disconnected');

  let dotClass = 'bg-status-offline';
  let label = 'Disconnected';
  if (effectiveState === 'connected') {
    dotClass = 'bg-status-running animate-pulse';
    label = 'Live';
  } else if (effectiveState === 'connecting' || effectiveState === 'reconnecting') {
    dotClass = 'bg-status-warning animate-pulse';
    label = effectiveState === 'connecting' ? 'Connecting…' : 'Reconnecting…';
  } else if (pollingFallback) {
    // Socket gave up for now; REST polling keeps the data fresh in the background.
    dotClass = 'bg-status-warning';
    label = 'Polling';
  }

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <span className={`w-2 h-2 rounded-full ${dotClass}`} />
      <span className="text-sm text-opsgrid-text-secondary">{label}</span>
    </div>
  );
};
