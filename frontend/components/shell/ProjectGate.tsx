"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCurrentProject } from "@/features/projects/useCurrentProject";
import { Button, EmptyState } from "@/components/ui/primitives";
import { ProjectsIcon } from "@/components/ui/icons";

/** Every flat, project-scoped route (§7: /compatibility, /graph, ...)
 * needs a project in context. `?projectId=` from a link wins; falls
 * back to the last-selected project; otherwise prompts the user to
 * pick one rather than rendering a blank or broken screen. */
export function ProjectGate({ children }: { children: (projectId: string) => React.ReactNode }) {
  const params = useSearchParams();
  const [storedProjectId, setCurrentProject] = useCurrentProject();
  const projectId = params.get("projectId") ?? storedProjectId;

  useEffect(() => {
    const fromUrl = params.get("projectId");
    if (fromUrl && fromUrl !== storedProjectId) setCurrentProject(fromUrl);
  }, [params, storedProjectId, setCurrentProject]);

  if (!projectId) {
    return (
      <div className="mx-auto max-w-md">
        <EmptyState
          icon={<ProjectsIcon className="h-8 w-8" />}
          message="No project selected"
          hint="Choose a project to see its compatibility, dependency, replay, and risk evidence."
          action={
            <Link href="/projects">
              <Button variant="secondary">Go to projects</Button>
            </Link>
          }
        />
      </div>
    );
  }

  return <>{children(projectId)}</>;
}
