import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/lib/auth-context';
import { Role } from '@/lib/types';
import { Button } from '@/components/ui/Button';
import { Hexagon } from 'lucide-react';
import { ThemeToggle } from '@/components/layout/ThemeToggle';
import { LoginHero3D } from './LoginHero3D';

const roleRedirects: Record<Role, string> = {
  [Role.Admin]: '/admin/dashboard',
  [Role.HOD]: '/hod/dashboard',
  [Role.Teacher]: '/teacher/session-setup',
  [Role.ExamController]: '/exam-controller/schedule',
  [Role.Student]: '/student/cases',
};

// An OAuth code can be redeemed exactly once; StrictMode runs effects twice in dev.
const redeemedCodes = new Set<string>();

export function LoginPage() {
  const navigate = useNavigate();
  const { user, isAuthenticated, isLoading, signInWithGoogle, completeSignIn } = useAuth();
  const [error, setError] = useState('');

  // Returning from Google: /login?code=... (or ?error=... if the user backed out).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const oauthError = params.get('error_description') || params.get('error');
    if (!code && !oauthError) return;
    window.history.replaceState(null, '', window.location.pathname);

    if (oauthError) {
      setError(oauthError);
      return;
    }
    if (!code || redeemedCodes.has(code)) return;
    redeemedCodes.add(code);
    completeSignIn(code)
      .then(signedIn => navigate(roleRedirects[signedIn.role], { replace: true }))
      .catch(err => setError((err as { message?: string })?.message || 'Sign-in failed. Please try again.'));
  }, [completeSignIn, navigate]);

  useEffect(() => {
    if (isAuthenticated && user) navigate(roleRedirects[user.role], { replace: true });
  }, [isAuthenticated, user, navigate]);

  const handleGoogleSignIn = async () => {
    setError('');
    try {
      await signInWithGoogle();
    } catch (err) {
      setError((err as { message?: string })?.message || 'Could not start Google sign-in.');
    }
  };

  return (
    <div className="min-h-screen flex bg-(--color-bg-primary)">
      {/* Left: 3D Hero */}
      <div className="hidden lg:flex flex-1 items-center justify-center relative overflow-hidden bg-(--color-bg-surface)">
        <LoginHero3D />
        {/* Overlay info */}
        <div className="absolute bottom-8 left-8 right-8">
          <div className="bg-(--color-bg-surface)/80 backdrop-blur-sm border border-(--color-border-default) rounded-[6px] px-4 py-3">
            <div className="flex items-center gap-2 mb-1">
              <div className="w-2 h-2 rounded-full bg-(--color-success) animate-pulse" />
              <span className="text-label text-(--color-success) font-medium">Monitoring engine operational</span>
            </div>
            <p className="text-body-sm text-(--color-text-muted)">
              256-bit TLS encrypted session, FERPA compliant
            </p>
          </div>
        </div>
      </div>

      {/* Right: Sign-in */}
      <div className="w-full lg:w-[480px] flex flex-col justify-center px-8 lg:px-12 py-8 bg-(--color-bg-surface) lg:border-l border-(--color-border-default)">
        {/* Theme toggle */}
        <div className="absolute top-4 right-4">
          <ThemeToggle />
        </div>

        {/* Logo */}
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-[6px] bg-(--color-accent-primary) flex items-center justify-center text-white">
            <Hexagon size={22} />
          </div>
          <div>
            <h1 className="font-[Sora] font-bold text-[22px] text-(--color-text-primary)">ProctorAI</h1>
            <p className="text-label text-(--color-text-muted)">Academic Integrity Platform</p>
          </div>
        </div>

        <h2 className="text-display-md text-(--color-text-primary) mb-1">Sign in</h2>
        <p className="text-body text-(--color-text-secondary) mb-6">
          Authenticate with your institutional credentials
        </p>

        {error && (
          <div role="alert" className="mb-4 px-4 py-3 bg-(--color-error-subtle) border border-(--color-error)/20 rounded-[6px] text-body-sm text-(--color-error)">
            <p>{error}</p>
          </div>
        )}

        <Button type="button" onClick={handleGoogleSignIn} loading={isLoading} size="lg" className="w-full mt-2">
          Sign in with Google
        </Button>

        <p className="text-label text-(--color-text-muted) mt-8">
          System time (UTC): {new Date().toISOString().slice(0, 19).replace('T', ' ')}
        </p>
      </div>
    </div>
  );
}
