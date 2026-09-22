import { Bell, ChevronRight, LogOut, User } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';
import { useAuth } from '@/lib/auth-context';
import { useNavigate } from 'react-router-dom';
import { ThemeToggle } from './ThemeToggle';

interface HeaderProps {
  breadcrumb: string[];
  onNotificationsClick: () => void;
}

export function Header({ breadcrumb, onNotificationsClick }: HeaderProps) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const handleLogout = () => {
    setUserMenuOpen(false);
    logout();
    navigate('/login');
  };

  return (
    <header className="h-14 bg-(--color-bg-surface) border-b border-(--color-border-default) px-6 flex items-center justify-between shrink-0">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-body-sm">
        {breadcrumb.map((seg, i) => (
          <span key={i} className="flex items-center gap-1.5">
            {i > 0 && <ChevronRight size={14} className="text-(--color-text-muted)" />}
            <span
              className={
                i === breadcrumb.length - 1
                  ? 'text-(--color-text-primary) font-medium'
                  : 'text-(--color-text-muted)'
              }
            >
              {seg}
            </span>
          </span>
        ))}
      </nav>

      {/* Right side */}
      <div className="flex items-center gap-2">
        <ThemeToggle />

        {/* Notification bell */}
        <button
          onClick={onNotificationsClick}
          className="relative p-2 rounded-[6px] text-(--color-text-secondary) hover:bg-(--color-bg-surface-raised) hover:text-(--color-text-primary) transition-colors cursor-pointer"
          aria-label="Notifications"
        >
          <Bell size={18} />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-(--color-error) rounded-full" />
        </button>

        {/* User menu */}
        <div ref={menuRef} className="relative">
          <button
            onClick={() => setUserMenuOpen(!userMenuOpen)}
            className="flex items-center gap-2.5 px-2 py-1.5 rounded-[6px] hover:bg-(--color-bg-surface-raised) transition-colors cursor-pointer"
          >
            <div className="w-8 h-8 rounded-full bg-(--color-accent-primary-subtle) flex items-center justify-center text-(--color-accent-primary)">
              <User size={16} />
            </div>
            <div className="text-left hidden sm:block">
              <p className="text-body-sm font-medium text-(--color-text-primary) leading-tight">{user?.name}</p>
              <p className="text-label text-(--color-text-muted) leading-tight">{user?.role}</p>
            </div>
          </button>

          {userMenuOpen && (
            <div className="absolute right-0 top-full mt-1 w-52 bg-(--color-bg-surface-overlay) border border-(--color-border-default) rounded-[8px] shadow-[var(--shadow-overlay)] py-1 z-50">
              <div className="px-3 py-2 border-b border-(--color-border-default)">
                <p className="text-body-sm font-medium text-(--color-text-primary)">{user?.name}</p>
                <p className="text-label text-(--color-text-muted)">{user?.email}</p>
              </div>
              <button
                onClick={handleLogout}
                className="w-full flex items-center gap-2 px-3 py-2 text-body-sm text-(--color-error) hover:bg-(--color-error-subtle) transition-colors cursor-pointer"
              >
                <LogOut size={16} />
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
