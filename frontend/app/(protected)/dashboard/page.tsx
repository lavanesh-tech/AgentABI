"use client";

import Link from "next/link";
import { useProjects } from "@/features/projects/hooks";
import { useAuth } from "@/features/auth/AuthProvider";
import { hasPermission } from "@/lib/permissions";
import { Badge, Button, Card, EmptyState, PageHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { formatRelative } from "@/lib/format";
import {
  AgentABIMark,
  CompatibilityIcon,
  GraphIcon,
  ProjectsIcon,
  ReplaysIcon,
  RiskIcon,
} from "@/components/ui/icons";

const WORKFLOW_STEPS = [
  { Icon: CompatibilityIcon, label: "Compatibility" },
  { Icon: GraphIcon, label: "Dependency graph" },
  { Icon: ReplaysIcon, label: "Replay & differential" },
  { Icon: RiskIcon, label: "Risk decision" },
];

/** Spec §5/§16: only real backend-supported info. No cross-project
 * aggregate endpoint exists, so this stays scoped to the project list
 * itself rather than fabricating global metrics or activity. */
export default function DashboardPage() {
  const { user } = useAuth();
  const projectsQuery = useProjects();
  const canCreate = hasPermission(user?.role ?? null, "project:create");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Your organization's projects. Open one to see compatibility, dependency, replay, and risk evidence."
      />

      <QueryState
        isLoading={projectsQuery.isLoading}
        isError={projectsQuery.isError}
        error={projectsQuery.error}
        data={projectsQuery.data}
        isEmpty={(d) => d.items.length === 0}
        emptyMessage="No projects yet"
        emptyHint="Create a project, register components, and AgentABI starts tracking compatibility and risk automatically."
      >
        {(data) =>
          data.items.length === 0 ? (
            <Card>
              <EmptyState
                icon={<AgentABIMark className="h-10 w-10" />}
                message="No projects yet"
                hint="Every AgentABI workflow starts with a project: register components, run a compatibility scan, and a deterministic PASS/WARN/BLOCK decision follows automatically."
                action={
                  canCreate ? (
                    <Button onClick={() => (window.location.href = "/projects")}>
                      Create your first project
                    </Button>
                  ) : (
                    <p className="text-xs text-ink-faint">
                      Ask an organization admin to create a project to get started.
                    </p>
                  )
                }
              />
              <div className="border-t border-border px-6 py-5">
                <p className="mb-3 text-center text-xs font-medium uppercase tracking-wide text-ink-faint">
                  How AgentABI evaluates a change
                </p>
                <div className="flex flex-wrap items-center justify-center gap-2">
                  {WORKFLOW_STEPS.map(({ Icon, label }, i) => (
                    <div key={label} className="flex items-center gap-2">
                      <div className="flex items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1.5">
                        <Icon className="h-3.5 w-3.5 text-ink-muted" />
                        <span className="text-xs text-ink-muted">{label}</span>
                      </div>
                      {i < WORKFLOW_STEPS.length - 1 && (
                        <span className="text-ink-faint" aria-hidden>
                          →
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </Card>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {data.items.map((project) => (
                <Link key={project.id} href={`/projects/${project.id}`} className="block">
                  <Card className="h-full p-4 transition-colors hover:border-accent/40">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent/10 text-accent">
                        <ProjectsIcon className="h-4 w-4" />
                      </div>
                      <Badge>{project.slug}</Badge>
                    </div>
                    <p className="mt-3 truncate text-sm font-semibold text-ink">{project.name}</p>
                    <p className="mt-1 text-xs text-ink-faint">
                      Updated {formatRelative(project.updated_at)}
                    </p>
                  </Card>
                </Link>
              ))}
            </div>
          )
        }
      </QueryState>
    </div>
  );
}
