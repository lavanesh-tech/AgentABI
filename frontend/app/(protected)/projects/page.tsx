"use client";

import { useState } from "react";
import Link from "next/link";
import { useCreateProject, useProjects } from "@/features/projects/hooks";
import { useAuth } from "@/features/auth/AuthProvider";
import { hasPermission } from "@/lib/permissions";
import { Button, Card, CardHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { friendlyErrorMessage } from "@/lib/api-client";

export default function ProjectsPage() {
  const { user } = useAuth();
  const projectsQuery = useProjects();
  const createProject = useCreateProject();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const canCreate = hasPermission(user?.role ?? null, "project:create");

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="text-lg font-semibold text-ink">Projects</h1>

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
                className="rounded border border-border bg-surface px-2 py-1 text-sm text-ink"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-muted">
              Slug
              <input
                className="rounded border border-border bg-surface px-2 py-1 text-sm text-ink"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                required
              />
            </label>
            <Button type="submit" disabled={createProject.isPending}>
              {createProject.isPending ? "Creating…" : "Create"}
            </Button>
            {createProject.isError && (
              <p className="w-full text-xs text-block">{friendlyErrorMessage(createProject.error)}</p>
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
          emptyMessage="No projects yet."
        >
          {(data) => (
            <ul className="divide-y divide-border">
              {data.items.map((project) => (
                <li key={project.id}>
                  <Link
                    href={`/projects/${project.id}`}
                    className="flex items-center justify-between px-4 py-3 hover:bg-surface-sunken"
                  >
                    <span className="text-sm font-medium text-ink">{project.name}</span>
                    <span className="text-xs text-ink-faint">{project.slug}</span>
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
