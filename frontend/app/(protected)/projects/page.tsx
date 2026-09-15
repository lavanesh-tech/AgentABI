"use client";

import { useState } from "react";
import Link from "next/link";
import { useCreateProject, useProjects } from "@/features/projects/hooks";
import { useAuth } from "@/features/auth/AuthProvider";
import { hasPermission } from "@/lib/permissions";
import { Badge, Button, Card, CardHeader, PageHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { friendlyErrorMessage } from "@/lib/api-client";
import { formatRelative } from "@/lib/format";
import { ProjectsIcon } from "@/components/ui/icons";

export default function ProjectsPage() {
  const { user } = useAuth();
  const projectsQuery = useProjects();
  const createProject = useCreateProject();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const canCreate = hasPermission(user?.role ?? null, "project:create");

  return (
    <div className="space-y-6">
      <PageHeader title="Projects" description="Everything AgentABI tracks is scoped to a project." />

      {canCreate && (
        <Card>
          <CardHeader title="Create a project" />
          <form
            className="flex flex-wrap items-end gap-3 p-4"
            onSubmit={(e) => {
              e.preventDefault();
              createProject.mutate(
                { name, slug },
                { onSuccess: () => { setName(""); setSlug(""); } },
              );
            }}
          >
            <label className="flex flex-col gap-1 text-xs text-ink-muted">
              Name
              <input
                className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-muted">
              Slug
              <input
                className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                required
              />
            </label>
            <Button type="submit" disabled={createProject.isPending}>
              {createProject.isPending ? "Creating…" : "Create"}
            </Button>
            {createProject.isError && (
              <p role="alert" className="w-full text-xs text-block">
                {friendlyErrorMessage(createProject.error)}
              </p>
            )}
          </form>
        </Card>
      )}

      <Card>
        <CardHeader title="All projects" />
        <QueryState
          isLoading={projectsQuery.isLoading}
          isError={projectsQuery.isError}
          error={projectsQuery.error}
          data={projectsQuery.data}
          isEmpty={(d) => d.items.length === 0}
          emptyMessage="No projects yet"
          emptyHint={canCreate ? "Use the form above to create one." : "Ask an organization admin to create one."}
        >
          {(data) => (
            <ul className="divide-y divide-border">
              {data.items.map((project) => (
                <li key={project.id}>
                  <Link
                    href={`/projects/${project.id}`}
                    className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-surface-sunken"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent/10 text-accent">
                        <ProjectsIcon className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-ink">{project.name}</p>
                        <Badge>{project.slug}</Badge>
                      </div>
                    </div>
                    <span className="shrink-0 text-xs text-ink-faint">
                      Updated {formatRelative(project.updated_at)}
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
