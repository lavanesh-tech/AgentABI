"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useComponents, useComponentVersions, useCreateComponent } from "@/features/components/hooks";
import { useAuth } from "@/features/auth/AuthProvider";
import { hasPermission } from "@/lib/permissions";
import { Badge, Button, Card, CardHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { formatDateTime } from "@/lib/format";

export default function ComponentsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { user } = useAuth();
  const componentsQuery = useComponents(projectId);
  const createComponent = useCreateComponent(projectId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", slug: "", component_type: "tool" });
  const canWrite = hasPermission(user?.role ?? null, "component:write");

  const versionsQuery = useComponentVersions(projectId, selectedId ?? undefined);

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <h1 className="text-lg font-semibold text-ink">Components</h1>

      {canWrite && (
        <Card>
          <CardHeader title="Register a component" />
          <form
            className="flex flex-wrap items-end gap-3 p-4"
            onSubmit={(e) => {
              e.preventDefault();
              createComponent.mutate(form, { onSuccess: () => setForm({ name: "", slug: "", component_type: "tool" }) });
            }}
          >
            <label className="flex flex-col gap-1 text-xs text-ink-muted">
              Name
              <input
                className="rounded border border-border bg-surface px-2 py-1 text-sm text-ink"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                required
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-muted">
              Slug
              <input
                className="rounded border border-border bg-surface px-2 py-1 text-sm text-ink"
                value={form.slug}
                onChange={(e) => setForm((f) => ({ ...f, slug: e.target.value }))}
                required
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-muted">
              Type
              <input
                className="rounded border border-border bg-surface px-2 py-1 text-sm text-ink"
                value={form.component_type}
                onChange={(e) => setForm((f) => ({ ...f, component_type: e.target.value }))}
                required
              />
            </label>
            <Button type="submit" disabled={createComponent.isPending}>
              {createComponent.isPending ? "Creating…" : "Register"}
            </Button>
          </form>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardHeader title="Registry" />
          <QueryState
            isLoading={componentsQuery.isLoading}
            isError={componentsQuery.isError}
            error={componentsQuery.error}
            data={componentsQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No components registered yet."
          >
            {(data) => (
              <ul className="divide-y divide-border">
                {data.items.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(c.id)}
                      className={`flex w-full items-center justify-between px-4 py-2 text-left text-sm hover:bg-surface-sunken ${selectedId === c.id ? "bg-accent/5" : ""}`}
                    >
                      <span>
                        <span className="font-medium text-ink">{c.name}</span>{" "}
                        <span className="text-xs text-ink-faint">{c.component_type}</span>
                      </span>
                      <Badge tone={c.status === "active" ? "pass" : "neutral"}>{c.status}</Badge>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </QueryState>
        </Card>

        <Card>
          <CardHeader title="Version history" subtitle={selectedId ? undefined : "Select a component"} />
          {selectedId ? (
            <QueryState
              isLoading={versionsQuery.isLoading}
              isError={versionsQuery.isError}
              error={versionsQuery.error}
              data={versionsQuery.data}
              isEmpty={(d) => d.items.length === 0}
              emptyMessage="No versions registered yet."
            >
              {(data) => (
                <ul className="divide-y divide-border">
                  {data.items.map((v) => (
                    <li key={v.id} className="px-4 py-2 text-sm">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-ink">{v.version}</span>
                        <span className="text-xs text-ink-faint">seq {v.sequence}</span>
                      </div>
                      <p className="text-xs text-ink-faint">{formatDateTime(v.created_at)}</p>
                    </li>
                  ))}
                </ul>
              )}
            </QueryState>
          ) : (
            <p className="p-4 text-sm text-ink-muted">Select a component to see its version history.</p>
          )}
        </Card>
      </div>
    </div>
  );
}
