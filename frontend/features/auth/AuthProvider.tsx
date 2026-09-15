"use client";

/**
 * Auth session state (Phase 14 spec §8). Wraps `/auth/me`, tracks the
 * current user/role/org, and registers the 401 handler that
 * lib/api-client.ts calls into.
 *
 * See docs/DECISIONS.md for the OAuth token-handling ADR: the backend
 * returns the JWT as a JSON body from `/auth/github/callback`, with no
 * cookie or frontend-redirect mechanism built in. This frontend never
 * changes that backend behavior — instead, `github_oauth_redirect_uri`
 * is configured (env only, no code change) to point at this app's own
 * `/auth/callback` route, which receives GitHub's `code`/`state` query
 * params, forwards them to the backend's callback endpoint via a
 * client-side fetch, and stores the returned JWT.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient, registerUnauthorizedHandler } from "@/lib/api-client";
import { clearStoredToken, getStoredToken, setStoredToken } from "@/lib/auth-storage";
import type {
  AuthMeResponse,
  GitHubCallbackResponse,
  OrganizationOnboardingResponse,
} from "@/types/api";

interface AuthContextValue {
  user: AuthMeResponse | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  /** Redirects the browser to the backend's GitHub OAuth login route. */
  loginWithGitHub: () => void;
  logout: () => void;
  /** Called only by /auth/callback once it has exchanged the code. */
  completeLogin: (result: GitHubCallbackResponse) => void;
  /** Called only by /onboarding once `POST /organizations` succeeds.
   * Stores the fresh, organization-scoped JWT the backend just issued,
   * then reloads `/auth/me` so `user` (role, organization_id) is always
   * the server's own view — never assembled client-side from the
   * onboarding response alone. */
  completeOnboarding: (result: OrganizationOnboardingResponse) => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const API_BASE_URL = process.env.NEXT_PUBLIC_AGENTABI_API_URL ?? "http://localhost:8000/api/v1";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthMeResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const queryClient = useQueryClient();

  const clearSession = useCallback(() => {
    clearStoredToken();
    setUser(null);
    queryClient.clear();
  }, [queryClient]);

  const refresh = useCallback(async () => {
    const token = getStoredToken();
    if (!token) {
      setUser(null);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    try {
      const me = await apiClient.get<AuthMeResponse>("/auth/me");
      setUser(me);
    } catch {
      // api-client already cleared the token + fired onUnauthorized on 401
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    registerUnauthorizedHandler(clearSession);
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loginWithGitHub = useCallback(() => {
    window.location.href = `${API_BASE_URL}/auth/github/login`;
  }, []);

  const completeLogin = useCallback((result: GitHubCallbackResponse) => {
    setStoredToken(result.access_token);
    setUser({
      user_id: result.user_id,
      email: result.email,
      organization_id: result.organization_id,
      role: result.role,
      requires_onboarding: result.requires_onboarding,
    });
  }, []);

  const completeOnboarding = useCallback(
    async (result: OrganizationOnboardingResponse) => {
      setStoredToken(result.access_token);
      await refresh();
    },
    [refresh],
  );

  const logout = useCallback(() => {
    // No backend logout route (stateless JWT, per spec §8) — clearing
    // the client-held token is the entire logout action.
    clearSession();
  }, [clearSession]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      isAuthenticated: user !== null,
      loginWithGitHub,
      logout,
      completeLogin,
      completeOnboarding,
      refresh,
    }),
    [user, isLoading, loginWithGitHub, logout, completeLogin, completeOnboarding, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
