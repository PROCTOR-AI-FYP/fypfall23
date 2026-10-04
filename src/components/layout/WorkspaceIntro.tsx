import { Link, useLocation } from 'react-router-dom';
import { ArrowUpRight, Layers3, ShieldCheck, CalendarDays, GraduationCap, ScanLine } from 'lucide-react';
import { useAuth } from '@/lib/auth-context';
import { Role } from '@/lib/types';
import { IntegrityScene } from '@/components/visual/IntegrityScene';
import StarBorder from '@/components/reactbits/StarBorder';

const workspaces = {
  [Role.Admin]: { label: 'Administration', title: 'Everything in perspective.', description: 'Manage your people, spaces and policies. Keep your institution moving with confidence.', action: 'Manage people', href: '/admin/users', icon: Layers3 },
  [Role.HOD]: { label: 'Academic review', title: 'Clarity before every decision.', description: 'Review the evidence, follow every case and give each student a fair hearing.', action: 'Review cases', href: '/hod/cases', icon: ShieldCheck },
  [Role.Teacher]: { label: 'Invigilation', title: 'Be present. Stay in control.', description: 'Prepare your exam, observe the room and bring the right evidence into focus.', action: 'Your sessions', href: '/teacher/live-monitor', icon: ScanLine },
  [Role.ExamController]: { label: 'Examination office', title: 'An organised exam starts here.', description: 'Bring schedules, classrooms and invigilators together in one considered workspace.', action: 'View assignments', href: '/exam-controller/assignments', icon: CalendarDays },
  [Role.Student]: { label: 'Student portal', title: 'Your voice matters.', description: 'Understand your case, follow its progress and make your perspective heard.', action: 'Your cases', href: '/student/cases', icon: GraduationCap },
};

export function WorkspaceIntro() {
  const { user } = useAuth();
  const { pathname } = useLocation();
  if (!user) return null;
  const workspace = workspaces[user.role];
  const isOverview = ['/admin/dashboard', '/hod/dashboard', '/teacher/session-setup', '/student/cases', '/exam-controller/schedule'].includes(pathname);
  const Icon = workspace.icon;
  if (!isOverview) return <div className="workspace-context"><span><Icon size={14} />{workspace.label}</span><span className="workspace-context-rule" /><span>ProctorAI workspace</span></div>;
  return <section className="workspace-intro">
    <div className="workspace-intro-copy">
      <span className="workspace-eyebrow"><Icon size={14} />{workspace.label} workspace</span>
      <h2>{workspace.title}</h2>
      <p>{workspace.description}</p>
      <StarBorder as={Link} to={workspace.href} color="#28c5ef" speed="9s" backgroundColor="var(--intro-button-bg)" textColor="var(--color-text-primary)" borderColor="var(--color-border-default)" className="workspace-intro-action">
        {workspace.action}<ArrowUpRight size={16} />
      </StarBorder>
    </div>
    <IntegrityScene compact />
    <span className="workspace-intro-index">PROCTOR / 01</span>
  </section>;
}
