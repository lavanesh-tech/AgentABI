import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { Component, ComponentVersion, Paginated } from "@/types/api";

export function useComponents(projectId: string | undefined) {
  return useQuery({
    queryKey: ["components", projectId],
    queryFn: () =>
      apiClient.get<Paginated<Component>>(`/projects/${projectId}/components`, {
        page: 1,
        page_size: 100,
      }),
    enabled: !!projectId,
  });
}

export function useComponent(projectId: string | undefined, componentId: string | undefined) {
  return useQuery({
    queryKey: ["component", projectId, componentId],
    queryFn: () => apiClient.get<Component>(`/projects/${projectId}/components/${componentId}`),
    enabled: !!projectId && !!componentId,
  });
}

export function useComponentVersions(
  projectId: string | undefined,
  componentId: string | undefined,
) {
  return useQuery({
    queryKey: ["component-versions", projectId, componentId],
    queryFn: () =>
      apiClient.get<Paginated<ComponentVersion>>(
        `/projects/${projectId}/components/${componentId}/versions`,
        { page: 1, page_size: 100 },
      ),
    enabled: !!projectId && !!componentId,
  });
}

export function useCreateComponent(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      component_type: string;
      name: string;
      slug: string;
      description?: string;
    }) => apiClient.post<Component>(`/projects/${projectId}/components`, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["components", projectId] });
    },
  });
}
