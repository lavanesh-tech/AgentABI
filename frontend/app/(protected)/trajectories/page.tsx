"use client";

import { Suspense, useState } from "react";
import clsx from "clsx";
import { ProjectGate } from "@/components/shell/ProjectGate";
import { useTrajectories, useTrajectoryEvents } from "@/features/trajectories/hooks";
import { Badge, Card, CardHeader, PageHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { formatDateTime, formatDuration, formatRelative } from "@/lib/format";

function TrajectoriesInner({ projectId }: { projectId: string }) {
  const trajectoriesQuery = useTrajectories(projectId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const eventsQuery = useTrajectoryEvents(projectId, selectedId ?? undefined);
  const [expandedEvent, setExpandedEvent] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Trajectories"
        description="Recorded agent execution runs — the source material replays are built from."
      />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
        <Card>
          <CardHeader title="Runs" />
          <QueryState
            isLoading={trajectoriesQuery.isLoading}
            isError={trajectoriesQuery.isError}
            error={trajectoriesQuery.error}
            data={trajectoriesQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No trajectories recorded yet"
            emptyHint="Trajectories appear once agent runs are ingested for this project."
          >
            {(data) => (
              <ul className="max-h-[640px] divide-y divide-border overflow-y-auto">
                {data.items.map((t) => (
                  <li key={t.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(t.id)}
                      aria-current={selectedId === t.id}
                      className={clsx(
                        "block w-full px-4 py-3 text-left transition-colors hover:bg-surface-sunken",
                        selectedId === t.id && "bg-accent/5",
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <Badge tone={t.status === "completed" ? "pass" : t.status === "failed" ? "block" : "neutral"}>
                          {t.status}
                        </Badge>
                        <span className="text-xs text-ink-faint">{t.event_count} events</span>
                      </div>
                      <p className="mt-1 text-xs text-ink-muted">{formatRelative(t.started_at)}</p>
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
                <p className="text-sm font-medium text-ink-muted">Select a trajectory</p>
                <p className="text-xs text-ink-faint">Its ordered event timeline will appear here.</p>
              </div>
            </Card>
          ) : (
            <Card>
              <CardHeader title="Event timeline" />
              <QueryState
                isLoading={eventsQuery.isLoading}
                isError={eventsQuery.isError}
                error={eventsQuery.error}
                data={eventsQuery.data}
                isEmpty={(d) => d.items.length === 0}
                emptyMessage="No events recorded for this trajectory"
              >
                {(data) => (
                  <ol className="max-h-[640px] divide-y divide-border overflow-y-auto">
                    {data.items.map((event) => (
                      <li key={event.id} className="px-4 py-2.5">
                        <button
                          type="button"
                          onClick={() => setExpandedEvent(expandedEvent === event.id ? null : event.id)}
                          aria-expanded={expandedEvent === event.id}
                          className="flex w-full items-center justify-between gap-2 text-left text-sm"
                        >
                          <span className="min-w-0 truncate">
                            <span className="font-mono text-xs text-ink-faint">#{event.sequence_number}</span>{" "}
                            <span className="font-medium text-ink">{event.event_type}</span>
                          </span>
                          <span className="shrink-0 text-xs text-ink-faint">
                            {formatDuration(event.duration_ms)} · {formatDateTime(event.occurred_at)}
                          </span>
                        </button>
                        {expandedEvent === event.id && (
                          <div className="mt-2 space-y-1 text-xs text-ink-muted">
                            {event.payload_truncated && (
                              <p className="text-warn">Payload truncated (redacted summary shown)</p>
                            )}
                            <pre className="overflow-x-auto rounded bg-surface-sunken p-2">
                              {JSON.stringify({ input: event.input, output: event.output, error: event.error }, null, 2)}
                            </pre>
                          </div>
                        )}
                      </li>
                    ))}
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

export default function TrajectoriesPage() {
  return (
    <Suspense>
      <ProjectGate>{(projectId) => <TrajectoriesInner projectId={projectId} />}</ProjectGate>
    </Suspense>
  );
}
