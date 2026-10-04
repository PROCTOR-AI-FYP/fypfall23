import { Bell, ChevronRight, LogOut, Menu, ArrowUpRight } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';
import { useAuth } from '@/lib/auth-context';
import { useNavigate } from 'react-router-dom';
import { ThemeToggle } from './ThemeToggle';
import { useLiveRevision } from '@/lib/live-context';
import { getNotifications } from '@/lib/api';

interface HeaderProps {
  breadcrumb: string[];
  onNotificationsClick: () => void;
  onMenuClick?: () => void;
  navigationOpen?: boolean;
}

export function Header({ breadcrumb, onNotificationsClick, onMenuClick, navigationOpen }: HeaderProps) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const liveRevision = useLiveRevision();
  const [unread,setUnread] = useState(0);
  useEffect(() => {
    if (!user) return;
    let cancelled=false;
    getNotifications(user.id).then(result=>{ if (!cancelled) setUnread(result.data.filter(value=>!value.read).length); }).catch(()=>{});
    return ()=>{cancelled=true;};
  },[user?.id,liveRevision]);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setUserMenuOpen(false);
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
    <header className="portal-header">
      <div className="portal-header-left">
        <button onClick={onMenuClick} className="mobile-menu-button" aria-label="Open navigation" aria-expanded={navigationOpen} aria-controls="workspace-navigation"><Menu size={20} /></button>
        <nav aria-label="Breadcrumb" className="portal-breadcrumb">
          {breadcrumb.map((seg, i) => <span key={i}>{i > 0 && <ChevronRight size={13} />}<span>{seg}</span></span>)}
        </nav>
      </div>
      <div className="portal-header-tools">
        <span className="header-date">{new Date().toLocaleDateString(undefined, {day:'2-digit',month:'short',year:'numeric'})}</span>
        <ThemeToggle />
        <button onClick={onNotificationsClick} className="header-icon-button" aria-label="Notifications">
          <Bell size={19} />{unread > 0 && <span className="notification-count">{unread}</span>}
        </button>
        <div ref={menuRef} className="relative">
          <button onClick={() => setUserMenuOpen(!userMenuOpen)} className="header-user-button" aria-expanded={userMenuOpen}>
            <span className="user-avatar">{user?.name.split(' ').map(part => part[0]).slice(0,2).join('')}</span>
            <span className="header-user-copy"><strong>{user?.name}</strong><span>{user?.role}</span></span>
          </button>
          {userMenuOpen && <div className="header-user-menu">
            <div><strong>{user?.name}</strong><p>{user?.email}</p></div>
            <button onClick={() => {setUserMenuOpen(false); navigate('/');}}><ArrowUpRight size={16} />About ProctorAI</button>
            <button onClick={handleLogout}><LogOut size={16} />Sign out</button>
          </div>}
        </div>
      </div>
    </header>
  );
}
