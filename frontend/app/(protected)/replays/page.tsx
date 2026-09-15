"use client";

import { Suspense, useState } from "react";
import clsx from "clsx";
import { ProjectGate } from "@/components/shell/ProjectGate";
import { useReplay, useReplaySteps, useReplays } from "@/features/replays/hooks";
import { Badge, Card, CardHeader, PageHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { formatDuration, formatRelative } from "@/lib/format";
import type { StepKind } from "@/types/api";

const STEP_KIND_LABEL: Record<string, string> = {
  reused_evidence: "Reused evidence",
  substituted_execution: "Substituted execution",
  provider_execution_required: "Provider required",
  skipped: "Skipped",
};

// Investigation-tooling color coding: what AgentABI *did* with each step
// during replay, distinct from whether it succeeded (that's `status`).
const STEP_KIND_BORDER: Record<string, string> = {
  reused_evidence: "border-l-accent",
  substituted_execution: "border-l-warn",
  provider_execution_required: "border-l-ink-faint",
  skipped: "border-l-border",
};

function ReplaysInner({ projectId }: { projectId: string }) {
  const replaysQuery = useReplays(projectId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const replayQuery = useReplay(projectId, selectedId ?? undefined);
  const stepsQuery = useReplaySteps(projectId, selectedId ?? undefined);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Replays"
        description="Step-by-step re-execution against the candidate version — what was reused, substituted, or required a live provider call."
      />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
        <Card>
          <CardHeader title="Runs" />
          <QueryState
            isLoading={replaysQuery.isLoading}
            isError={replaysQuery.isError}
            error={replaysQuery.error}
            data={replaysQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No replay runs recorded"
            emptyHint="Replays appear once a trajectory is re-executed against a candidate version."
          >
            {(data) => (
              <ul className="max-h-[640px] divide-y divide-border overflow-y-auto">
                {data.items.map((r) => (
                  <li key={r.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(r.id)}
                      aria-current={selectedId === r.id}
                      className={clsx(
                        "block w-full px-4 py-3 text-left transition-colors hover:bg-surface-sunken",
                        selectedId === r.id && "bg-accent/5",
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <Badge tone={r.status === "completed" ? "pass" : r.status === "failed" ? "block" : "neutral"}>
                          {r.status}
                        </Badge>
                        <span className="text-xs text-ink-faint">{r.step_count} steps</span>
                      </div>
                      <p className="mt-1 text-xs text-ink-muted">
                        {r.started_at ? formatRelative(r.started_at) : "not started"}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </QueryState>
        </Card>

        <div className="min-w-0">
          {!selectedId ? (
            <Card>
              <div className="flex flex-col items-center justify-center gap-1 px-6 py-20 text-center">
                <p className="text-sm font-medium text-ink-muted">Select a replay run</p>
                <p className="text-xs text-ink-faint">Its step-by-step sequence will appear here.</p>
              </div>
            </Card>
          ) : (
            <Card>
              <QueryState
                isLoading={replayQuery.isLoading}
                isError={replayQuery.isError}
                error={replayQuery.error}
                data={replayQuery.data}
                emptyMessage="Replay not found."
              >
                {(replay) => (
                  <CardHeader
                    title="Steps"
                    subtitle={
                      <span className="flex flex-wrap gap-x-3">
                        <span>Baseline: <code>{replay.baseline_component_version_id}</code></span>
                        <span>Candidate: <code>{replay.candidate_component_version_id}</code></span>
                      </span>
                    }
                  />
                )}
              </QueryState>
              <QueryState
                isLoading={stepsQuery.isLoading}
                isError={stepsQuery.isError}
                error={stepsQuery.error}
                data={stepsQuery.data}
                isEmpty={(d) => d.items.length === 0}
                emptyMessage="No steps recorded for this replay"
              >
                {(data) => (
                  <ol className="divide-y divide-border">
                    {data.items.map((step) => {
                      const kindKey = step.kind as StepKind;
                      const statusTone =
                        step.status === "failed"
                          ? "block"
                          : step.status === "executed"
                            ? "pass"
                            : step.status === "provider_required"
                              ? "warn"
                              : "neutral";
                      return (
                        <li
                          key={step.id}
                          className={clsx(
                            "border-l-4 px-4 py-2.5",
                            STEP_KIND_BORDER[kindKey] ?? "border-l-border",
                          )}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="flex items-center gap-2">
                              <span className="font-mono text-xs text-ink-faint">
                                #{step.sequence_number}
                              </span>
                              <Badge>{STEP_KIND_LABEL[step.kind] ?? step.kind}</Badge>
                              <Badge tone={statusTone}>{step.status}</Badge>
                            </span>
                            <span className="shrink-0 text-xs text-ink-faint">
                              {formatDuration(step.duration_ms)}
                            </span>
                          </div>
                          {step.justification && (
                            <p className="mt-1 text-xs text-ink-muted">{step.justification}</p>
                          )}
                          {step.error != null && (
                            <p className="mt-1 text-xs text-block">
                              {typeof step.error === "string" ? step.error : JSON.stringify(step.error)}
                            </p>
                          )}
                        </li>
                      );
                    })}
                  </ol>
                )}
              </QueryState>
            </Card>
          )}
        </div>
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
