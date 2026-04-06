import { FC } from 'react';
import { Badge } from '../ui';
import { AlarmSeverity } from '../../types';

interface SeverityBadgeProps {
  severity: AlarmSeverity;
  size?: 'sm' | 'md';
  showDot?: boolean;
}

export const SeverityBadge: FC<SeverityBadgeProps> = ({
  severity,
  size = 'sm',
  showDot = true,
}) => {
  return (
    <Badge variant={severity} size={size} dot={showDot} pulse={severity === 'critical'}>
      {severity.charAt(0).toUpperCase() + severity.slice(1)}
    </Badge>
  );
};
