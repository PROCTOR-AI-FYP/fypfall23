import { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { NotificationPanel } from './NotificationPanel';
import { RoleSwitcher } from '../dev/RoleSwitcher';

export function AppShell() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const location = useLocation();

  // Derive breadcrumb from path
  const breadcrumb = location.pathname
    .split('/')
    .filter(Boolean)
    .map(seg => seg.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase()));

  return (
    <div className="flex h-screen overflow-hidden bg-(--color-bg-primary)">
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div className="flex-1 flex flex-col overflow-hidden">
        <Header
          breadcrumb={breadcrumb}
          onNotificationsClick={() => setNotificationsOpen(!notificationsOpen)}
        />

        <main className="flex-1 overflow-auto p-6">
          <div className="max-w-[1280px] mx-auto">
            <Outlet />
          </div>
        </main>
      </div>

      <NotificationPanel
        isOpen={notificationsOpen}
        onClose={() => setNotificationsOpen(false)}
      />

      {/* Dev-only role switcher */}
      <RoleSwitcher />
    </div>
  );
}
