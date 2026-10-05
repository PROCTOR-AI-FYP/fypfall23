interface SessionAccount { id: string }

/** A sign-in response is insufficient: verify the browser actually sends its cookie. */
export async function establishBrowserSession<T extends SessionAccount>(
  exchange: () => Promise<T>,
  readSession: () => Promise<T>,
): Promise<T> {
  const signedIn = await exchange();
  let current: T;
  try {
    current = await readSession();
  } catch (error) {
    const failure = error as { status?: number; message?: string } | null;
    if (failure?.status !== 401 || (failure.message && failure.message !== 'Not authenticated')) throw error;
    throw {
      message: 'Your browser could not keep the sign-in session. Allow cookies for this website. '
        + 'For local development, restart the frontend and use the same website address throughout sign-in.',
      code: 'SESSION_NOT_ESTABLISHED', status: 401,
    };
  }
  if (current.id !== signedIn.id) {
    throw { message: 'The browser session belongs to a different account. Sign out and try again.',
      code: 'SESSION_ACCOUNT_MISMATCH', status: 401 };
  }
  // The persisted session is authoritative, including any role/status change.
  return current;
}
