import { FC } from 'react';
import { Badge } from '../ui';
import { PackMLState } from '../../types';
import { STATUS_TEXT_COLORS } from '../../utils';

interface PackMLBadgeProps {
  state: PackMLState;
  size?: 'sm' | 'md';
  showDot?: boolean;
  pulse?: boolean;
}

export const PackMLBadge: FC<PackMLBadgeProps> = ({
  state,
  size = 'sm',
  showDot = true,
  pulse = false,
}) => {
  return (
    <Badge variant={state} size={size} dot={showDot} pulse={pulse && state === 'Execute'}>
      {state}
    </Badge>
  );
};

interface PackMLIndicatorProps {
  state: PackMLState;
  size?: 'sm' | 'md' | 'lg';
  showLabel?: boolean;
}

export const PackMLIndicator: FC<PackMLIndicatorProps> = ({
  state,
  size = 'md',
  showLabel = false,
}) => {
  const sizeClasses = {
    sm: 'w-2 h-2',
    md: 'w-3 h-3',
    lg: 'w-4 h-4',
  };

  const textColorClass = STATUS_TEXT_COLORS[state] || STATUS_TEXT_COLORS.default;

  return (
    <div className="flex items-center gap-2">
      <span
        className={`${sizeClasses[size]} rounded-full ${textColorClass.replace(
          'text-',
          'bg-'
        )} ${state === 'Execute' ? 'animate-pulse' : ''}`}
      />
      {showLabel && <span className={`text-sm ${textColorClass}`}>{state}</span>}
    </div>
  );
};
