import { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '@/lib/auth-context';
import { Role } from '@/lib/types';
import { Button } from '@/components/ui/Button';
import { ArrowUpRight, ShieldCheck, ScanLine, Scale, LockKeyhole } from 'lucide-react';
import { ThemeToggle } from '@/components/layout/ThemeToggle';
import { Logo } from '@/components/ui/Logo';
import { IntegrityScene } from '@/components/visual/IntegrityScene';
import StarBorder from '@/components/reactbits/StarBorder';

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
    <div className="auth-page">
      <header className="auth-header">
        <Link to="/" className="auth-brand" aria-label="ProctorAI home"><Logo size={32} /><span>ProctorAI<small>ACADEMIC INTEGRITY</small></span></Link>
        <div className="auth-header-actions"><Link to="/">Back to overview<ArrowUpRight size={14} /></Link><ThemeToggle /></div>
      </header>
      <main className="auth-main">
        <section className="auth-story">
          <span className="workspace-eyebrow"><ScanLine size={15} />A clearer perspective</span>
          <h1>Built to observe.<br />Designed to be <em>fair.</em></h1>
          <p>Intelligent exam monitoring. Considered human review. One connected academic community.</p>
          <IntegrityScene />
          <div className="auth-story-features">
            <div><ScanLine size={18} /><strong>Observe</strong><span>Signals in context</span></div>
            <div><ShieldCheck size={18} /><strong>Review</strong><span>Evidence with clarity</span></div>
            <div><Scale size={18} /><strong>Resolve</strong><span>A fair process</span></div>
          </div>
        </section>
        <section className="auth-signin" aria-labelledby="signin-heading">
          <div className="auth-signin-top"><span className="auth-signin-icon"><LockKeyhole size={23} /></span><span className="auth-access-label">INSTITUTIONAL ACCESS</span></div>
          <h2 id="signin-heading">Welcome back.</h2>
          <p className="auth-signin-description">Your workspace is ready. Sign in with your university Google account to continue.</p>
          {error && <div role="alert" className="auth-error">{error}</div>}
          <StarBorder as="div" color="#28c5ef" speed="8s" backgroundColor="var(--color-bg-surface)" textColor="var(--color-text-primary)" borderColor="var(--color-border-default)" className="auth-google-frame">
            <Button type="button" onClick={handleGoogleSignIn} loading={isLoading} size="lg" className="auth-google-button">
              <svg width="19" height="19" viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M21.6 12.2c0-.7-.1-1.4-.2-2.1H12v4h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.8 3-4.3 3-7.4Z"/><path fill="#34A853" d="M12 22c2.7 0 5-1 6.6-2.4l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.2H3.1v2.6A10 10 0 0 0 12 22Z"/><path fill="#FBBC05" d="M6.4 13.9a6 6 0 0 1 0-3.8V7.5H3.1a10 10 0 0 0 0 9l3.3-2.6Z"/><path fill="#EA4335" d="M12 5.9c1.5 0 2.8.5 3.8 1.5l2.8-2.8A9.6 9.6 0 0 0 12 2a10 10 0 0 0-8.9 5.5l3.3 2.6A6 6 0 0 1 12 5.9Z"/></svg>
              Sign in with Google<ArrowUpRight size={17} />
            </Button>
          </StarBorder>
          <div className="auth-divider"><span />One account. Your assigned role.<span /></div>
          <div className="auth-roles"><span>Administration</span><span>Examination office</span><span>Invigilation</span><span>Academic review</span><span>Students</span></div>
          <div className="auth-note"><ShieldCheck size={19} /><p>Access follows your institutional role. Student cases and review evidence are visible only to authorised accounts.</p></div>
          <div className="auth-signin-footer"><span>University examination platform</span><Logo size={20} /></div>
        </section>
      </main>
      <footer className="auth-footer"><span>ProctorAI · Academic integrity, thoughtfully.</span><span>Observe. Review. Resolve.</span></footer>
    </div>
  );
}
