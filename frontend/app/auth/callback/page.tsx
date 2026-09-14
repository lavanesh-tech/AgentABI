"use client";

/**
 * This route is what `github_oauth_redirect_uri` (backend env config)
 * must point at, e.g. `http://localhost:3000/auth/callback` — see
 * docs/DECISIONS.md for the full ADR. GitHub redirects the browser
 * here with `code`/`state`/`error` query params (identical to what it
 * would send the backend's own callback route); this page forwards
 * those same params to the backend's `/auth/github/callback` via a
 * client-side fetch, reads the JSON body it returns (never a redirect,
 * never a cookie — confirmed directly from app/api/v1/auth.py), and
 * stores the JWT. No backend code changes — only the redirect_uri
 * value differs from its default.
 */

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/features/auth/AuthProvider";
import { apiClient, friendlyErrorMessage } from "@/lib/api-client";
import { ErrorState, LoadingBlock } from "@/components/ui/primitives";
import type { GitHubCallbackResponse } from "@/types/api";

function CallbackInner() {
  const params = useSearchParams();
  const router = useRouter();
  const { completeLogin } = useAuth();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = params.get("code");
    const state = params.get("state");
    const oauthError = params.get("error");

    apiClient
      .getUnauthenticated<GitHubCallbackResponse>("/auth/github/callback", {
        code,
        state,
        error: oauthError,
      })
      .then((result) => {
        completeLogin(result);
        router.replace("/dashboard");
      })
      .catch((err) => setError(friendlyErrorMessage(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  if (error) return <ErrorState message={error} />;
  return <LoadingBlock />;
}

export default function AuthCallbackPage() {
  return (
    <div className="flex h-screen items-center justify-center bg-surface-sunken">
      <Suspense fallback={<LoadingBlock />}>
        <CallbackInner />
      </Suspense>
    </div>
  );
}
