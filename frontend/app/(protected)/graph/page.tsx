"use client";

import { Suspense, useState } from "react";
import { ProjectGate } from "@/components/shell/ProjectGate";
import { useComponents } from "@/features/components/hooks";
import { useBlastRadius, useDependents } from "@/features/graph/hooks";
import { Card, CardHeader, PageHeader, StatTile } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { DependencyGraph } from "@/components/graph/DependencyGraph";
import { GraphIcon } from "@/components/ui/icons";

function GraphInner({ projectId }: { projectId: string }) {
  const componentsQuery = useComponents(projectId);
  const [componentId, setComponentId] = useState<string | null>(null);
  const dependentsQuery = useDependents(projectId, componentId ?? undefined);
  const blastRadiusQuery = useBlastRadius(projectId, componentId ?? undefined);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dependency Graph"
        description="Real dependency relationships from the graph service — never a fabricated layout."
      />

      <Card>
        <CardHeader
          title="Select a component"
          action={
            <QueryState
              isLoading={componentsQuery.isLoading}
              isError={componentsQuery.isError}
              error={componentsQuery.error}
              data={componentsQuery.data}
              emptyMessage="No components."
            >
              {(data) => (
                <select
                  aria-label="Component"
                  className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent"
                  value={componentId ?? ""}
                  onChange={(e) => setComponentId(e.target.value || null)}
                >
                  <option value="">Select…</option>
                  {data.items.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              )}
            </QueryState>
          }
        />
        {!componentId ? (
          <div className="flex flex-col items-center justify-center gap-1 px-6 py-16 text-center">
            <GraphIcon className="mb-1 h-8 w-8 text-ink-faint" />
            <p className="text-sm font-medium text-ink-muted">Select a component</p>
            <p className="text-xs text-ink-faint">Its dependency graph and blast radius will appear here.</p>
          </div>
        ) : (
          <QueryState
            isLoading={dependentsQuery.isLoading}
            isError={dependentsQuery.isError}
            error={dependentsQuery.error}
            data={dependentsQuery.data}
            isEmpty={(d) => d.length === 0}
            emptyMessage="No dependents recorded in the graph for this component"
            emptyHint="This component has no tracked dependents yet."
          >
            {(dependents) => (
              <div className="p-4">
                <DependencyGraph
                  centerComponentId={componentId}
                  centerLabel={
                    componentsQuery.data?.items.find((c) => c.id === componentId)?.name ?? componentId
                  }
                  dependents={dependents}
                  blastRadius={blastRadiusQuery.data}
                />
              </div>
            )}
          </QueryState>
        )}
      </Card>

      {componentId && (
        <Card>
          <CardHeader title="Blast radius" subtitle="Deterministic impact evidence from the graph service" />
          <QueryState
            isLoading={blastRadiusQuery.isLoading}
            isError={blastRadiusQuery.isError}
            error={blastRadiusQuery.error}
            data={blastRadiusQuery.data}
            emptyMessage="No blast radius evidence available."
          >
            {(br) => (
              <div className="grid grid-cols-3 gap-3 p-4">
                <StatTile label="Total affected" value={br.total_affected} />
                <StatTile label="Direct" value={br.direct_dependents.length} tone="warn" />
                <StatTile label="Transitive" value={br.transitive_dependents.length} tone="accent" />
              </div>
            )}
          </QueryState>
        </Card>
      )}
    </div>
  );
}

export default function GraphPage() {
  return (
    <Suspense>
      <ProjectGate>{(projectId) => <GraphInner projectId={projectId} />}</ProjectGate>
    </Suspense>
  );
}
