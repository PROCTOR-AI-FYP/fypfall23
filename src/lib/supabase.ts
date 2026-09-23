// ═══════════════════════════════════════════
// Supabase Auth client — Google sign-in only.
// Uses the public anon key (never service_role). Supabase performs the OAuth
// redirect and code exchange; the resulting access token is handed once to
// our backend (POST /api/auth/session), which verifies it and sets the app's
// own httpOnly session cookie. The Supabase session itself is then discarded.
// ═══════════════════════════════════════════

import { createClient, type SupabaseClient } from '@supabase/supabase-js';

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export const ALLOWED_EMAIL_DOMAIN =
  (import.meta.env.VITE_ALLOWED_EMAIL_DOMAIN as string | undefined) || 'students.au.edu.pk';

let client: SupabaseClient | null = null;

function getSupabase(): SupabaseClient {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
    throw { message: 'Sign-in is not configured (VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY).', code: 'CONFIG', status: 0 };
  }
  if (!client) {
    client = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
      auth: {
        flowType: 'pkce',
        // The Login page exchanges the ?code= itself so the order of events is explicit.
        detectSessionInUrl: false,
        autoRefreshToken: false,
        // Only the PKCE verifier needs to survive the Google round trip; keep it
        // out of localStorage and scoped to this tab.
        storage: window.sessionStorage,
      },
    });
  }
  return client;
}

/** Leaves the app for Google's account picker; returns here with ?code=. */
export async function startGoogleSignIn(): Promise<void> {
  const { error } = await getSupabase().auth.signInWithOAuth({
    provider: 'google',
    options: {
      redirectTo: `${window.location.origin}/login`,
      // UX hint only: Google pre-filters to the university domain. The backend
      // enforces the domain on the verified email regardless.
      queryParams: { hd: ALLOWED_EMAIL_DOMAIN, prompt: 'select_account' },
    },
  });
  if (error) throw { message: error.message, code: 'OAUTH_START', status: 0 };
}

/** Exchanges the OAuth ?code= for a Supabase access token, then forgets the Supabase session. */
export async function completeGoogleSignIn(code: string): Promise<string> {
  const supabase = getSupabase();
  const { data, error } = await supabase.auth.exchangeCodeForSession(code);
  if (error || !data.session) {
    throw { message: error?.message || 'Google sign-in could not be completed.', code: 'OAUTH_EXCHANGE', status: 0 };
  }
  const accessToken = data.session.access_token;
  // The app's own cookie is the session from here on; drop Supabase's tokens.
  await supabase.auth.signOut({ scope: 'local' });
  return accessToken;
}
