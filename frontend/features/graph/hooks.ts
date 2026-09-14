import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { BlastRadiusResponse, DependencyEdge } from "@/types/api";

export function useDependencies(projectId: string | undefined, componentId: string | undefined) {
  return useQuery({
    queryKey: ["graph-dependencies", projectId, componentId],
    queryFn: () =>
      apiClient.get<DependencyEdge[]>(
        `/projects/${projectId}/components/${componentId}/graph/dependencies`,
      ),
    enabled: !!projectId && !!componentId,
  });
}

export function useDependents(projectId: string | undefined, componentId: string | undefined) {
  return useQuery({
    queryKey: ["graph-dependents", projectId, componentId],
    queryFn: () =>
      apiClient.get<DependencyEdge[]>(
        `/projects/${projectId}/components/${componentId}/graph/dependents`,
      ),
    enabled: !!projectId && !!componentId,
  });
}

export function useBlastRadius(
  projectId: string | undefined,
  componentId: string | undefined,
  maxDepth = 5,
) {
  return useQuery({
    queryKey: ["graph-blast-radius", projectId, componentId, maxDepth],
    queryFn: () =>
      apiClient.get<BlastRadiusResponse>(
        `/projects/${projectId}/components/${componentId}/graph/blast-radius`,
        { max_depth: maxDepth },
      ),
    enabled: !!projectId && !!componentId,
  });
}
