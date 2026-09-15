"use client";

/**
 * First-organization onboarding (product-gap fix before Phase 17).
 * Reached from: `/auth/callback` when `requires_onboarding` is true, or
 * `ProtectedShell` redirecting an authenticated-but-orgless user here on
 * any later visit (the authoritative signal is `/auth/me`'s
 * `requires_onboarding`, not a one-time callback flag — see
 * ProtectedShell.tsx and AuthProvider.tsx).
 *
 * Deliberately asks for nothing but an organization name — the backend
 * (`POST /organizations`) assigns the caller OWNER deterministically;
 * this form has no role selector and never could.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/features/auth/AuthProvider";
import { apiClient, ApiError, friendlyErrorMessage } from "@/lib/api-client";
import { Button, LoadingBlock } from "@/components/ui/primitives";
import { AgentABIMark } from "@/components/ui/icons";
import type { OrganizationCreateRequest, OrganizationOnboardingResponse } from "@/types/api";

export default function OnboardingPage() {
  const { isAuthenticated, isLoading, user, completeOnboarding } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated) {
      router.replace("/login");
      return;
    }
    // Already onboarded (organization created in another tab, or a
    // stale visit to this URL) — the backend would reject a second
    // onboarding attempt with 409, so just move on.
    if (user && !user.requires_onboarding) {
      router.replace("/dashboard");
    }
  }, [isLoading, isAuthenticated, user, router]);

  if (isLoading || !isAuthenticated || (user && !user.requires_onboarding)) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface-sunken">
        <LoadingBlock />
      </div>
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const payload: OrganizationCreateRequest = { name: name.trim() };
      const result = await apiClient.post<OrganizationOnboardingResponse>(
        "/organizations",
        payload,
      );
      await completeOnboarding(result);
      router.replace("/dashboard");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Your session has expired. Please sign in again.");
      } else if (err instanceof ApiError && err.status === 409) {
        // Already onboarded elsewhere — refresh auth state and move on
        // rather than showing this as a hard failure.
        router.replace("/dashboard");
        return;
      } else {
        setError(friendlyErrorMessage(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-sunken px-4">
      <div className="w-full max-w-md rounded-lg border border-border bg-surface-raised p-8 shadow-sm">
        <div className="flex flex-col items-center text-center">
          <AgentABIMark className="h-9 w-9 text-accent" />
          <h1 className="mt-3 text-lg font-semibold text-ink">Create your organization</h1>
          <p className="mt-1 text-sm text-ink-muted">
            This workspace owns your AgentABI projects, compatibility analyses, replays, risk
            assessments, and GitHub integrations.
          </p>
        </div>

        <form className="mt-6 space-y-3" onSubmit={handleSubmit}>
          <label className="flex flex-col gap-1 text-xs font-medium text-ink-muted">
            Organization name
            <input
              autoFocus
              className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Acme Inc."
              maxLength={255}
              required
            />
          </label>

          {error && (
            <p role="alert" className="text-xs text-block">
              {error}
            </p>
          )}

          <Button type="submit" className="w-full" disabled={submitting || !name.trim()}>
            {submitting ? "Creating…" : "Create organization"}
          </Button>
        </form>
      </div>
    </div>
  );
}
