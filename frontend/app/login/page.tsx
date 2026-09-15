"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/features/auth/AuthProvider";
import { Button } from "@/components/ui/primitives";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import {
  AgentABIMark,
  CompatibilityIcon,
  GitHubIcon,
  GraphIcon,
  ReplaysIcon,
  RiskIcon,
} from "@/components/ui/icons";

const PIPELINE_STEPS = [
  {
    Icon: CompatibilityIcon,
    title: "Deterministic compatibility analysis",
    description: "Schema and config diffs between baseline and candidate, classified breaking vs. non-breaking.",
  },
  {
    Icon: GraphIcon,
    title: "Dependency-aware blast radius",
    description: "Traces direct and transitive dependents through the component graph before anything ships.",
  },
  {
    Icon: ReplaysIcon,
    title: "Replay and differential evidence",
    description: "Re-executes recorded trajectories against the candidate and compares step-by-step outcomes.",
  },
  {
    Icon: RiskIcon,
    title: "Deterministic PASS / WARN / BLOCK",
    description: "A rule-based risk engine — not a model — produces the final ship/no-ship decision.",
  },
];

export default function LoginPage() {
  const { isAuthenticated, isLoading, loginWithGitHub } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && isAuthenticated) router.replace("/dashboard");
  }, [isLoading, isAuthenticated, router]);

  return (
    <div className="flex min-h-screen flex-col bg-surface-sunken">
      <header className="flex h-14 shrink-0 items-center justify-between px-4 sm:px-6">
        <div className="flex items-center gap-2">
          <AgentABIMark className="h-5 w-5 text-accent" />
          <span className="text-sm font-bold tracking-tight text-ink">AgentABI</span>
        </div>
        <ThemeToggle />
      </header>

      <main className="flex flex-1 items-center justify-center px-4 py-8 sm:py-12">
        <div className="grid w-full max-w-4xl grid-cols-1 gap-10 lg:grid-cols-2 lg:gap-14">
          <div className="flex flex-col justify-center">
            <p className="text-xs font-semibold uppercase tracking-wide text-accent">
              Agent Compatibility &amp; Upgrade Intelligence
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
              Know whether an AI-agent change is safe before you ship it.
            </h1>
            <p className="mt-4 max-w-md text-sm leading-relaxed text-ink-muted">
              AgentABI evaluates every agent-system change through deterministic compatibility
              analysis, dependency-aware blast radius, and replay/differential evidence — then
              produces a single, explainable PASS, WARN, or BLOCK decision before it reaches
              production.
            </p>

            <dl className="mt-8 space-y-5">
              {PIPELINE_STEPS.map(({ Icon, title, description }) => (
                <div key={title} className="flex gap-3">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent/10 text-accent">
                    <Icon className="h-4 w-4" />
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-ink">{title}</dt>
                    <dd className="mt-0.5 text-xs text-ink-muted">{description}</dd>
                  </div>
                </div>
              ))}
            </dl>
          </div>

          <div className="flex items-center">
            <div className="w-full rounded-lg border border-border bg-surface-raised p-8 shadow-sm">
              <div className="flex flex-col items-center text-center">
                <AgentABIMark className="h-9 w-9 text-accent" />
                <h2 className="mt-3 text-lg font-semibold text-ink">Sign in to AgentABI</h2>
                <p className="mt-1 text-sm text-ink-muted">
                  Authenticate with the GitHub account connected to your organization.
                </p>
                <Button className="mt-6 w-full" onClick={loginWithGitHub}>
                  <GitHubIcon className="h-4 w-4" />
                  Continue with GitHub
                </Button>
                <p className="mt-4 text-xs text-ink-faint">
                  Access and permissions are determined by your organization&apos;s role
                  assignment after sign-in.
                </p>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
