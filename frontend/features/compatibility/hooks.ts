import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type {
  CompatibilityScan,
  CompatibilityScanListItem,
  ExplanationResponse,
  Paginated,
  ScanChange,
} from "@/types/api";

export function useCompatibilityScans(projectId: string | undefined, page = 1) {
  return useQuery({
    queryKey: ["compatibility-scans", projectId, page],
    queryFn: () =>
      apiClient.get<Paginated<CompatibilityScanListItem>>(
        `/projects/${projectId}/compatibility/scans`,
        { page, page_size: 20 },
      ),
    enabled: !!projectId,
  });
}

export function useCompatibilityScan(projectId: string | undefined, scanId: string | undefined) {
  return useQuery({
    queryKey: ["compatibility-scan", projectId, scanId],
    queryFn: () =>
      apiClient.get<CompatibilityScan>(`/projects/${projectId}/compatibility/scans/${scanId}`),
    enabled: !!projectId && !!scanId,
  });
}

export function useScanChanges(projectId: string | undefined, scanId: string | undefined) {
  return useQuery({
    queryKey: ["compatibility-scan-changes", projectId, scanId],
    queryFn: () =>
      apiClient.get<ScanChange[]>(
        `/projects/${projectId}/compatibility/scans/${scanId}/changes`,
      ),
    enabled: !!projectId && !!scanId,
  });
}

export function useRunCompatibilityScan(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      component_id: string;
      baseline_version_id: string;
      candidate_version_id: string;
    }) => apiClient.post<CompatibilityScan>(`/projects/${projectId}/compatibility/scans`, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["compatibility-scans", projectId] });
    },
  });
}

/** §24: explicit, user-triggered only — never called on page load. */
export function useExplainScan(projectId: string | undefined, scanId: string | undefined) {
  return useMutation({
    mutationFn: () =>
      apiClient.post<ExplanationResponse>(
        `/projects/${projectId}/compatibility/scans/${scanId}/explain`,
      ),
  });
}
