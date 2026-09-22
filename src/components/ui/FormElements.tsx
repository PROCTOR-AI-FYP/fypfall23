import { type InputHTMLAttributes, type TextareaHTMLAttributes, type SelectHTMLAttributes, forwardRef, type ReactNode } from 'react';

// ── FormField ──────────────────────────────

interface FormFieldProps {
  label: string;
  error?: string;
  required?: boolean;
  children: ReactNode;
  htmlFor?: string;
}

export function FormField({ label, error, required, children, htmlFor }: FormFieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={htmlFor}
        className="text-label text-(--color-text-secondary)"
      >
        {label}
        {required && <span className="text-(--color-error) ml-0.5">*</span>}
      </label>
      {children}
      {error && <p className="text-label text-(--color-error)">{error}</p>}
    </div>
  );
}

// ── Input ──────────────────────────────────

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  hasError?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ hasError, className = '', ...props }, ref) => (
    <input
      ref={ref}
      className={`
        w-full px-3 py-2 text-body
        bg-(--color-bg-surface) border rounded-[6px]
        text-(--color-text-primary)
        placeholder:text-(--color-text-muted)
        focus:outline-none focus:border-(--color-border-focus) focus:ring-1 focus:ring-(--color-border-focus)
        disabled:opacity-50 disabled:cursor-not-allowed
        transition-colors
        ${hasError ? 'border-(--color-error)' : 'border-(--color-border-default)'}
        ${className}
      `}
      {...props}
    />
  )
);
Input.displayName = 'Input';

// ── Select ─────────────────────────────────

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  hasError?: boolean;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ hasError, className = '', children, ...props }, ref) => (
    <select
      ref={ref}
      className={`
        w-full px-3 py-2 text-body
        bg-(--color-bg-surface) border rounded-[6px]
        text-(--color-text-primary)
        focus:outline-none focus:border-(--color-border-focus) focus:ring-1 focus:ring-(--color-border-focus)
        disabled:opacity-50 disabled:cursor-not-allowed
        transition-colors appearance-none cursor-pointer
        ${hasError ? 'border-(--color-error)' : 'border-(--color-border-default)'}
        ${className}
      `}
      {...props}
    >
      {children}
    </select>
  )
);
Select.displayName = 'Select';

// ── TextArea ───────────────────────────────

interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  hasError?: boolean;
  maxChars?: number;
  currentLength?: number;
}

export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(
  ({ hasError, maxChars, currentLength = 0, className = '', ...props }, ref) => (
    <div className="relative">
      <textarea
        ref={ref}
        className={`
          w-full px-3 py-2 text-body
          bg-(--color-bg-surface) border rounded-[6px]
          text-(--color-text-primary)
          placeholder:text-(--color-text-muted)
          focus:outline-none focus:border-(--color-border-focus) focus:ring-1 focus:ring-(--color-border-focus)
          disabled:opacity-50 disabled:cursor-not-allowed
          transition-colors resize-y min-h-[100px]
          ${hasError ? 'border-(--color-error)' : 'border-(--color-border-default)'}
          ${className}
        `}
        {...props}
      />
      {maxChars !== undefined && (
        <span
          className={`absolute bottom-2 right-3 text-label tabular-nums ${
            currentLength > maxChars ? 'text-(--color-error)' : 'text-(--color-text-muted)'
          }`}
        >
          {currentLength}/{maxChars}
        </span>
      )}
    </div>
  )
);
TextArea.displayName = 'TextArea';
