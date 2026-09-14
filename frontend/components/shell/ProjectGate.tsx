"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCurrentProject } from "@/features/projects/useCurrentProject";
import { EmptyState } from "@/components/ui/primitives";

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
        <EmptyState message="No project selected." hint="Choose a project to continue." />
        <div className="text-center">
          <Link href="/projects" className="text-sm text-accent hover:underline">
            Go to projects
          </Link>
        </div>
      </div>
    );
  }

  return <>{children(projectId)}</>;
}
