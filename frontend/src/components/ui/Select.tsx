import { FC, SelectHTMLAttributes, forwardRef, useId } from 'react';
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
    { label, error, helperText, options, placeholder, className, id, ...props },
    ref
  ) => {
    // FS-550. Associate the label and the messages with the control, exactly as
    // `Input.tsx:15-19,42` has done since task 6.
    //
    // WHAT WAS WRONG. The `<label>` had no `htmlFor` and the `<select>` had no `id`, so
    // this rendered an **unlabelled combobox** — a screen reader announces "combo box" and
    // nothing else, app-wide, on every filter and every form that uses it. The error text
    // had no `role="alert"`, no `aria-describedby` and no `aria-invalid`, so a validation
    // failure was visible only to someone looking at the colour.
    //
    // Its sibling did all of this correctly one file away. That is what makes it a defect
    // rather than an omission: the pattern was established, applied to `Input`, and not
    // carried across — and `Select` reported **100% line coverage** the whole time, because
    // `a11y.test.tsx` renders `Button` and `Input` and never this.
    const autoId = useId();
    const selectId = id ?? autoId;
    const errorId = `${selectId}-error`;
    const helperId = `${selectId}-helper`;
    const describedBy = error ? errorId : helperText ? helperId : undefined;

    return (
      <div className="w-full">
        {label && (
          <label htmlFor={selectId} className="block text-sm font-medium text-opsgrid-text mb-1">
            {label}
          </label>
        )}
        <div className="relative">
          <select
            ref={ref}
            id={selectId}
            aria-invalid={error ? true : undefined}
            aria-describedby={describedBy}
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
        {error && (
          <p id={errorId} role="alert" className="mt-1 text-sm text-status-alarm">
            {error}
          </p>
        )}
        {helperText && !error && (
          <p id={helperId} className="mt-1 text-sm text-opsgrid-text-secondary">
            {helperText}
          </p>
        )}
      </div>
    );
  }
);

Select.displayName = 'Select';
