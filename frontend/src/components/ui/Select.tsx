import { FC, SelectHTMLAttributes, forwardRef } from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '../../utils';

interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  helperText?: string;
  options: SelectOption[];
  placeholder?: string;
}

export const Select: FC<SelectProps> = forwardRef<HTMLSelectElement, SelectProps>(
  (
    { label, error, helperText, options, placeholder, className, ...props },
    ref
  ) => {
    return (
      <div className="w-full">
        {label && (
          <label className="block text-sm font-medium text-opsgrid-text mb-1">
            {label}
          </label>
        )}
        <div className="relative">
          <select
            ref={ref}
            className={cn(
              'w-full px-3 py-2 pr-10 bg-opsgrid-bg border border-opsgrid-border rounded-lg',
              'text-opsgrid-text appearance-none',
              'focus:outline-none focus:ring-2 focus:ring-opsgrid-primary focus:border-transparent',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              error && 'border-status-alarm focus:ring-status-alarm',
              className
            )}
            {...props}
          >
            {placeholder && (
              <option value="" disabled>
                {placeholder}
              </option>
            )}
            {options.map((option) => (
              <option
                key={option.value}
                value={option.value}
                disabled={option.disabled}
              >
                {option.label}
              </option>
            ))}
          </select>
          <ChevronDown
            className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-opsgrid-text-secondary pointer-events-none"
          />
        </div>
        {error && <p className="mt-1 text-sm text-status-alarm">{error}</p>}
        {helperText && !error && (
          <p className="mt-1 text-sm text-opsgrid-text-secondary">{helperText}</p>
        )}
      </div>
    );
  }
);

Select.displayName = 'Select';
