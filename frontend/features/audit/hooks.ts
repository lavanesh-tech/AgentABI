import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/features/auth/AuthProvider";
import type { AuditEvent, Paginated } from "@/types/api";

export function useAuditEvents(page = 1, action?: string) {
  const { user } = useAuth();
  const organizationId = user?.organization_id ?? null;
  return useQuery({
    queryKey: ["audit-events", organizationId, page, action],
    queryFn: () =>
      apiClient.get<Paginated<AuditEvent>>(`/organizations/${organizationId}/audit-events`, {
        page,
        page_size: 25,
        action,
      }),
    enabled: !!organizationId,
  });
}
