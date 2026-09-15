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
import { Badge, Card, CardHeader, PageHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { RiskDecisionBadge } from "@/components/risk/RiskDecisionBadge";
import { formatDateTime, formatRelative } from "@/lib/format";
import {
  CompatibilityIcon,
  ComponentsIcon,
  DifferentialIcon,
  GitHubIcon,
  GraphIcon,
  ReplaysIcon,
  RiskIcon,
} from "@/components/ui/icons";

function WorkflowStrip({ projectId }: { projectId: string }) {
  const steps = [
    { href: `/projects/${projectId}/components`, label: "Components", Icon: ComponentsIcon },
    { href: `/compatibility?projectId=${projectId}`, label: "Compatibility", Icon: CompatibilityIcon },
    { href: `/graph?projectId=${projectId}`, label: "Dependency Graph", Icon: GraphIcon },
    { href: `/replays?projectId=${projectId}`, label: "Replay", Icon: ReplaysIcon },
    { href: `/differential?projectId=${projectId}`, label: "Differential", Icon: DifferentialIcon },
    { href: `/risk?projectId=${projectId}`, label: "Risk", Icon: RiskIcon },
    { href: `/github?projectId=${projectId}`, label: "GitHub Check", Icon: GitHubIcon },
  ];
  return (
    <Card padded>
      <p className="mb-3 text-xs font-medium uppercase tracking-wide text-ink-faint">
        Analysis workflow
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        {steps.map(({ href, label, Icon }, i) => (
          <div key={label} className="flex items-center gap-1.5">
            <Link
              href={href}
              className="flex items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-ink-muted transition-colors hover:border-accent/40 hover:text-ink"
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </Link>
            {i < steps.length - 1 && (
              <span className="text-ink-faint" aria-hidden>
                →
              </span>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

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
    <div className="space-y-6">
      <QueryState
        isLoading={projectQuery.isLoading}
        isError={projectQuery.isError}
        error={projectQuery.error}
        data={projectQuery.data}
        emptyMessage="Project not found."
      >
        {(project) => (
          <PageHeader eyebrow={project.slug} title={project.name} />
        )}
      </QueryState>

      <WorkflowStrip projectId={projectId} />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardHeader
            title="Components"
            action={
              <Link href={`/projects/${projectId}/components`} className="text-xs text-accent hover:underline">
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
            emptyMessage="No components registered yet"
            emptyHint="Register a component to start tracking its versions and compatibility."
          >
            {(data) => (
              <ul className="divide-y divide-border">
                {data.items.slice(0, 5).map((c) => (
                  <li key={c.id} className="flex items-center justify-between px-4 py-2 text-sm">
                    <span className="text-ink">{c.name}</span>
                    <Badge>{c.component_type}</Badge>
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
              <Link href={`/risk?projectId=${projectId}`} className="text-xs text-accent hover:underline">
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
            emptyMessage="No risk assessments yet"
            emptyHint="Run a compatibility scan and differential to produce a deterministic decision."
          >
            {(data) => (
              <ul className="divide-y divide-border">
                {data.items.slice(0, 5).map((r) => (
                  <li key={r.id} className="flex items-center justify-between px-4 py-2 text-sm">
                    <RiskDecisionBadge decision={r.decision} />
                    <span className="font-mono text-xs text-ink-muted">{r.score}</span>
                    <span className="text-xs text-ink-faint">{formatRelative(r.created_at)}</span>
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
              <Link href={`/compatibility?projectId=${projectId}`} className="text-xs text-accent hover:underline">
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
            emptyMessage="No compatibility scans yet"
          >
            {(data) => (
              <ul className="divide-y divide-border">
                {data.items.slice(0, 5).map((s) => (
                  <li key={s.id} className="flex items-center justify-between px-4 py-2 text-sm">
                    <Badge
                      tone={
                        s.status === "breaking" ? "block" : s.status === "warning" ? "warn" : "pass"
                      }
                    >
                      {s.status}
                    </Badge>
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
              <Link href={`/github?projectId=${projectId}`} className="text-xs text-accent hover:underline">
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
            emptyMessage="No GitHub repository mapped"
            emptyHint="Map a repository to enable PR analysis and automated checks."
          >
            {(data) => (
              <ul className="divide-y divide-border">
                {data.items.map((m) => (
                  <li key={m.id} className="flex items-center gap-2 px-4 py-2 text-sm text-ink">
                    <GitHubIcon className="h-3.5 w-3.5 text-ink-faint" />
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
