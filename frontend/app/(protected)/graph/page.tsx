"use client";

import { Suspense, useState } from "react";
import { ProjectGate } from "@/components/shell/ProjectGate";
import { useComponents } from "@/features/components/hooks";
import { useBlastRadius, useDependents } from "@/features/graph/hooks";
import { Card, CardHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { DependencyGraph } from "@/components/graph/DependencyGraph";

function GraphInner({ projectId }: { projectId: string }) {
  const componentsQuery = useComponents(projectId);
  const [componentId, setComponentId] = useState<string | null>(null);
  const dependentsQuery = useDependents(projectId, componentId ?? undefined);
  const blastRadiusQuery = useBlastRadius(projectId, componentId ?? undefined);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <h1 className="text-lg font-semibold text-ink">Dependency Graph</h1>

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
                  className="rounded border border-border bg-surface px-2 py-1 text-sm text-ink"
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
          <p className="p-4 text-sm text-ink-muted">Select a component to view its dependency graph.</p>
        ) : (
          <QueryState
            isLoading={dependentsQuery.isLoading}
            isError={dependentsQuery.isError}
            error={dependentsQuery.error}
            data={dependentsQuery.data}
            isEmpty={(d) => d.length === 0}
            emptyMessage="No dependents recorded in the graph for this component."
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
              <div className="grid grid-cols-3 gap-4 p-4 text-center">
                <div>
                  <p className="text-2xl font-bold text-ink">{br.total_affected}</p>
                  <p className="text-xs text-ink-faint">Total affected</p>
                </div>
                <div>
                  <p className="text-2xl font-bold text-warn">{br.direct_dependents.length}</p>
                  <p className="text-xs text-ink-faint">Direct</p>
                </div>
                <div>
                  <p className="text-2xl font-bold text-accent">{br.transitive_dependents.length}</p>
                  <p className="text-xs text-ink-faint">Transitive</p>
                </div>
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
