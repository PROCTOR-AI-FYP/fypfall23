import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { signup, ALLOWED_EMAIL_DOMAIN } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import { FormField, Input } from '@/components/ui/FormElements';
import { Hexagon, Mail, User, Lock, CheckCircle2 } from 'lucide-react';
import { ThemeToggle } from '@/components/layout/ThemeToggle';

interface FormErrors {
  fullName?: string;
  email?: string;
  password?: string;
  confirmPassword?: string;
}

export function SignupPage() {
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [errors, setErrors] = useState<FormErrors>({});
  const [submitError, setSubmitError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const validate = (): boolean => {
    const e: FormErrors = {};
    if (!fullName.trim()) e.fullName = 'Full name is required';
    if (!email.trim()) e.email = 'Email is required';
    else if (!email.includes('@')) e.email = 'Enter a valid email address';
    if (!password) e.password = 'Password is required';
    else if (password.length < 8) e.password = 'Password must be at least 8 characters';
    if (confirmPassword !== password) e.confirmPassword = 'Passwords do not match';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitError('');
    if (!validate()) return;

    setSubmitting(true);
    try {
      await signup(fullName, email, password);
      // Neutral confirmation only — never distinguish new vs. existing account.
      setSubmitted(true);
    } catch (err) {
      const apiErr = err as { message?: string };
      setSubmitError(apiErr?.message || 'Something went wrong. Please try again.');
    }
    setSubmitting(false);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-(--color-bg-primary) px-4 py-8">
      <div className="absolute top-4 right-4">
        <ThemeToggle />
      </div>

      <div className="w-full max-w-md bg-(--color-bg-surface) border border-(--color-border-default) rounded-[6px] px-8 py-8">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-[6px] bg-(--color-accent-primary) flex items-center justify-center text-white">
            <Hexagon size={22} />
          </div>
          <div>
            <h1 className="font-[Sora] font-bold text-[22px] text-(--color-text-primary)">ProctorAI</h1>
            <p className="text-label text-(--color-text-muted)">Academic Integrity Platform</p>
          </div>
        </div>

        {submitted ? (
          <div className="flex flex-col items-center text-center gap-3 py-6">
            <div className="w-12 h-12 rounded-full bg-(--color-success-subtle) flex items-center justify-center text-(--color-success)">
              <CheckCircle2 size={24} />
            </div>
            <h2 className="text-display-md text-(--color-text-primary)">Check your inbox</h2>
            <p className="text-body text-(--color-text-secondary)">
              Check your inbox for a verification link to activate your account.
            </p>
            <Link
              to="/login"
              className="mt-2 text-body-sm text-(--color-accent-primary) font-medium hover:underline"
            >
              Back to sign in
            </Link>
          </div>
        ) : (
          <>
            <h2 className="text-display-md text-(--color-text-primary) mb-1">Create an account</h2>
            <p className="text-body text-(--color-text-secondary) mb-6">
              Self-service signup is available for students only
            </p>

            {submitError && (
              <div className="mb-4 px-4 py-3 bg-(--color-error-subtle) border border-(--color-error)/20 rounded-[6px] text-body-sm text-(--color-error)">
                {submitError}
              </div>
            )}

            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
              <FormField label="Full name" error={errors.fullName} required htmlFor="signup-name">
                <div className="relative">
                  <User size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-(--color-text-muted)" />
                  <Input
                    id="signup-name"
                    type="text"
                    value={fullName}
                    onChange={e => { setFullName(e.target.value); setErrors(prev => ({ ...prev, fullName: undefined })); }}
                    placeholder="Areeba Siddiqui"
                    hasError={!!errors.fullName}
                    className="pl-9"
                    autoComplete="name"
                  />
                </div>
              </FormField>

              <FormField label="Email address" error={errors.email} required htmlFor="signup-email">
                <div className="relative">
                  <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-(--color-text-muted)" />
                  <Input
                    id="signup-email"
                    type="email"
                    value={email}
                    onChange={e => { setEmail(e.target.value); setErrors(prev => ({ ...prev, email: undefined })); }}
                    placeholder={`232490@${ALLOWED_EMAIL_DOMAIN}`}
                    hasError={!!errors.email}
                    className="pl-9"
                    autoComplete="email"
                  />
                </div>
                <p className="text-label text-(--color-text-muted) mt-1">
                  Students, use your registration-number email, e.g. 232490@{ALLOWED_EMAIL_DOMAIN}
                </p>
              </FormField>

              <FormField label="Password" error={errors.password} required htmlFor="signup-password">
                <div className="relative">
                  <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-(--color-text-muted)" />
                  <Input
                    id="signup-password"
                    type="password"
                    value={password}
                    onChange={e => { setPassword(e.target.value); setErrors(prev => ({ ...prev, password: undefined })); }}
                    placeholder="Create a password"
                    hasError={!!errors.password}
                    className="pl-9"
                    autoComplete="new-password"
                  />
                </div>
              </FormField>

              <FormField label="Confirm password" error={errors.confirmPassword} required htmlFor="signup-confirm-password">
                <div className="relative">
                  <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-(--color-text-muted)" />
                  <Input
                    id="signup-confirm-password"
                    type="password"
                    value={confirmPassword}
                    onChange={e => { setConfirmPassword(e.target.value); setErrors(prev => ({ ...prev, confirmPassword: undefined })); }}
                    placeholder="Re-enter password"
                    hasError={!!errors.confirmPassword}
                    className="pl-9"
                    autoComplete="new-password"
                  />
                </div>
              </FormField>

              <Button type="submit" loading={submitting} size="lg" className="w-full mt-2">
                Create account
              </Button>
            </form>

            <p className="text-body-sm text-(--color-text-secondary) mt-6 text-center">
              Already have an account?{' '}
              <Link to="/login" className="text-(--color-accent-primary) font-medium hover:underline">
                Sign in
              </Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
