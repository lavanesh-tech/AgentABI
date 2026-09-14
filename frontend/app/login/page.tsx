"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/features/auth/AuthProvider";
import { Button } from "@/components/ui/primitives";

export default function LoginPage() {
  const { isAuthenticated, isLoading, loginWithGitHub } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && isAuthenticated) router.replace("/dashboard");
  }, [isLoading, isAuthenticated, router]);

  return (
    <div className="flex h-screen items-center justify-center bg-surface-sunken">
      <div className="w-full max-w-sm rounded-md border border-border bg-surface-raised p-8 text-center">
        <h1 className="text-lg font-bold text-ink">AgentABI</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Agent Compatibility &amp; Upgrade Intelligence Platform
        </p>
        <Button className="mt-6 w-full" onClick={loginWithGitHub}>
          Sign in with GitHub
        </Button>
      </div>
    </div>
  );
}
