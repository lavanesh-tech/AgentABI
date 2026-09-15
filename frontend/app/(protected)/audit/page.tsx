"use client";

import { useState } from "react";
import { useAuditEvents } from "@/features/audit/hooks";
import { useAuth } from "@/features/auth/AuthProvider";
import { hasPermission } from "@/lib/permissions";
import { Card, CardHeader, EmptyState, PageHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { formatDateTime } from "@/lib/format";
import { AuditIcon } from "@/components/ui/icons";

export default function AuditPage() {
  const { user } = useAuth();
  const canRead = hasPermission(user?.role ?? null, "audit:read");
  const auditQuery = useAuditEvents();
  const [filter, setFilter] = useState("");

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Security & operations"
        title="Audit Log"
        description="Organization-scoped activity: who did what, to which resource, and when."
      />

      {!canRead ? (
        <Card>
          <EmptyState
            icon={<AuditIcon className="h-8 w-8" />}
            message="Audit log access requires ADMIN or OWNER"
            hint={`Your role is ${user?.role ?? "unknown"}.`}
          />
        </Card>
      ) : (
        <Card>
          <CardHeader
            title="Events"
            action={
              <input
                type="search"
                aria-label="Filter events by action or resource"
                placeholder="Filter by action or resource…"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="w-56 rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent"
              />
            }
          />
          <QueryState
            isLoading={auditQuery.isLoading}
            isError={auditQuery.isError}
            error={auditQuery.error}
            data={auditQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No audit events recorded yet"
          >
            {(data) => {
              const needle = filter.trim().toLowerCase();
              const rows = needle
                ? data.items.filter(
                    (e) =>
                      e.action.toLowerCase().includes(needle) ||
                      (e.resource_type ?? "").toLowerCase().includes(needle),
                  )
                : data.items;
              if (rows.length === 0) {
                return <EmptyState message="No events match that filter" />;
              }
              return (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="border-b border-border text-xs uppercase tracking-wide text-ink-faint">
                      <tr>
                        <th className="whitespace-nowrap px-4 py-2 font-medium">Action</th>
                        <th className="whitespace-nowrap px-4 py-2 font-medium">Resource</th>
                        <th className="whitespace-nowrap px-4 py-2 font-medium">Actor</th>
                        <th className="whitespace-nowrap px-4 py-2 font-medium">Correlation</th>
                        <th className="whitespace-nowrap px-4 py-2 font-medium">Request ID</th>
                        <th className="whitespace-nowrap px-4 py-2 font-medium">When</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {rows.map((e) => (
                        <tr key={e.id} className="hover:bg-surface-sunken/60">
                          <td className="whitespace-nowrap px-4 py-2 font-mono text-xs text-ink">{e.action}</td>
                          <td className="whitespace-nowrap px-4 py-2 text-xs text-ink-muted">
                            {e.resource_type ?? "—"} {e.resource_id ? `#${e.resource_id.slice(0, 8)}` : ""}
                          </td>
                          <td className="whitespace-nowrap px-4 py-2 text-xs text-ink-muted">
                            {e.actor_user_id ? e.actor_user_id.slice(0, 8) : "system"}
                          </td>
                          <td className="whitespace-nowrap px-4 py-2 font-mono text-xs text-ink-faint">
                            {e.correlation_id ? e.correlation_id.slice(0, 8) : "—"}
                          </td>
                          <td className="whitespace-nowrap px-4 py-2 font-mono text-xs text-ink-faint">
                            {e.request_id ? e.request_id.slice(0, 8) : "—"}
                          </td>
                          <td className="whitespace-nowrap px-4 py-2 text-xs text-ink-faint">
                            {formatDateTime(e.created_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            }}
          </QueryState>
        </Card>
      )}
    </div>
  );
}
