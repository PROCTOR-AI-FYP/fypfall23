import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import { type User, type AuthState, Role } from './types';
import { users } from './fixtures';
import { login as apiLogin } from './api';

interface AuthContextValue extends AuthState {
  // Resolves with the authenticated user, or throws the mock ApiError
  // (e.g. code: 'EMAIL_NOT_VERIFIED') so callers can react to why it failed.
  login: (email: string, password: string) => Promise<User>;
  logout: () => void;
  switchRole: (role: Role) => void; // Dev-only
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

// Default users per role for dev role-switching
const roleDefaults: Record<Role, string> = {
  [Role.Admin]: 'usr-001',
  [Role.HOD]: 'usr-002',
  [Role.Teacher]: 'usr-004',
  [Role.ExamController]: 'usr-009',
  [Role.Student]: 'usr-010',
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    isAuthenticated: false,
    isLoading: false,
  });

  const login = useCallback(async (email: string, password: string): Promise<User> => {
    setState(prev => ({ ...prev, isLoading: true }));
    try {
      const res = await apiLogin(email, password);
      setState({ user: res.data, isAuthenticated: true, isLoading: false });
      return res.data;
    } catch (err) {
      setState(prev => ({ ...prev, isLoading: false }));
      throw err;
    }
  }, []);

  const logout = useCallback(() => {
    setState({ user: null, isAuthenticated: false, isLoading: false });
  }, []);

  const switchRole = useCallback((role: Role) => {
    const userId = roleDefaults[role];
    const user = users.find(u => u.id === userId) as User;
    setState({ user, isAuthenticated: true, isLoading: false });
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, logout, switchRole }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
}

// Route-level role check
export function hasRole(user: User | null, allowedRoles: Role[]): boolean {
  if (!user) return false;
  return allowedRoles.includes(user.role);
}
