import { FC, ReactNode } from 'react';
import { cn, STATUS_COLORS } from '../../utils';
import { AlarmSeverity, PackMLState } from '../../types';
import { Tooltip, TooltipTrigger, TooltipContent } from './Tooltip';

type BadgeVariant = AlarmSeverity | PackMLState | 'default' | 'success' | 'warning' | 'error' | 'info' | 'neutral';

interface BadgeProps {
  children: ReactNode;
  variant?: BadgeVariant;
  size?: 'sm' | 'md';
  className?: string;
  dot?: boolean;
  pulse?: boolean;
  tooltip?: string;
}

const variantMap: Record<BadgeVariant, string> = {
  // Status variants
  success: 'bg-status-running text-opsgrid-bg',
  warning: 'bg-status-warning text-opsgrid-bg',
  error: 'bg-status-alarm text-white',
  neutral: 'bg-opsgrid-text-secondary text-opsgrid-bg',

  // Include all severity and state colors from STATUS_COLORS
  ...STATUS_COLORS,
};

export const Badge: FC<BadgeProps> = ({
  children,
  variant = 'default',
  size = 'sm',
  className,
  dot = false,
  pulse = false,
  tooltip,
}) => {
  const sizeClasses = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-3 py-1 text-sm',
  };

  const badgeContent = (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 font-medium rounded-full',
        variantMap[variant] || variantMap.default,
        sizeClasses[size],
        className
      )}
    >
      {dot && (
        <span
          className={cn(
            'w-1.5 h-1.5 rounded-full bg-current',
            pulse && 'animate-pulse'
          )}
        />
      )}
      {children}
    </span>
  );

  if (tooltip) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          {badgeContent}
        </TooltipTrigger>
        <TooltipContent>{tooltip}</TooltipContent>
      </Tooltip>
    );
  }

  return badgeContent;
};
