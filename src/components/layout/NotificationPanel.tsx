import { useEffect, useState } from 'react';
import { X, Bell, CheckCheck } from 'lucide-react';
import { useAuth } from '@/lib/auth-context';
import * as api from '@/lib/api';
import type { Notification } from '@/lib/types';

interface NotificationPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export function NotificationPanel({ isOpen, onClose }: NotificationPanelProps) {
  const { user } = useAuth();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isOpen && user) {
      setLoading(true);
      api.getNotifications(user.id).then(res => {
        setNotifications(res.data);
        setLoading(false);
      }).catch(() => setLoading(false));
    }
  }, [isOpen, user]);

  const handleMarkRead = async (id: string) => {
    await api.markNotificationRead(id);
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));
  };

  const handleMarkAllRead = async () => {
    if (!user) return;
    await api.markAllNotificationsRead(user.id);
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
  };

  const unreadCount = notifications.filter(n => !n.read).length;

  const typeColors: Record<string, string> = {
    alert: 'var(--color-error)',
    case_update: 'var(--color-accent-primary)',
    penalty: 'var(--color-warning)',
    appeal: 'var(--color-behavior-gaze)',
    system: 'var(--color-text-muted)',
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-40" onClick={onClose} />

      {/* Panel */}
      <div className="fixed right-0 top-0 h-full w-96 max-w-[calc(100vw-16px)] bg-(--color-bg-surface) border-l border-(--color-border-default) shadow-[var(--shadow-overlay)] z-50 flex flex-col">
        {/* Header */}
        <div className="h-14 px-4 flex items-center justify-between border-b border-(--color-border-default) shrink-0">
          <div className="flex items-center gap-2">
            <Bell size={18} className="text-(--color-text-secondary)" />
            <h2 className="text-heading text-(--color-text-primary)">Notifications</h2>
            {unreadCount > 0 && (
              <span className="px-1.5 py-0.5 rounded-[2px] bg-(--color-accent-primary) text-white text-label font-medium">
                {unreadCount}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {unreadCount > 0 && (
              <button
                onClick={handleMarkAllRead}
                className="p-1.5 rounded-[6px] text-(--color-text-muted) hover:text-(--color-accent-primary) hover:bg-(--color-accent-primary-subtle) transition-colors cursor-pointer"
                title="Mark all as read"
              >
                <CheckCheck size={16} />
              </button>
            )}
            <button
              onClick={onClose}
              className="p-1.5 rounded-[6px] text-(--color-text-muted) hover:text-(--color-text-primary) hover:bg-(--color-bg-surface-raised) transition-colors cursor-pointer"
              aria-label="Close notifications"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="h-6 w-6 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin" />
            </div>
          ) : notifications.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center px-4">
              <Bell size={24} className="text-(--color-text-muted) mb-2" />
              <p className="text-body-sm text-(--color-text-muted)">No notifications yet</p>
            </div>
          ) : (
            <ul>
              {notifications.map(n => (
                <li
                  key={n.id}
                  onClick={() => !n.read && handleMarkRead(n.id)}
                  className={`
                    px-4 py-3 border-b border-(--color-border-default) cursor-pointer
                    hover:bg-(--color-bg-surface-raised) transition-colors
                    ${!n.read ? 'bg-(--color-accent-primary-subtle)/30' : ''}
                  `}
                >
                  <div className="flex items-start gap-3">
                    <div
                      className="w-2 h-2 rounded-full mt-1.5 shrink-0"
                      style={{ backgroundColor: n.read ? 'transparent' : typeColors[n.type] || typeColors.system }}
                    />
                    <div className="flex-1 min-w-0">
                      <p className="text-body-sm font-medium text-(--color-text-primary) leading-tight">{n.title}</p>
                      <p className="text-body-sm text-(--color-text-secondary) mt-0.5 line-clamp-2">{n.message}</p>
                      <p className="text-label text-(--color-text-muted) mt-1">
                        {new Date(n.createdAt).toLocaleString(undefined, {
                          month: 'short',
                          day: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </p>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </>
  );
}
