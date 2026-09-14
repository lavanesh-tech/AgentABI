"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useProject } from "@/features/projects/hooks";
import { useComponents } from "@/features/components/hooks";
import { useCompatibilityScans } from "@/features/compatibility/hooks";
import { useRiskAssessments } from "@/features/risk/hooks";
import { useGitHubRepositories } from "@/features/github/hooks";
import { useCurrentProject } from "@/features/projects/useCurrentProject";
import { Card, CardHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { RiskDecisionBadge } from "@/components/risk/RiskDecisionBadge";
import { formatDateTime } from "@/lib/format";

export default function ProjectOverviewPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [, setCurrentProject] = useCurrentProject();

  useEffect(() => {
    if (projectId) setCurrentProject(projectId);
  }, [projectId, setCurrentProject]);

  const projectQuery = useProject(projectId);
  const componentsQuery = useComponents(projectId);
  const scansQuery = useCompatibilityScans(projectId);
  const riskQuery = useRiskAssessments(projectId);
  const githubQuery = useGitHubRepositories(projectId);

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <QueryState
        isLoading={projectQuery.isLoading}
        isError={projectQuery.isError}
        error={projectQuery.error}
        data={projectQuery.data}
        emptyMessage="Project not found."
      >
        {(project) => (
          <div>
            <h1 className="text-lg font-semibold text-ink">{project.name}</h1>
            <p className="text-xs text-ink-faint">{project.slug}</p>
          </div>
        )}
      </QueryState>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardHeader
            title="Components"
            action={
              <Link href={`/projects/${projectId}/components`} className="text-xs text-accent">
                View all
              </Link>
            }
          />
          <QueryState
            isLoading={componentsQuery.isLoading}
            isError={componentsQuery.isError}
            error={componentsQuery.error}
            data={componentsQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No components registered yet."
          >
            {(data) => (
              <ul className="divide-y divide-border">
                {data.items.slice(0, 5).map((c) => (
                  <li key={c.id} className="flex justify-between px-4 py-2 text-sm">
                    <span className="text-ink">{c.name}</span>
                    <span className="text-ink-faint">{c.component_type}</span>
                  </li>
                ))}
              </ul>
            )}
          </QueryState>
        </Card>

        <Card>
          <CardHeader
            title="Latest risk assessments"
            action={
              <Link href={`/risk?projectId=${projectId}`} className="text-xs text-accent">
                View all
              </Link>
            }
          />
          <QueryState
            isLoading={riskQuery.isLoading}
            isError={riskQuery.isError}
            error={riskQuery.error}
            data={riskQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No risk assessments yet."
          >
            {(data) => (
              <ul className="divide-y divide-border">
                {data.items.slice(0, 5).map((r) => (
                  <li key={r.id} className="flex items-center justify-between px-4 py-2 text-sm">
                    <RiskDecisionBadge decision={r.decision} />
                    <span className="font-mono text-xs text-ink-muted">{r.score}</span>
                    <span className="text-xs text-ink-faint">{formatDateTime(r.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </QueryState>
        </Card>

        <Card>
          <CardHeader
            title="Recent compatibility scans"
            action={
              <Link href={`/compatibility?projectId=${projectId}`} className="text-xs text-accent">
                View all
              </Link>
            }
          />
          <QueryState
            isLoading={scansQuery.isLoading}
            isError={scansQuery.isError}
            error={scansQuery.error}
            data={scansQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No compatibility scans yet."
          >
            {(data) => (
              <ul className="divide-y divide-border">
                {data.items.slice(0, 5).map((s) => (
                  <li key={s.id} className="flex items-center justify-between px-4 py-2 text-sm">
                    <span className="text-ink">{s.status}</span>
                    <span className="text-xs text-ink-faint">
                      {s.summary.total_changes} change(s)
                    </span>
                    <span className="text-xs text-ink-faint">{formatDateTime(s.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </QueryState>
        </Card>

        <Card>
          <CardHeader
            title="GitHub"
            action={
              <Link href={`/github?projectId=${projectId}`} className="text-xs text-accent">
                Manage
              </Link>
            }
          />
          <QueryState
            isLoading={githubQuery.isLoading}
            isError={githubQuery.isError}
            error={githubQuery.error}
            data={githubQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No GitHub repository is mapped to this project."
          >
            {(data) => (
              <ul className="divide-y divide-border">
                {data.items.map((m) => (
                  <li key={m.id} className="px-4 py-2 text-sm text-ink">
                    {m.github_repository_full_name}
                  </li>
                ))}
              </ul>
            )}
          </QueryState>
        </Card>
      </div>
    </div>
  );
}
