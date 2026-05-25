import { FC, InputHTMLAttributes, forwardRef } from 'react';
import { cn } from '../../utils';
import { Tooltip, TooltipTrigger, TooltipContent } from './Tooltip';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
  tooltip?: string;
}

export const Input: FC<InputProps> = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, helperText, className, tooltip, ...props }, ref) => {
    const inputElement = (
      <input
        ref={ref}
        className={cn(
          'w-full px-3 py-2 bg-opsgrid-bg border border-opsgrid-border rounded-lg',
          'text-opsgrid-text placeholder:text-opsgrid-text-secondary',
          'focus:outline-none focus:ring-2 focus:ring-opsgrid-primary focus:border-transparent',
          'disabled:opacity-50 disabled:cursor-not-allowed',
          error && 'border-status-alarm focus:ring-status-alarm',
          className
        )}
        {...props}
      />
    );

    return (
      <div className="w-full">
        {label && (
          <label className="block text-sm font-medium text-opsgrid-text mb-1">
            {label}
          </label>
        )}
        {tooltip ? (
          <Tooltip>
            <TooltipTrigger asChild>
              {inputElement}
            </TooltipTrigger>
            <TooltipContent>{tooltip}</TooltipContent>
          </Tooltip>
        ) : (
          inputElement
        )}
        {error && <p className="mt-1 text-sm text-status-alarm">{error}</p>}
        {helperText && !error && (
          <p className="mt-1 text-sm text-opsgrid-text-secondary">{helperText}</p>
        )}
      </div>
    );
  }
);

Input.displayName = 'Input';
