import { Navigate } from 'react-router-dom';
import { useAuth } from '@/lib/auth-context';
import { type Role } from '@/lib/types';

interface ProtectedRouteProps {
  allowedRoles: Role[];
  children: React.ReactNode;
}

export function ProtectedRoute({ allowedRoles, children }: ProtectedRouteProps) {
  const { user, isAuthenticated } = useAuth();

  if (!isAuthenticated || !user) {
    return <Navigate to="/login" replace />;
  }

  if (!allowedRoles.includes(user.role)) {
    // Redirect to appropriate dashboard based on role
    const roleHome: Record<Role, string> = {
      Admin: '/admin/dashboard',
      HOD: '/hod/dashboard',
      Teacher: '/teacher/session-setup',
      'Exam Controller': '/exam-controller/schedule',
      Student: '/student/cases',
    };
    return <Navigate to={roleHome[user.role] || '/login'} replace />;
  }

  return <>{children}</>;
}
