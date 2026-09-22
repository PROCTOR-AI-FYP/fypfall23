import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { verifyEmail, resendVerification } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import { FormField, Input } from '@/components/ui/FormElements';
import { CheckCircle2, XCircle, Hexagon, Mail } from 'lucide-react';
import { ThemeToggle } from '@/components/layout/ThemeToggle';

type Status = 'loading' | 'success' | 'error';

export function VerifyEmailPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') || '';

  const [status, setStatus] = useState<Status>('loading');
  const [message, setMessage] = useState('');
  const [resendEmail, setResendEmail] = useState('');
  const [resending, setResending] = useState(false);
  const [resendSent, setResendSent] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      if (!token) {
        if (!cancelled) {
          setStatus('error');
          setMessage('This link is invalid or has expired.');
        }
        return;
      }
      try {
        const res = await verifyEmail(token);
        if (!cancelled) {
          setStatus('success');
          setMessage(res.data.message);
        }
      } catch (err) {
        if (!cancelled) {
          const apiErr = err as { message?: string };
          setStatus('error');
          setMessage(apiErr?.message || 'This link is invalid or has expired.');
        }
      }
    }

    run();
    return () => { cancelled = true; };
  }, [token]);

  const handleResend = async () => {
    if (!resendEmail.trim()) return;
    setResending(true);
    try {
      await resendVerification(resendEmail);
    } catch {
      // Same generic outcome — resend never reveals account existence.
    }
    setResendSent(true);
    setResending(false);
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

        {status === 'loading' && (
          <div className="flex flex-col items-center text-center gap-3 py-8">
            <svg className="animate-spin h-8 w-8 text-(--color-accent-primary)" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <p className="text-body text-(--color-text-secondary)">Verifying your email…</p>
          </div>
        )}

        {status === 'success' && (
          <div className="flex flex-col items-center text-center gap-3 py-6">
            <div className="w-12 h-12 rounded-full bg-(--color-success-subtle) flex items-center justify-center text-(--color-success)">
              <CheckCircle2 size={24} />
            </div>
            <h2 className="text-display-md text-(--color-text-primary)">Email verified</h2>
            <p className="text-body text-(--color-text-secondary)">{message || 'You can now sign in.'}</p>
            <Link
              to="/login"
              className="mt-2 px-5 py-2.5 text-[15px] font-medium rounded-[6px] bg-(--color-accent-primary) text-white hover:bg-(--color-accent-primary-hover) transition-colors"
            >
              Go to sign in
            </Link>
          </div>
        )}

        {status === 'error' && (
          <div className="flex flex-col gap-4 py-2">
            <div className="flex flex-col items-center text-center gap-3 py-4">
              <div className="w-12 h-12 rounded-full bg-(--color-error-subtle) flex items-center justify-center text-(--color-error)">
                <XCircle size={24} />
              </div>
              <h2 className="text-display-md text-(--color-text-primary)">{message || 'This link is invalid or has expired'}</h2>
              <p className="text-body text-(--color-text-secondary)">
                Request a new verification link below.
              </p>
            </div>

            {resendSent ? (
              <p className="text-body-sm text-(--color-text-secondary) text-center">
                If this email is valid, a verification link has been sent.
              </p>
            ) : (
              <div className="flex flex-col gap-3">
                <FormField label="Email address" htmlFor="resend-email">
                  <div className="relative">
                    <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-(--color-text-muted)" />
                    <Input
                      id="resend-email"
                      type="email"
                      value={resendEmail}
                      onChange={e => setResendEmail(e.target.value)}
                      placeholder="232490@students.au.edu.pk"
                      className="pl-9"
                      autoComplete="email"
                    />
                  </div>
                </FormField>
                <Button onClick={handleResend} loading={resending} disabled={!resendEmail.trim()}>
                  Resend verification email
                </Button>
              </div>
            )}

            <p className="text-body-sm text-(--color-text-secondary) mt-2 text-center">
              <Link to="/login" className="text-(--color-accent-primary) font-medium hover:underline">
                Back to sign in
              </Link>
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
