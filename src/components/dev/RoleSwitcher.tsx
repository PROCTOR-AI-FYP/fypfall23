import { useState } from 'react';
import { useAuth } from '@/lib/auth-context';
import { Role } from '@/lib/types';
import { Bug, X } from 'lucide-react';

const roles = [Role.Admin, Role.HOD, Role.Teacher, Role.ExamController, Role.Student];

export function RoleSwitcher() {
  const { user, switchRole } = useAuth();
  const [open, setOpen] = useState(false);

  if (!user) return null;

  return (
    <div className="fixed bottom-4 left-4 z-50">
      {open ? (
        <div className="bg-(--color-bg-surface-overlay) border border-(--color-border-default) rounded-[8px] shadow-[var(--shadow-overlay)] p-3 w-56">
          <div className="flex items-center justify-between mb-2">
            <span className="text-label text-(--color-warning) font-medium flex items-center gap-1">
              <Bug size={14} />
              Dev: Role Switcher
            </span>
            <button
              onClick={() => setOpen(false)}
              className="p-1 rounded text-(--color-text-muted) hover:text-(--color-text-primary) cursor-pointer"
            >
              <X size={14} />
            </button>
          </div>
          <div className="flex flex-col gap-1">
            {roles.map(role => (
              <button
                key={role}
                onClick={() => { switchRole(role); setOpen(false); }}
                className={`
                  px-3 py-1.5 text-left text-body-sm rounded-[4px] transition-colors cursor-pointer
                  ${user.role === role
                    ? 'bg-(--color-accent-primary-subtle) text-(--color-accent-primary) font-medium'
                    : 'text-(--color-text-secondary) hover:bg-(--color-bg-surface-raised)'
                  }
                `}
              >
                {role}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <button
          onClick={() => setOpen(true)}
          className="w-10 h-10 rounded-full bg-(--color-warning) text-white flex items-center justify-center shadow-lg hover:opacity-90 transition-opacity cursor-pointer"
          title="Dev: Switch Role"
        >
          <Bug size={18} />
        </button>
      )}
    </div>
  );
}
