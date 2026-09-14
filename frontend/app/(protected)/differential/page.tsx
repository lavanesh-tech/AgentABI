"use client";

import { Suspense, useState } from "react";
import { ProjectGate } from "@/components/shell/ProjectGate";
import { useDifferentialReport, useDifferentialReports } from "@/features/differential/hooks";
import { Card, CardHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { StructuredDiffTable, type StructuredDiffRow } from "@/components/diff/StructuredDiffTable";
import { formatDateTime } from "@/lib/format";

function DifferentialInner({ projectId }: { projectId: string }) {
  const reportsQuery = useDifferentialReports(projectId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const reportQuery = useDifferentialReport(projectId, selectedId ?? undefined);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-ink">Differential Analysis</h1>
        <p className="text-xs text-ink-faint">
          Deterministic step alignment (Phase 10 analyzer) — never LLM/fuzzy alignment.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
        <Card>
          <CardHeader title="Reports" />
          <QueryState
            isLoading={reportsQuery.isLoading}
            isError={reportsQuery.isError}
            error={reportsQuery.error}
            data={reportsQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No differential reports yet."
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
                      <p className="text-xs text-ink-muted">
                        {r.summary.changed_steps} changed, {r.summary.new_failures} new failures
                      </p>
                      <p className="text-xs text-ink-faint">{formatDateTime(r.created_at)}</p>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </QueryState>
        </Card>

        <Card>
          <CardHeader title="Report detail" subtitle={selectedId ? undefined : "Select a report"} />
          {!selectedId ? (
            <p className="p-4 text-sm text-ink-muted">Select a differential report from the list.</p>
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
                  <div>
                    <div className="grid grid-cols-4 gap-2 border-b border-border px-4 py-3 text-center text-xs">
                      <Stat label="Matched" value={report.summary.matched_steps} />
                      <Stat label="Added" value={report.summary.added_steps} />
                      <Stat label="Removed" value={report.summary.removed_steps} />
                      <Stat label="New failures" value={report.summary.new_failures} tone="block" />
                    </div>
                    <StructuredDiffTable rows={rows} />
                  </div>
                );
              }}
            </QueryState>
          )}
        </Card>
      </div>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "block" }) {
  return (
    <div>
      <p className={`text-lg font-bold ${tone === "block" ? "text-block" : "text-ink"}`}>{value}</p>
      <p className="text-ink-faint">{label}</p>
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
