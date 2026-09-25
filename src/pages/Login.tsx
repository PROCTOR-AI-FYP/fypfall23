import { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '@/lib/auth-context';
import { Role } from '@/lib/types';
import { Button } from '@/components/ui/Button';
import { ArrowLeft } from 'lucide-react';
import { ThemeToggle } from '@/components/layout/ThemeToggle';
import { Logo } from '@/components/ui/Logo';
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
    <div className="min-h-screen w-full bg-(--color-bg-primary) text-(--color-text-primary) flex flex-col justify-between relative overflow-x-hidden">
      {/* ── Fixed Floating Header ──────────────────────────── */}
      <header className="w-full flex items-center justify-between px-6 lg:px-12 py-4 z-20">
        <Link
          to="/"
          className="flex items-center gap-3 group outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40 rounded-full py-1 px-2 -ml-2 hover:opacity-90 transition-opacity"
          title="Return to ProctorAI Overview"
        >
          <Logo size={28} />
          <div className="flex flex-col">
            <span className="font-[Sora] font-bold text-base sm:text-lg tracking-tight text-(--color-text-primary)">
              ProctorAI
            </span>
            <span className="text-[11px] text-(--color-text-muted) -mt-1 hidden sm:block">
              Academic Integrity Platform
            </span>
          </div>
        </Link>

        <div className="flex items-center gap-3">
          <Link
            to="/"
            className="text-body-sm font-medium text-(--color-text-secondary) hover:text-(--color-text-primary) px-3.5 py-1.5 rounded-full border border-(--color-border-default) bg-(--color-bg-surface)/80 hover:bg-(--color-bg-surface) transition-colors inline-flex items-center gap-1.5 shadow-2xs cursor-pointer"
          >
            <ArrowLeft size={14} />
            <span>Overview</span>
          </Link>
          <div className="h-4 w-px bg-(--color-border-default)" aria-hidden="true" />
          <ThemeToggle />
        </div>
      </header>

      {/* ── Main Sign In Container ────────────────────────── */}
      <main className="max-w-6xl mx-auto w-full px-4 sm:px-6 lg:px-12 my-auto py-6 sm:py-8 z-10">
        {/* Section Heading */}
        <div className="mb-6 text-center sm:text-left flex flex-col sm:flex-row sm:items-end justify-between gap-4">
          <div>
            <div className="text-label text-(--color-accent-primary) font-semibold tracking-wider uppercase mb-1">
              Security Gateway
            </div>
            <h1 className="text-display-md text-(--color-text-primary)">
              Institutional Access &amp; Live Seat Telemetry
            </h1>
          </div>
          <p className="text-body-sm text-(--color-text-secondary) max-w-md">
            Please authenticate using your institutional Google workspace credentials. Permissions are assigned based on your academic role.
          </p>
        </div>

        {/* Unified Frame containing 3D Hero on Left and Login Card on Right */}
        <div className="rounded-xl border border-(--color-border-default) bg-(--color-bg-surface) shadow-sm overflow-hidden flex flex-col lg:flex-row min-h-[580px]">
          {/* Left: 3D Hero Seat Grid */}
          <div className="hidden lg:flex flex-1 flex-col relative overflow-hidden bg-(--color-bg-primary)/40 border-b lg:border-b-0 lg:border-r border-(--color-border-default) min-h-[460px]">
            <div className="absolute top-4 left-4 z-10 flex items-center gap-2 px-3 py-1.5 rounded-md bg-(--color-bg-surface)/90 border border-(--color-border-default) backdrop-blur-xs">
              <span className="w-2 h-2 rounded-full bg-(--color-success) animate-pulse" />
              <span className="text-label text-(--color-text-secondary) font-medium">Hall-04 Spatial Grid Active</span>
            </div>

            <div className="flex-1 w-full h-full">
              <LoginHero3D />
            </div>

            {/* Overlay info footer */}
            <div className="p-4 bg-(--color-bg-surface)/90 backdrop-blur-xs border-t border-(--color-border-default)">
              <div className="flex items-center justify-between text-body-sm">
                <div className="flex items-center gap-2 text-(--color-success)">
                  <span className="w-2 h-2 rounded-full bg-(--color-success)" />
                  <span className="text-label font-medium">Monitoring engine operational</span>
                </div>
                <span className="text-label text-(--color-text-muted)">256-bit TLS encrypted session, FERPA compliant</span>
              </div>
            </div>
          </div>

          {/* Right: Sign-in Form */}
          <div className="w-full lg:w-[460px] flex flex-col justify-center p-8 sm:p-12 bg-(--color-bg-surface)">
            {/* Emblem */}
            <div className="flex items-center gap-3 mb-8">
              <Logo size={42} />
              <div>
                <h2 className="font-[Sora] font-bold text-[20px] text-(--color-text-primary) leading-tight">ProctorAI</h2>
                <p className="text-label text-(--color-text-muted)">Authorized Sign In</p>
              </div>
            </div>

            <h3 className="text-display-sm text-(--color-text-primary) mb-2">Sign in</h3>
            <p className="text-body text-(--color-text-secondary) mb-6">
              Authenticate with your university credentials to access the proctoring tribunal or invigilation tools.
            </p>

            {error && (
              <div role="alert" className="mb-4 px-4 py-3 bg-(--color-error-subtle) border border-(--color-error)/20 rounded-[6px] text-body-sm text-(--color-error)">
                <p>{error}</p>
              </div>
            )}

            <Button
              type="button"
              onClick={handleGoogleSignIn}
              loading={isLoading}
              size="lg"
              className="w-full mt-2"
            >
              Sign in with Google
            </Button>

            <div className="mt-8 pt-6 border-t border-(--color-border-default) space-y-2">
              <div className="flex items-center justify-between text-label text-(--color-text-muted)">
                <span>Security Protocol</span>
                <span className="font-medium text-(--color-text-secondary)">OAuth 2.0 / SSO</span>
              </div>
              <div className="flex items-center justify-between text-label text-(--color-text-muted)">
                <span>System Time (UTC)</span>
                <span className="font-mono text-body-sm text-(--color-text-secondary)">
                  {new Date().toISOString().slice(0, 19).replace('T', ' ')}
                </span>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* ── Footer docked at bottom of Login Section ───────── */}
      <footer className="w-full border-t border-(--color-border-default) bg-(--color-bg-surface)/95 backdrop-blur-xs py-4 px-6 lg:px-12 flex flex-col sm:flex-row items-center justify-between gap-4 text-label text-(--color-text-muted)">
        <div className="flex items-center gap-2.5">
          <Logo size={18} />
          <span>ProctorAI University Examination System — Pilot Deployment</span>
        </div>
        <div>
          <span>Evidentiary integrity · Multi-camera spatial inference · FERPA compliant</span>
        </div>
      </footer>
    </div>
  );
}
