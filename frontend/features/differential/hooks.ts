import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { DifferentialReport, Paginated } from "@/types/api";

export function useDifferentialReports(projectId: string | undefined, page = 1) {
  return useQuery({
    queryKey: ["differential-reports", projectId, page],
    queryFn: () =>
      apiClient.get<Paginated<DifferentialReport>>(`/projects/${projectId}/differential/reports`, {
        page,
        page_size: 20,
      }),
    enabled: !!projectId,
  });
}

export function useDifferentialReport(projectId: string | undefined, reportId: string | undefined) {
  return useQuery({
    queryKey: ["differential-report", projectId, reportId],
    queryFn: () =>
      apiClient.get<DifferentialReport>(`/projects/${projectId}/differential/reports/${reportId}`),
    enabled: !!projectId && !!reportId,
  });
}

export function useCreateDifferentialReport(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { baseline_replay_id: string; candidate_replay_id: string }) =>
      apiClient.post<DifferentialReport>(`/projects/${projectId}/differential/reports`, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["differential-reports", projectId] });
    },
  });
}
