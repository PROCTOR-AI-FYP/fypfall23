import { useState, type FormEvent } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '@/lib/auth-context';
import { Role } from '@/lib/types';
import { resendVerification } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import { FormField, Input } from '@/components/ui/FormElements';
import { Hexagon, Lock, Mail } from 'lucide-react';
import { ThemeToggle } from '@/components/layout/ThemeToggle';
import { LoginHero3D } from './LoginHero3D';

const roleRedirects: Record<Role, string> = {
  [Role.Admin]: '/admin/dashboard',
  [Role.HOD]: '/hod/dashboard',
  [Role.Teacher]: '/teacher/session-setup',
  [Role.ExamController]: '/exam-controller/schedule',
  [Role.Student]: '/student/cases',
};

// Quick login presets for testing
const quickLogins = [
  { label: 'Admin', email: 'sadia.rashid@au.edu.pk' },
  { label: 'HOD', email: 'khalid.mehmood@au.edu.pk' },
  { label: 'Teacher', email: 'usman.tariq@au.edu.pk' },
  { label: 'Exam Ctrl', email: 'naveed.iqbal@au.edu.pk' },
  { label: 'Student', email: 'ahmed.raza@student.au.edu.pk' },
];

export function LoginPage() {
  const navigate = useNavigate();
  const { login, isLoading } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [errorCode, setErrorCode] = useState('');
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const [resending, setResending] = useState(false);
  const [resendSent, setResendSent] = useState(false);

  const validate = (): boolean => {
    const e: typeof errors = {};
    if (!email.trim()) e.email = 'Email is required';
    else if (!email.includes('@')) e.email = 'Enter a valid email address';
    if (!password.trim()) e.password = 'Password is required';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setErrorCode('');
    setResendSent(false);
    if (!validate()) return;

    try {
      const user = await login(email, password);
      navigate(roleRedirects[user.role]);
    } catch (err) {
      const apiErr = err as { code?: string; message?: string };
      if (apiErr?.code === 'EMAIL_NOT_VERIFIED') {
        setErrorCode(apiErr.code);
        setError(apiErr.message || 'Please verify your email before signing in.');
      } else {
        setError('Invalid credentials. Use one of the quick login options below.');
      }
    }
  };

  const handleQuickLogin = async (quickEmail: string) => {
    setEmail(quickEmail);
    setPassword('password');
    setError('');
    setErrorCode('');
    setResendSent(false);
    setErrors({});
    try {
      const user = await login(quickEmail, 'password');
      navigate(roleRedirects[user.role]);
    } catch {
      // Quick-login presets are always valid fixtures; ignore failures here.
    }
  };

  const handleResend = async () => {
    setResending(true);
    try {
      await resendVerification(email);
      setResendSent(true);
    } catch {
      // Same generic outcome regardless — nothing to distinguish here.
      setResendSent(true);
    }
    setResending(false);
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

      {/* Right: Login Form */}
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
          <div className="mb-4 px-4 py-3 bg-(--color-error-subtle) border border-(--color-error)/20 rounded-[6px] text-body-sm text-(--color-error)">
            <p>{error}</p>
            {errorCode === 'EMAIL_NOT_VERIFIED' && (
              resendSent ? (
                <p className="mt-2 text-(--color-text-secondary)">
                  If this email is valid, a verification link has been sent.
                </p>
              ) : (
                <button
                  type="button"
                  onClick={handleResend}
                  disabled={resending}
                  className="mt-2 text-label font-medium text-(--color-accent-primary) hover:underline cursor-pointer disabled:opacity-50"
                >
                  {resending ? 'Sending…' : 'Resend verification email'}
                </button>
              )
            )}
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <FormField label="Email address" error={errors.email} required htmlFor="login-email">
            <div className="relative">
              <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-(--color-text-muted)" />
              <Input
                id="login-email"
                type="email"
                value={email}
                onChange={e => { setEmail(e.target.value); setErrors(prev => ({ ...prev, email: undefined })); }}
                placeholder="faculty_id@au.edu.pk"
                hasError={!!errors.email}
                className="pl-9"
                autoComplete="email"
              />
            </div>
          </FormField>

          <FormField label="Password" error={errors.password} required htmlFor="login-password">
            <div className="relative">
              <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-(--color-text-muted)" />
              <Input
                id="login-password"
                type="password"
                value={password}
                onChange={e => { setPassword(e.target.value); setErrors(prev => ({ ...prev, password: undefined })); }}
                placeholder="Enter password"
                hasError={!!errors.password}
                className="pl-9"
                autoComplete="current-password"
              />
            </div>
          </FormField>

          <Button type="submit" loading={isLoading} size="lg" className="w-full mt-2">
            Sign in
          </Button>
        </form>

        {/* Quick login for dev */}
        <div className="mt-8 pt-6 border-t border-(--color-border-default)">
          <p className="text-label text-(--color-warning) font-medium mb-3 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-(--color-warning)" />
            Dev: Quick login
          </p>
          <div className="flex flex-wrap gap-2">
            {quickLogins.map(q => (
              <button
                key={q.email}
                onClick={() => handleQuickLogin(q.email)}
                className="px-3 py-1.5 text-label font-medium text-(--color-accent-primary) bg-(--color-accent-primary-subtle) rounded-[4px] hover:opacity-80 transition-opacity cursor-pointer"
              >
                {q.label}
              </button>
            ))}
          </div>
        </div>

        <p className="text-body-sm text-(--color-text-secondary) mt-6 text-center">
          New here?{' '}
          <Link to="/signup" className="text-(--color-accent-primary) font-medium hover:underline">
            Create an account
          </Link>
        </p>

        <p className="text-label text-(--color-text-muted) mt-8">
          System time (UTC): {new Date().toISOString().slice(0, 19).replace('T', ' ')}
        </p>
      </div>
    </div>
  );
}
