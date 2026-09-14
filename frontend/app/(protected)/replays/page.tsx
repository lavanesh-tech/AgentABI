"use client";

import { Suspense, useState } from "react";
import { ProjectGate } from "@/components/shell/ProjectGate";
import { useReplay, useReplaySteps, useReplays } from "@/features/replays/hooks";
import { Badge, Card, CardHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { formatDateTime, formatDuration } from "@/lib/format";

const STEP_KIND_LABEL: Record<string, string> = {
  reused_evidence: "Reused evidence",
  substituted_execution: "Substituted execution",
  provider_execution_required: "Provider required",
  skipped: "Skipped",
};

function ReplaysInner({ projectId }: { projectId: string }) {
  const replaysQuery = useReplays(projectId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const replayQuery = useReplay(projectId, selectedId ?? undefined);
  const stepsQuery = useReplaySteps(projectId, selectedId ?? undefined);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <h1 className="text-lg font-semibold text-ink">Replays</h1>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
        <Card>
          <CardHeader title="Runs" />
          <QueryState
            isLoading={replaysQuery.isLoading}
            isError={replaysQuery.isError}
            error={replaysQuery.error}
            data={replaysQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No replay runs recorded."
          >
            {(data) => (
              <ul className="max-h-[600px] divide-y divide-border overflow-y-auto">
                {data.items.map((r) => (
                  <li key={r.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(r.id)}
                      className={`block w-full px-4 py-3 text-left hover:bg-surface-sunken ${selectedId === r.id ? "bg-accent/5" : ""}`}
                    >
                      <div className="flex items-center justify-between">
                        <Badge tone={r.status === "completed" ? "pass" : r.status === "failed" ? "block" : "neutral"}>
                          {r.status}
                        </Badge>
                        <span className="text-xs text-ink-faint">{r.step_count} steps</span>
                      </div>
                      <p className="mt-1 text-xs text-ink-muted">
                        {r.started_at ? formatDateTime(r.started_at) : "not started"}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </QueryState>
        </Card>

        <Card>
          <CardHeader title="Steps" subtitle={selectedId ? undefined : "Select a replay run"} />
          {!selectedId ? (
            <p className="p-4 text-sm text-ink-muted">Select a replay run to see its steps.</p>
          ) : (
            <>
              <QueryState
                isLoading={replayQuery.isLoading}
                isError={replayQuery.isError}
                error={replayQuery.error}
                data={replayQuery.data}
                emptyMessage="Replay not found."
              >
                {(replay) => (
                  <div className="flex flex-wrap gap-4 border-b border-border px-4 py-3 text-xs text-ink-muted">
                    <span>Source trajectory: <code>{replay.source_trajectory_id}</code></span>
                    <span>Baseline: <code>{replay.baseline_component_version_id}</code></span>
                    <span>Candidate: <code>{replay.candidate_component_version_id}</code></span>
                  </div>
                )}
              </QueryState>
              <QueryState
                isLoading={stepsQuery.isLoading}
                isError={stepsQuery.isError}
                error={stepsQuery.error}
                data={stepsQuery.data}
                isEmpty={(d) => d.items.length === 0}
                emptyMessage="No steps recorded for this replay."
              >
                {(data) => (
                  <ol className="divide-y divide-border">
                    {data.items.map((step) => (
                      <li key={step.id} className="px-4 py-2 text-sm">
                        <div className="flex items-center justify-between">
                          <span>
                            <span className="font-mono text-xs text-ink-faint">#{step.sequence_number}</span>{" "}
                            <Badge>{STEP_KIND_LABEL[step.kind] ?? step.kind}</Badge>
                          </span>
                          <span className="text-xs text-ink-faint">{formatDuration(step.duration_ms)}</span>
                        </div>
                        <p className="mt-1 text-xs text-ink-muted">Status: {step.status}</p>
                        {step.justification && (
                          <p className="mt-1 text-xs text-ink-faint">{step.justification}</p>
                        )}
                      </li>
                    ))}
                  </ol>
                )}
              </QueryState>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}

export default function ReplaysPage() {
  return (
    <Suspense>
      <ProjectGate>{(projectId) => <ReplaysInner projectId={projectId} />}</ProjectGate>
    </Suspense>
  );
}
