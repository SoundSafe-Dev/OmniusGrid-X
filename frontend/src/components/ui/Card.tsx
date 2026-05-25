import { forwardRef, ReactNode, HTMLAttributes } from 'react';
import { cn } from '../../utils';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  title?: string;
  subtitle?: string;
  action?: ReactNode;
  noPadding?: boolean;
  hover?: boolean;
}

export const Card = forwardRef<HTMLDivElement, CardProps>(({
  children,
  title,
  subtitle,
  action,
  className,
  noPadding = false,
  hover = false,
  ...props
}, ref) => {
  return (
    <div
      ref={ref}
      className={cn(
        'bg-opsgrid-panel border border-opsgrid-border rounded-lg overflow-hidden',
        hover && 'hover:border-opsgrid-border-emphasis transition-colors cursor-pointer',
        className
      )}
      {...props}
    >
      {(title || subtitle || action) && (
        <div className="px-4 py-3 border-b border-opsgrid-border flex items-center justify-between">
          <div>
            {title && <h3 className="text-lg font-semibold text-opsgrid-text">{title}</h3>}
            {subtitle && (
              <p className="text-sm text-opsgrid-text-secondary">{subtitle}</p>
            )}
          </div>
          {action && <div>{action}</div>}
        </div>
      )}
      <div className={cn(!noPadding && 'p-4')}>{children}</div>
    </div>
  );
});

Card.displayName = 'Card';
