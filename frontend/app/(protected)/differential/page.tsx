"use client";

import { Suspense, useState } from "react";
import clsx from "clsx";
import { ProjectGate } from "@/components/shell/ProjectGate";
import { useDifferentialReport, useDifferentialReports } from "@/features/differential/hooks";
import { Card, CardHeader, PageHeader, StatTile } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { StructuredDiffTable, type StructuredDiffRow } from "@/components/diff/StructuredDiffTable";
import { formatRelative } from "@/lib/format";

function DifferentialInner({ projectId }: { projectId: string }) {
  const reportsQuery = useDifferentialReports(projectId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const reportQuery = useDifferentialReport(projectId, selectedId ?? undefined);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Differential Analysis"
        description="Deterministic step alignment between a baseline and candidate replay — never LLM/fuzzy alignment."
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
        <Card>
          <CardHeader title="Reports" />
          <QueryState
            isLoading={reportsQuery.isLoading}
            isError={reportsQuery.isError}
            error={reportsQuery.error}
            data={reportsQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No differential reports yet"
            emptyHint="Reports appear once a baseline and candidate replay are compared."
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
                      <p className="text-xs text-ink-muted">
                        {r.summary.changed_steps} changed
                        {r.summary.new_failures > 0 && (
                          <span className="font-medium text-block"> · {r.summary.new_failures} new failures</span>
                        )}
                      </p>
                      <p className="mt-0.5 text-xs text-ink-faint">{formatRelative(r.created_at)}</p>
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
                <p className="text-sm font-medium text-ink-muted">Select a report</p>
                <p className="text-xs text-ink-faint">Baseline vs. candidate differences will appear here.</p>
              </div>
            </Card>
          ) : (
            <QueryState
              isLoading={reportQuery.isLoading}
              isError={reportQuery.isError}
              error={reportQuery.error}
              data={reportQuery.data}
              emptyMessage="Report not found."
            >
              {(report) => {
                const rows: StructuredDiffRow[] = report.changes.map((c) => ({
                  id: c.id,
                  changeType: c.difference_types.join(", ") || "unchanged",
                  path: c.sequence_number !== null ? `step[${c.sequence_number}]` : "—",
                  before: c.baseline_status,
                  after: c.candidate_status,
                  severity: c.error_difference ? "high" : "low",
                  classification: c.error_difference ? "breaking" : "compatible",
                  message: `Alignment: ${c.alignment_method}${
                    c.latency_delta_ms !== null ? ` · latency Δ ${c.latency_delta_ms}ms` : ""
                  }`,
                  evidence: { output_differences: c.output_differences, error_difference: c.error_difference },
                }));
                return (
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                      <StatTile label="Matched" value={report.summary.matched_steps} />
                      <StatTile label="Added" value={report.summary.added_steps} tone="accent" />
                      <StatTile label="Removed" value={report.summary.removed_steps} tone="warn" />
                      <StatTile label="New failures" value={report.summary.new_failures} tone="block" />
                    </div>
                    <Card>
                      <CardHeader
                        title="Aligned steps"
                        subtitle={`Analyzer ${report.analyzer_version}`}
                      />
                      <StructuredDiffTable rows={rows} />
                    </Card>
                  </div>
                );
              }}
            </QueryState>
          )}
        </div>
      </div>
    </div>
  );
}

export default function DifferentialPage() {
  return (
    <Suspense>
      <ProjectGate>{(projectId) => <DifferentialInner projectId={projectId} />}</ProjectGate>
    </Suspense>
  );
}
