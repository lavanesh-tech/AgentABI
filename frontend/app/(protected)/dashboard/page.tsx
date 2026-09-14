"use client";

import Link from "next/link";
import { useProjects } from "@/features/projects/hooks";
import { Card, CardHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { formatDateTime } from "@/lib/format";

/** Spec §11: only real backend-supported info. No cross-project
 * aggregate endpoint exists, so this stays scoped to the project list
 * itself rather than fabricating global metrics. */
export default function DashboardPage() {
  const projectsQuery = useProjects();

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-ink">Dashboard</h1>
        <p className="text-sm text-ink-muted">
          Your organization&apos;s projects. Open one to see compatibility, risk, and deployment
          evidence.
        </p>
      </div>

      <Card>
        <CardHeader title="Projects" />
        <QueryState
          isLoading={projectsQuery.isLoading}
          isError={projectsQuery.isError}
          error={projectsQuery.error}
          data={projectsQuery.data}
          isEmpty={(d) => d.items.length === 0}
          emptyMessage="No projects yet."
          emptyHint="Create a project to start tracking compatibility and risk."
        >
          {(data) => (
            <ul className="divide-y divide-border">
              {data.items.map((project) => (
                <li key={project.id}>
                  <Link
                    href={`/projects/${project.id}`}
                    className="flex items-center justify-between px-4 py-3 hover:bg-surface-sunken"
                  >
                    <div>
                      <p className="text-sm font-medium text-ink">{project.name}</p>
                      <p className="text-xs text-ink-faint">{project.slug}</p>
                    </div>
                    <span className="text-xs text-ink-faint">
                      Updated {formatDateTime(project.updated_at)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </QueryState>
      </Card>
    </div>
  );
}
