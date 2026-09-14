import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { Paginated, Replay, ReplayStep } from "@/types/api";

export function useReplays(projectId: string | undefined, page = 1) {
  return useQuery({
    queryKey: ["replays", projectId, page],
    queryFn: () =>
      apiClient.get<Paginated<Replay>>(`/projects/${projectId}/replays`, { page, page_size: 20 }),
    enabled: !!projectId,
  });
}

export function useReplay(projectId: string | undefined, replayId: string | undefined) {
  return useQuery({
    queryKey: ["replay", projectId, replayId],
    queryFn: () => apiClient.get<Replay>(`/projects/${projectId}/replays/${replayId}`),
    enabled: !!projectId && !!replayId,
  });
}

export function useReplaySteps(
  projectId: string | undefined,
  replayId: string | undefined,
  page = 1,
) {
  return useQuery({
    queryKey: ["replay-steps", projectId, replayId, page],
    queryFn: () =>
      apiClient.get<Paginated<ReplayStep>>(`/projects/${projectId}/replays/${replayId}/steps`, {
        page,
        page_size: 50,
      }),
    enabled: !!projectId && !!replayId,
  });
}

export function useExecuteReplay(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (replayId: string) =>
      apiClient.post<Replay>(`/projects/${projectId}/replays/${replayId}/execute`),
    onSuccess: (_data, replayId) => {
      void queryClient.invalidateQueries({ queryKey: ["replay", projectId, replayId] });
      void queryClient.invalidateQueries({ queryKey: ["replays", projectId] });
    },
  });
}
