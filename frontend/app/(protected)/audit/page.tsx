"use client";

import { useAuditEvents } from "@/features/audit/hooks";
import { useAuth } from "@/features/auth/AuthProvider";
import { hasPermission } from "@/lib/permissions";
import { Card, CardHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { formatDateTime } from "@/lib/format";

export default function AuditPage() {
  const { user } = useAuth();
  const canRead = hasPermission(user?.role ?? null, "audit:read");
  const auditQuery = useAuditEvents();

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <h1 className="text-lg font-semibold text-ink">Audit Log</h1>

      {!canRead ? (
        <Card>
          <div className="p-6 text-sm text-ink-muted">
            Audit log access requires ADMIN or OWNER. Your role is {user?.role ?? "unknown"}.
          </div>
        </Card>
      ) : (
        <Card>
          <CardHeader title="Events" />
          <QueryState
            isLoading={auditQuery.isLoading}
            isError={auditQuery.isError}
            error={auditQuery.error}
            data={auditQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No audit events recorded yet."
          >
            {(data) => (
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border text-xs uppercase tracking-wide text-ink-faint">
                  <tr>
                    <th className="px-4 py-2 font-medium">Action</th>
                    <th className="px-4 py-2 font-medium">Resource</th>
                    <th className="px-4 py-2 font-medium">Actor</th>
                    <th className="px-4 py-2 font-medium">Request ID</th>
                    <th className="px-4 py-2 font-medium">When</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {data.items.map((e) => (
                    <tr key={e.id}>
                      <td className="px-4 py-2 font-mono text-xs text-ink">{e.action}</td>
                      <td className="px-4 py-2 text-xs text-ink-muted">
                        {e.resource_type ?? "—"} {e.resource_id ? `#${e.resource_id.slice(0, 8)}` : ""}
                      </td>
                      <td className="px-4 py-2 text-xs text-ink-muted">
                        {e.actor_user_id ? e.actor_user_id.slice(0, 8) : "system"}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs text-ink-faint">
                        {e.request_id ? e.request_id.slice(0, 8) : "—"}
                      </td>
                      <td className="px-4 py-2 text-xs text-ink-faint">{formatDateTime(e.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </QueryState>
        </Card>
      )}
    </div>
  );
}
