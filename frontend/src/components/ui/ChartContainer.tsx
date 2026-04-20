import { FC, ReactNode } from 'react';
import { cn } from '../../utils';

interface ChartContainerProps {
  children: ReactNode;
  title?: string;
  subtitle?: string | ReactNode;
  className?: string;
  height?: number;
  loading?: boolean;
  error?: string | null;
}

export const ChartContainer: FC<ChartContainerProps> = ({
  children,
  title,
  subtitle,
  className,
  height = 300,
  loading = false,
  error = null,
}) => {
  return (
    <div
      className={cn(
        'bg-opsgrid-panel border border-opsgrid-border rounded-lg overflow-hidden',
        className
      )}
    >
      {(title || subtitle) && (
        <div className="px-4 py-3 border-b border-opsgrid-border">
          {title && (
            <h3 className="text-lg font-semibold text-opsgrid-text">{title}</h3>
          )}
          {subtitle && (
            <div className="text-sm text-opsgrid-text-secondary">{subtitle}</div>
          )}
        </div>
      )}
      <div className="p-4" style={{ height }}>
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <div className="animate-pulse flex space-x-2">
              <div className="w-3 h-3 bg-opsgrid-primary rounded-full animate-bounce" />
              <div className="w-3 h-3 bg-opsgrid-primary rounded-full animate-bounce delay-100" />
              <div className="w-3 h-3 bg-opsgrid-primary rounded-full animate-bounce delay-200" />
            </div>
          </div>
        ) : error ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-status-alarm">{error}</p>
          </div>
        ) : (
          children
        )}
      </div>
    </div>
  );
};
