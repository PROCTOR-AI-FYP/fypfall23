import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react';
import { type User, type AuthState, Role } from './types';
import { exchangeGoogleSession, getCurrentUser, logout as apiLogout, UNAUTHORIZED_EVENT } from './api';
import { startGoogleSignIn, completeGoogleSignIn } from './supabase';
import { LoadingState } from '@/components/ui/DataDisplay';

interface AuthContextValue extends AuthState {
  // Redirects to Google; the browser comes back to /login?code=...
  signInWithGoogle: () => Promise<void>;
  // Finishes the round trip: code -> Supabase token -> backend session cookie.
  // Resolves with the signed-in user, or throws the backend's ApiError
  // (e.g. a non-university account or an unprovisioned staff email).
  completeSignIn: (code: string) => Promise<User>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    isAuthenticated: false,
    isLoading: false,
  });
  // The session cookie is httpOnly, so the only way to know who is signed in
  // after a refresh is to ask the backend.
  const [restoring, setRestoring] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getCurrentUser()
      .then(res => { if (!cancelled) setState({ user: res.data, isAuthenticated: true, isLoading: false }); })
      .catch(() => { /* no live session */ })
      .finally(() => { if (!cancelled) setRestoring(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const dropSession = () => setState({ user: null, isAuthenticated: false, isLoading: false });
    window.addEventListener(UNAUTHORIZED_EVENT, dropSession);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, dropSession);
  }, []);

  const signInWithGoogle = useCallback(async () => {
    setState(prev => ({ ...prev, isLoading: true }));
    try {
      await startGoogleSignIn();
    } catch (err) {
      setState(prev => ({ ...prev, isLoading: false }));
      throw err;
    }
  }, []);

  const completeSignIn = useCallback(async (code: string): Promise<User> => {
    setState(prev => ({ ...prev, isLoading: true }));
    try {
      const accessToken = await completeGoogleSignIn(code);
      const res = await exchangeGoogleSession(accessToken);
      setState({ user: res.data, isAuthenticated: true, isLoading: false });
      return res.data;
    } catch (err) {
      setState(prev => ({ ...prev, isLoading: false }));
      throw err;
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // Unreachable server or already-expired cookie: signing out locally still has to work.
    } finally {
      setState({ user: null, isAuthenticated: false, isLoading: false });
    }
  }, []);

  if (restoring) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-(--color-bg-primary)">
        <LoadingState message="Checking your session..." />
      </div>
    );
  }

  return (
    <AuthContext.Provider value={{ ...state, signInWithGoogle, completeSignIn, logout }}>
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
