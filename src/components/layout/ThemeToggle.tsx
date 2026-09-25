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
      className="flex items-center gap-1.5"
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
            p-2 rounded-[8px] transition-all cursor-pointer border
            ${theme === opt.value
              ? 'bg-(--color-bg-surface) text-(--color-text-primary) border-(--color-border-default) shadow-[var(--shadow-surface)] scale-105'
              : 'bg-(--color-bg-surface-raised) text-(--color-text-muted) border-transparent hover:text-(--color-text-secondary) hover:bg-(--color-bg-surface-overlay)'
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
