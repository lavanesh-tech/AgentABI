import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { Paginated, RiskAssessment, RiskAssessmentListItem } from "@/types/api";

export function useRiskAssessments(projectId: string | undefined, page = 1) {
  return useQuery({
    queryKey: ["risk-assessments", projectId, page],
    queryFn: () =>
      apiClient.get<Paginated<RiskAssessmentListItem>>(`/projects/${projectId}/risk/assessments`, {
        page,
        page_size: 20,
      }),
    enabled: !!projectId,
  });
}

export function useRiskAssessment(projectId: string | undefined, assessmentId: string | undefined) {
  return useQuery({
    queryKey: ["risk-assessment", projectId, assessmentId],
    queryFn: () =>
      apiClient.get<RiskAssessment>(`/projects/${projectId}/risk/assessments/${assessmentId}`),
    enabled: !!projectId && !!assessmentId,
  });
}

export function useCreateRiskAssessment(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      compatibility_scan_id?: string;
      differential_report_id?: string;
    }) => apiClient.post<RiskAssessment>(`/projects/${projectId}/risk/assessments`, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["risk-assessments", projectId] });
    },
  });
}
