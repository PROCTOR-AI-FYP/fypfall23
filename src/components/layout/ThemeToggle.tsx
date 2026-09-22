import { Sun, Moon, Monitor } from 'lucide-react';
import { useTheme } from '@/lib/theme-context';

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  const options = [
    { value: 'light' as const, icon: <Sun size={14} />, label: 'Light' },
    { value: 'dark' as const, icon: <Moon size={14} />, label: 'Dark' },
    { value: 'system' as const, icon: <Monitor size={14} />, label: 'System' },
  ];

  return (
    <div
      className="flex items-center bg-(--color-bg-surface-raised) rounded-[6px] p-0.5 border border-(--color-border-default)"
      role="radiogroup"
      aria-label="Theme selection"
    >
      {options.map(opt => (
        <button
          key={opt.value}
          role="radio"
          aria-checked={theme === opt.value}
          aria-label={opt.label}
          onClick={() => setTheme(opt.value)}
          className={`
            p-1.5 rounded-[4px] transition-colors cursor-pointer
            ${theme === opt.value
              ? 'bg-(--color-bg-surface) text-(--color-text-primary) shadow-[var(--shadow-surface)]'
              : 'text-(--color-text-muted) hover:text-(--color-text-secondary)'
            }
          `}
          title={opt.label}
        >
          {opt.icon}
        </button>
      ))}
    </div>
  );
}
