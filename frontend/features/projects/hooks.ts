import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/features/auth/AuthProvider";
import type { Paginated, Project } from "@/types/api";

export function useProjects() {
  const { user } = useAuth();
  const organizationId = user?.organization_id ?? null;
  return useQuery({
    queryKey: ["projects", organizationId],
    queryFn: () =>
      apiClient.get<Paginated<Project>>(`/organizations/${organizationId}/projects`, {
        page: 1,
        page_size: 100,
      }),
    enabled: !!organizationId,
  });
}

export function useProject(projectId: string | undefined) {
  return useQuery({
    queryKey: ["project", projectId],
    queryFn: () => apiClient.get<Project>(`/projects/${projectId}`),
    enabled: !!projectId,
  });
}

export function useCreateProject() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const organizationId = user?.organization_id ?? null;
  return useMutation({
    mutationFn: (input: { name: string; slug: string }) =>
      apiClient.post<Project>(`/organizations/${organizationId}/projects`, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects", organizationId] });
    },
  });
}
