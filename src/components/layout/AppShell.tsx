import { useState, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { NotificationPanel } from './NotificationPanel';
import { WorkspaceIntro } from './WorkspaceIntro';

export function AppShell() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    if (!mobileOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const navigation = document.getElementById('workspace-navigation');
    const focusables = () => Array.from(navigation?.querySelectorAll<HTMLElement>('a, button') ?? []).filter(element => element.getClientRects().length > 0);
    const frame = requestAnimationFrame(() => focusables()[0]?.focus());
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobileOpen(false);
      if (event.key !== 'Tab') return;
      const elements = focusables();
      const target = event.shiftKey ? elements.at(-1) : elements[0];
      if ((event.shiftKey && document.activeElement === elements[0]) || (!event.shiftKey && document.activeElement === elements.at(-1))) {
        event.preventDefault(); target?.focus();
      }
    };
    document.addEventListener('keydown', handleKey);
    return () => { cancelAnimationFrame(frame); document.removeEventListener('keydown', handleKey); previous?.focus(); };
  }, [mobileOpen]);

  // Derive breadcrumb from path
  const breadcrumb = location.pathname
    .split('/')
    .filter(Boolean)
    .map(seg => /^[0-9a-f-]{32,}$/i.test(seg) ? 'Details' : seg.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase()));

  return (
    <div className={`portal-shell ${sidebarCollapsed ? 'sidebar-is-collapsed' : ''} ${mobileOpen ? 'mobile-nav-open' : ''}`}>
      <a href="#workspace-main" className="skip-link">Skip to content</a>
      {mobileOpen && <button className="mobile-nav-scrim" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
      <Sidebar
        collapsed={sidebarCollapsed && !mobileOpen}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
        onNavigate={() => setMobileOpen(false)}
        mobileOpen={mobileOpen}
      />

      <div className="portal-frame">
        <Header
          breadcrumb={breadcrumb}
          onNotificationsClick={() => setNotificationsOpen(!notificationsOpen)}
          onMenuClick={() => setMobileOpen(!mobileOpen)}
          navigationOpen={mobileOpen}
        />

        <main id="workspace-main" className="portal-main" tabIndex={-1}>
          <div className="portal-content" key={location.pathname}>
            <WorkspaceIntro />
            <div className="portal-page"><Outlet /></div>
            <footer className="workspace-footer"><span>ProctorAI · Academic integrity, thoughtfully.</span><span>Observe. Review. Resolve.</span></footer>
          </div>
        </main>
      </div>

      <NotificationPanel
        isOpen={notificationsOpen}
        onClose={() => setNotificationsOpen(false)}
      />
    </div>
  );
}
