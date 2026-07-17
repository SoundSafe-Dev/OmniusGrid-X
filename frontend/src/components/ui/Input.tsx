import { FC, InputHTMLAttributes, forwardRef, useId } from 'react';
import { cn } from '../../utils';
import { Tooltip, TooltipTrigger, TooltipContent } from './Tooltip';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
  tooltip?: string;
}

export const Input: FC<InputProps> = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, helperText, className, tooltip, id, ...props }, ref) => {
    // Associate label/description with the control for screen readers (task 6).
    const autoId = useId();
    const inputId = id ?? autoId;
    const errorId = `${inputId}-error`;
    const helperId = `${inputId}-helper`;
    const describedBy = error ? errorId : helperText ? helperId : undefined;

    const inputElement = (
      <input
        ref={ref}
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
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
          <label htmlFor={inputId} className="block text-sm font-medium text-opsgrid-text mb-1">
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
        {error && <p id={errorId} role="alert" className="mt-1 text-sm text-status-alarm">{error}</p>}
        {helperText && !error && (
          <p id={helperId} className="mt-1 text-sm text-opsgrid-text-secondary">{helperText}</p>
        )}
      </div>
    );
  }
);

Input.displayName = 'Input';
