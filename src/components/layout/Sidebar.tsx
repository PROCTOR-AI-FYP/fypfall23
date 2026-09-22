import { NavLink } from 'react-router-dom';
import { useAuth } from '@/lib/auth-context';
import { Role } from '@/lib/types';
import {
  LayoutDashboard, Users, Building2, Sliders, FileText, Shield,
  Eye, Inbox, ClipboardList, BarChart3,
  Calendar, UserCheck, History, TrendingUp,
  FolderOpen, FileQuestion,
  PanelLeftClose, PanelLeftOpen,
  Hexagon,
} from 'lucide-react';
import type { ReactNode } from 'react';

interface NavItem {
  label: string;
  path: string;
  icon: ReactNode;
  roles: Role[];
}

const navItems: NavItem[] = [
  // Admin
  { label: 'Dashboard', path: '/admin/dashboard', icon: <LayoutDashboard size={18} />, roles: [Role.Admin] },
  { label: 'User Management', path: '/admin/users', icon: <Users size={18} />, roles: [Role.Admin] },
  { label: 'Classrooms', path: '/admin/classrooms', icon: <Building2 size={18} />, roles: [Role.Admin] },
  { label: 'Thresholds', path: '/admin/thresholds', icon: <Sliders size={18} />, roles: [Role.Admin] },
  { label: 'Audit Log', path: '/admin/audit-log', icon: <FileText size={18} />, roles: [Role.Admin] },

  // HOD
  { label: 'Dashboard', path: '/hod/dashboard', icon: <LayoutDashboard size={18} />, roles: [Role.HOD] },
  { label: 'Case Management', path: '/hod/cases', icon: <Shield size={18} />, roles: [Role.HOD] },
  { label: 'Appeals', path: '/hod/appeals', icon: <FileQuestion size={18} />, roles: [Role.HOD] },

  // Teacher
  { label: 'Session Setup', path: '/teacher/session-setup', icon: <ClipboardList size={18} />, roles: [Role.Teacher] },
  { label: 'Live Monitor', path: '/teacher/live-monitor/ses-001', icon: <Eye size={18} />, roles: [Role.Teacher] },
  { label: 'Alert Inbox', path: '/teacher/alerts', icon: <Inbox size={18} />, roles: [Role.Teacher] },
  { label: 'Session Report', path: '/teacher/session-report/ses-003', icon: <BarChart3 size={18} />, roles: [Role.Teacher] },

  // Student
  { label: 'My Cases', path: '/student/cases', icon: <FolderOpen size={18} />, roles: [Role.Student] },

  // Exam Controller
  { label: 'Exam Schedule', path: '/exam-controller/schedule', icon: <Calendar size={18} />, roles: [Role.ExamController] },
  { label: 'Assignments', path: '/exam-controller/assignments', icon: <UserCheck size={18} />, roles: [Role.ExamController] },
  { label: 'Session History', path: '/exam-controller/history', icon: <History size={18} />, roles: [Role.ExamController] },
  { label: 'Reports', path: '/exam-controller/reports', icon: <TrendingUp size={18} />, roles: [Role.ExamController] },
];

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { user } = useAuth();
  if (!user) return null;

  const filtered = navItems.filter(item => item.roles.includes(user.role));

  return (
    <aside
      className={`
        h-screen flex flex-col
        bg-(--color-bg-surface) border-r border-(--color-border-default)
        transition-all duration-200
        ${collapsed ? 'w-16' : 'w-60'}
      `}
    >
      {/* Logo */}
      <div className="h-14 flex items-center px-4 border-b border-(--color-border-default) gap-3 shrink-0">
        <div className="w-8 h-8 rounded-[6px] bg-(--color-accent-primary) flex items-center justify-center text-white shrink-0">
          <Hexagon size={18} />
        </div>
        {!collapsed && (
          <span className="font-[Sora] font-bold text-[16px] text-(--color-text-primary) whitespace-nowrap">
            ProctorAI
          </span>
        )}
      </div>

      {/* Nav items */}
      <nav className="flex-1 overflow-y-auto py-3 px-2">
        <ul className="flex flex-col gap-0.5">
          {filtered.map(item => (
            <li key={item.path}>
              <NavLink
                to={item.path}
                className={({ isActive }) => `
                  flex items-center gap-3 px-3 py-2.5 rounded-[6px]
                  text-body-sm font-medium transition-colors
                  ${isActive
                    ? 'bg-(--color-accent-primary-subtle) text-(--color-accent-primary)'
                    : 'text-(--color-text-secondary) hover:bg-(--color-bg-surface-raised) hover:text-(--color-text-primary)'
                  }
                  ${collapsed ? 'justify-center' : ''}
                `}
                title={collapsed ? item.label : undefined}
              >
                <span className="shrink-0">{item.icon}</span>
                {!collapsed && <span className="truncate">{item.label}</span>}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      {/* Collapse toggle */}
      <div className="p-2 border-t border-(--color-border-default) shrink-0">
        <button
          onClick={onToggle}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-[6px] text-(--color-text-muted) hover:bg-(--color-bg-surface-raised) hover:text-(--color-text-primary) transition-colors cursor-pointer text-body-sm"
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
          {!collapsed && <span>Collapse</span>}
        </button>
      </div>
    </aside>
  );
}
