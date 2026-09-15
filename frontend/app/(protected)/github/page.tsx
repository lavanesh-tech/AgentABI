"use client";

import { Suspense, useMemo, useState } from "react";
import { ProjectGate } from "@/components/shell/ProjectGate";
import { useCreateGitHubRepository, useDeleteGitHubRepository, useGitHubRepositories, usePRAnalyses } from "@/features/github/hooks";
import { useAuth } from "@/features/auth/AuthProvider";
import { hasPermission } from "@/lib/permissions";
import { Badge, Button, Card, CardHeader, PageHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { RiskDecisionBadge } from "@/components/risk/RiskDecisionBadge";
import { formatRelative, truncateSha } from "@/lib/format";
import { CompatibilityIcon, GitHubIcon, RiskIcon } from "@/components/ui/icons";

const STATUS_TONE: Record<string, "pass" | "warn" | "block" | "neutral"> = {
  completed: "pass",
  failed: "block",
  publish_failed: "warn",
  in_progress: "neutral",
  pending: "neutral",
};

const STATUS_LABEL: Record<string, string> = {
  completed: "Completed",
  failed: "Failed",
  publish_failed: "Check publish failed",
  in_progress: "Analyzing",
  pending: "Pending",
};

function PipelineExplainer() {
  const steps = [
    { icon: GitHubIcon, label: "Pull request opened" },
    { icon: CompatibilityIcon, label: "AgentABI analysis" },
    { icon: RiskIcon, label: "PASS / WARN / BLOCK" },
    { icon: GitHubIcon, label: "GitHub check published" },
  ];
  return (
    <Card padded className="flex flex-wrap items-center gap-2">
      {steps.map(({ icon: Icon, label }, i) => (
        <div key={label} className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-ink-muted">
            <Icon className="h-3.5 w-3.5" />
            {label}
          </div>
          {i < steps.length - 1 && (
            <span className="text-ink-faint" aria-hidden>
              →
            </span>
          )}
        </div>
      ))}
    </Card>
  );
}

function GitHubInner({ projectId }: { projectId: string }) {
  const { user } = useAuth();
  const canManage = hasPermission(user?.role ?? null, "github_integration:manage");
  const reposQuery = useGitHubRepositories(projectId);
  const createRepo = useCreateGitHubRepository(projectId);
  const deleteRepo = useDeleteGitHubRepository(projectId);
  const analysesQuery = usePRAnalyses(projectId);
  const [form, setForm] = useState({ github_repository_id: "", github_repository_full_name: "" });

  // §26: group by PR number so exact-SHA rows never look merged/ambiguous.
  const groupedByPr = useMemo(() => {
    const items = analysesQuery.data?.items ?? [];
    const groups = new Map<number, typeof items>();
    for (const a of items) {
      const list = groups.get(a.pull_request_number) ?? [];
      list.push(a);
      groups.set(a.pull_request_number, list);
    }
    return [...groups.entries()].sort((a, b) => b[0] - a[0]);
  }, [analysesQuery.data]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="GitHub Integration"
        description="Repository mapping and PR analysis history that back the automated status check."
      />

      <PipelineExplainer />

      <Card>
        <CardHeader title="Repository mapping" />
        <QueryState
          isLoading={reposQuery.isLoading}
          isError={reposQuery.isError}
          error={reposQuery.error}
          data={reposQuery.data}
          isEmpty={(d) => d.items.length === 0}
          emptyMessage="No GitHub repository is mapped to this project"
          emptyHint={canManage ? "Map one below to enable PR analysis." : "Ask a project admin to map one."}
        >
          {(data) => (
            <ul className="divide-y divide-border">
              {data.items.map((m) => (
                <li key={m.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                  <div className="flex min-w-0 items-center gap-2">
                    <GitHubIcon className="h-4 w-4 shrink-0 text-ink-faint" />
                    <div className="min-w-0">
                      <p className="truncate font-medium text-ink">{m.github_repository_full_name}</p>
                      <p className="text-xs text-ink-faint">
                        repo id {m.github_repository_id}
                        {m.baseline_version && ` · baseline ${m.baseline_version}`}
                      </p>
                    </div>
                  </div>
                  {canManage && (
                    <Button variant="danger" onClick={() => deleteRepo.mutate(m.id)}>
                      Remove
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </QueryState>
        {canManage && (
          <form
            className="flex flex-wrap items-end gap-3 border-t border-border p-4"
            onSubmit={(e) => {
              e.preventDefault();
              createRepo.mutate({
                github_repository_id: Number(form.github_repository_id),
                github_repository_full_name: form.github_repository_full_name,
              });
            }}
          >
            <label className="flex flex-col gap-1 text-xs text-ink-muted">
              GitHub repository ID
              <input
                type="number"
                className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent"
                value={form.github_repository_id}
                onChange={(e) => setForm((f) => ({ ...f, github_repository_id: e.target.value }))}
                required
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-muted">
              Full name (owner/repo)
              <input
                className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent"
                value={form.github_repository_full_name}
                onChange={(e) => setForm((f) => ({ ...f, github_repository_full_name: e.target.value }))}
                required
              />
            </label>
            <Button type="submit" disabled={createRepo.isPending}>
              {createRepo.isPending ? "Mapping…" : "Map repository"}
            </Button>
          </form>
        )}
      </Card>

      <Card>
        <CardHeader title="PR analysis history" subtitle="Grouped by PR number — exact SHA per row, never merged across commits" />
        <QueryState
          isLoading={analysesQuery.isLoading}
          isError={analysesQuery.isError}
          error={analysesQuery.error}
          data={analysesQuery.data}
          isEmpty={() => groupedByPr.length === 0}
          emptyMessage="No pull request analyses yet"
          emptyHint="Analyses appear here once AgentABI evaluates a pull request against a mapped repository."
        >
          {() => (
            <div className="divide-y divide-border">
              {groupedByPr.map(([prNumber, analyses]) => (
                <div key={prNumber} className="px-4 py-3">
                  <p className="text-sm font-semibold text-ink">PR #{prNumber}</p>
                  <ul className="mt-1.5 space-y-1.5">
                    {analyses.map((a) => (
                      <li key={a.id} className="flex flex-wrap items-center gap-2 text-xs">
                        <code className="text-ink-muted">{truncateSha(a.head_sha)}</code>
                        <Badge tone={STATUS_TONE[a.status] ?? "neutral"}>
                          {STATUS_LABEL[a.status] ?? a.status}
                        </Badge>
                        {a.decision && <RiskDecisionBadge decision={a.decision} />}
                        {a.status === "publish_failed" && a.publish_error && (
                          <span className="text-warn">{a.publish_error}</span>
                        )}
                        <span className="ml-auto shrink-0 text-ink-faint">{formatRelative(a.created_at)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </QueryState>
      </Card>
    </div>
  );
}

export default function GitHubPage() {
  return (
    <Suspense>
      <ProjectGate>{(projectId) => <GitHubInner projectId={projectId} />}</ProjectGate>
    </Suspense>
  );
}
