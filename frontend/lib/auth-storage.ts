/**
 * Token storage boundary (Phase 14 spec §8, ADR in docs/DECISIONS.md).
 *
 * The AgentABI backend's `/auth/github/callback` returns the JWT as a
 * JSON response body — there is no httpOnly cookie mechanism in the
 * existing implementation, and adding one would mean redesigning the
 * backend's OAuth flow, which spec §1/§8 explicitly rules out ("do not
 * assume endpoints exist... inspect the actual backend OAuth callback
 * behavior first"). Given that constraint, sessionStorage is the
 * safest practical option available without a backend change:
 * scoped to one browser tab, cleared when the tab closes, and never
 * sent automatically on cross-origin requests (unlike a non-httpOnly
 * cookie). It is still readable by any script on the page, so this is
 * a real, accepted XSS exposure tradeoff — not a claim of full safety.
 *
 * This module is the ONLY place that touches the stored token. Never
 * import `sessionStorage` directly elsewhere.
 */

const TOKEN_KEY = "agentabi_access_token";

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    // sessionStorage unavailable (private mode, etc.) — the session
    // simply won't persist; never throw out of a storage write.
  }
}

export function clearStoredToken(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // no-op
  }
}
