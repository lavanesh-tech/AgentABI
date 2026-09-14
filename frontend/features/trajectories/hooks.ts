import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { Paginated, Trajectory, TrajectoryEvent } from "@/types/api";

export function useTrajectories(projectId: string | undefined, page = 1) {
  return useQuery({
    queryKey: ["trajectories", projectId, page],
    queryFn: () =>
      apiClient.get<Paginated<Trajectory>>(`/projects/${projectId}/trajectories`, {
        page,
        page_size: 20,
      }),
    enabled: !!projectId,
  });
}

export function useTrajectory(projectId: string | undefined, trajectoryId: string | undefined) {
  return useQuery({
    queryKey: ["trajectory", projectId, trajectoryId],
    queryFn: () => apiClient.get<Trajectory>(`/projects/${projectId}/trajectories/${trajectoryId}`),
    enabled: !!projectId && !!trajectoryId,
  });
}

export function useTrajectoryEvents(
  projectId: string | undefined,
  trajectoryId: string | undefined,
  page = 1,
) {
  return useQuery({
    queryKey: ["trajectory-events", projectId, trajectoryId, page],
    queryFn: () =>
      apiClient.get<Paginated<TrajectoryEvent>>(
        `/projects/${projectId}/trajectories/${trajectoryId}/events`,
        { page, page_size: 50 },
      ),
    enabled: !!projectId && !!trajectoryId,
  });
}
