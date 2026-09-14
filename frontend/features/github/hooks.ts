import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { GitHubPRAnalysis, GitHubRepositoryMapping, Paginated } from "@/types/api";

export function useGitHubRepositories(projectId: string | undefined) {
  return useQuery({
    queryKey: ["github-repositories", projectId],
    queryFn: () =>
      apiClient.get<{ items: GitHubRepositoryMapping[] }>(
        `/projects/${projectId}/github/repositories`,
      ),
    enabled: !!projectId,
  });
}

export function useCreateGitHubRepository(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      github_repository_id: number;
      github_repository_full_name: string;
      github_installation_id?: number;
      component_id?: string;
      baseline_version?: string;
    }) =>
      apiClient.post<GitHubRepositoryMapping>(`/projects/${projectId}/github/repositories`, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["github-repositories", projectId] });
    },
  });
}

export function useDeleteGitHubRepository(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (mappingId: string) =>
      apiClient.delete(`/projects/${projectId}/github/repositories/${mappingId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["github-repositories", projectId] });
    },
  });
}

/** Backed by the Phase 14 read endpoint added to close the PR-analysis
 * history gap (see docs/DECISIONS.md) — exact-SHA history, never
 * merged across commits (spec §25/§26). */
export function usePRAnalyses(
  projectId: string | undefined,
  pullRequestNumber?: number,
  page = 1,
) {
  return useQuery({
    queryKey: ["github-pr-analyses", projectId, pullRequestNumber, page],
    queryFn: () =>
      apiClient.get<Paginated<GitHubPRAnalysis>>(`/projects/${projectId}/github/pr-analyses`, {
        pull_request_number: pullRequestNumber,
        page,
        page_size: 20,
      }),
    enabled: !!projectId,
  });
}
