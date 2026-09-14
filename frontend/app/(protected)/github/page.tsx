"use client";

import { Suspense, useMemo, useState } from "react";
import { ProjectGate } from "@/components/shell/ProjectGate";
import { useCreateGitHubRepository, useDeleteGitHubRepository, useGitHubRepositories, usePRAnalyses } from "@/features/github/hooks";
import { useAuth } from "@/features/auth/AuthProvider";
import { hasPermission } from "@/lib/permissions";
import { Badge, Button, Card, CardHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { RiskDecisionBadge } from "@/components/risk/RiskDecisionBadge";
import { formatDateTime, truncateSha } from "@/lib/format";

const STATUS_TONE: Record<string, "pass" | "warn" | "block" | "neutral"> = {
  completed: "pass",
  failed: "block",
  publish_failed: "warn",
  in_progress: "neutral",
  pending: "neutral",
};

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
    <div className="mx-auto max-w-6xl space-y-6">
      <h1 className="text-lg font-semibold text-ink">GitHub Integration</h1>

      <Card>
        <CardHeader title="Repository mapping" />
        <QueryState
          isLoading={reposQuery.isLoading}
          isError={reposQuery.isError}
          error={reposQuery.error}
          data={reposQuery.data}
          isEmpty={(d) => d.items.length === 0}
          emptyMessage="No GitHub repository is mapped to this project."
        >
          {(data) => (
            <ul className="divide-y divide-border">
              {data.items.map((m) => (
                <li key={m.id} className="flex items-center justify-between px-4 py-3 text-sm">
                  <div>
                    <p className="font-medium text-ink">{m.github_repository_full_name}</p>
                    <p className="text-xs text-ink-faint">
                      repo id {m.github_repository_id}
                      {m.baseline_version && ` · baseline ${m.baseline_version}`}
                    </p>
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
                className="rounded border border-border bg-surface px-2 py-1 text-sm text-ink"
                value={form.github_repository_id}
                onChange={(e) => setForm((f) => ({ ...f, github_repository_id: e.target.value }))}
                required
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-muted">
              Full name (owner/repo)
              <input
                className="rounded border border-border bg-surface px-2 py-1 text-sm text-ink"
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
        <CardHeader title="PR analysis history" subtitle="Exact-SHA — never merged across commits" />
        <QueryState
          isLoading={analysesQuery.isLoading}
          isError={analysesQuery.isError}
          error={analysesQuery.error}
          data={analysesQuery.data}
          isEmpty={() => groupedByPr.length === 0}
          emptyMessage="No pull request analyses yet."
        >
          {() => (
            <div className="divide-y divide-border">
              {groupedByPr.map(([prNumber, analyses]) => (
                <div key={prNumber} className="px-4 py-3">
                  <p className="text-sm font-semibold text-ink">PR #{prNumber}</p>
                  <ul className="mt-1 space-y-1">
                    {analyses.map((a) => (
                      <li key={a.id} className="flex items-center justify-between text-xs">
                        <span className="font-mono text-ink-muted">{truncateSha(a.head_sha)}</span>
                        <Badge tone={STATUS_TONE[a.status] ?? "neutral"}>{a.status}</Badge>
                        {a.decision && <RiskDecisionBadge decision={a.decision} />}
                        <span className="text-ink-faint">{formatDateTime(a.created_at)}</span>
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
