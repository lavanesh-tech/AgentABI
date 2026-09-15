"use client";

import { Suspense, useState } from "react";
import clsx from "clsx";
import { ProjectGate } from "@/components/shell/ProjectGate";
import { useCompatibilityScan, useCompatibilityScans, useExplainScan } from "@/features/compatibility/hooks";
import { Badge, Button, Card, CardHeader, PageHeader, StatTile } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { StructuredDiffTable, type StructuredDiffRow } from "@/components/diff/StructuredDiffTable";
import { formatDateTime, formatRelative } from "@/lib/format";
import { friendlyErrorMessage } from "@/lib/api-client";
import type { CompatibilityStatus } from "@/types/api";

const STATUS_TONE: Record<string, "pass" | "warn" | "block"> = {
  compatible: "pass",
  warning: "warn",
  breaking: "block",
};

function CompatibilityInner({ projectId }: { projectId: string }) {
  const scansQuery = useCompatibilityScans(projectId);
  const [selectedScanId, setSelectedScanId] = useState<string | null>(null);
  const scanQuery = useCompatibilityScan(projectId, selectedScanId ?? undefined);
  const explain = useExplainScan(projectId, selectedScanId ?? undefined);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Compatibility"
        description="Structured, deterministic diffs between a baseline and candidate component version."
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
        <Card>
          <CardHeader title="Scans" />
          <QueryState
            isLoading={scansQuery.isLoading}
            isError={scansQuery.isError}
            error={scansQuery.error}
            data={scansQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No compatibility scans yet"
            emptyHint="Scans appear here once a component version is compared against a baseline."
          >
            {(data) => (
              <ul className="max-h-[640px] divide-y divide-border overflow-y-auto">
                {data.items.map((scan) => (
                  <li key={scan.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedScanId(scan.id)}
                      aria-current={selectedScanId === scan.id}
                      className={clsx(
                        "block w-full px-4 py-3 text-left transition-colors hover:bg-surface-sunken",
                        selectedScanId === scan.id && "bg-accent/5",
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <Badge tone={STATUS_TONE[scan.status as CompatibilityStatus] ?? "neutral"}>
                          {scan.status}
                        </Badge>
                        <span className="shrink-0 text-xs text-ink-faint">{formatRelative(scan.created_at)}</span>
                      </div>
                      <p className="mt-1.5 text-xs text-ink-muted">
                        {scan.summary.total_changes} change(s)
                        {scan.summary.breaking_count > 0 && (
                          <span className="font-medium text-block"> · {scan.summary.breaking_count} breaking</span>
                        )}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </QueryState>
        </Card>

        <div className="min-w-0">
          {!selectedScanId ? (
            <Card>
              <div className="flex flex-col items-center justify-center gap-1 px-6 py-20 text-center">
                <p className="text-sm font-medium text-ink-muted">Select a scan</p>
                <p className="text-xs text-ink-faint">Choose one from the list to see what changed.</p>
              </div>
            </Card>
          ) : (
            <QueryState
              isLoading={scanQuery.isLoading}
              isError={scanQuery.isError}
              error={scanQuery.error}
              data={scanQuery.data}
              emptyMessage="Scan not found."
            >
              {(scan) => {
                const rows: StructuredDiffRow[] = scan.changes.map((c) => ({
                  id: c.id,
                  changeType: c.change_type,
                  path: c.path,
                  before: c.old_value,
                  after: c.new_value,
                  severity: c.severity,
                  classification: c.classification,
                  message: c.message,
                  evidence: c.evidence,
                }));
                return (
                  <div className="space-y-4">
                    {scan.summary.breaking_count > 0 && (
                      <div className="flex items-center gap-2 rounded-lg border-2 border-block/30 bg-block/[0.06] px-4 py-3">
                        <span className="text-sm font-semibold text-block">
                          {scan.summary.breaking_count} breaking change
                          {scan.summary.breaking_count === 1 ? "" : "s"} detected
                        </span>
                      </div>
                    )}

                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                      <StatTile label="Total changes" value={scan.summary.total_changes} />
                      <StatTile label="Compatible" value={scan.summary.compatible_count} tone="pass" />
                      <StatTile
                        label="Potentially breaking"
                        value={scan.summary.potentially_breaking_count}
                        tone="warn"
                      />
                      <StatTile label="Breaking" value={scan.summary.breaking_count} tone="block" />
                    </div>

                    <Card>
                      <CardHeader
                        title="Scan detail"
                        subtitle={
                          <span className="flex flex-wrap gap-x-3">
                            <span>Baseline: <code>{scan.baseline_version_id}</code></span>
                            <span>Candidate: <code>{scan.candidate_version_id}</code></span>
                          </span>
                        }
                        action={
                          <Button variant="secondary" onClick={() => explain.mutate()} disabled={explain.isPending}>
                            {explain.isPending ? "Generating…" : "Generate AI Explanation"}
                          </Button>
                        }
                      />
                      <div className="flex items-center gap-2 border-b border-border px-4 py-2 text-xs text-ink-muted">
                        Status:
                        <Badge tone={STATUS_TONE[scan.status as CompatibilityStatus] ?? "neutral"}>
                          {scan.status}
                        </Badge>
                        <span className="text-ink-faint">{formatDateTime(scan.created_at)}</span>
                      </div>
                      <StructuredDiffTable rows={rows} />

                      {explain.isError && (
                        <p role="alert" className="border-t border-border px-4 py-2 text-xs text-block">
                          {friendlyErrorMessage(explain.error)}
                        </p>
                      )}
                      {explain.data && (
                        <div className="border-t border-border bg-surface-sunken/40 px-4 py-3">
                          <p className="text-xs font-semibold uppercase tracking-wide text-ink-faint">
                            AI explanation of deterministic evidence — not part of the decision
                          </p>
                          <p className="mt-1 text-sm text-ink">{explain.data.summary}</p>
                          {explain.data.key_findings.length > 0 && (
                            <ul className="mt-2 list-disc pl-5 text-sm text-ink-muted">
                              {explain.data.key_findings.map((f, i) => (
                                <li key={i}>{f}</li>
                              ))}
                            </ul>
                          )}
                        </div>
                      )}
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

export default function CompatibilityPage() {
  return (
    <Suspense>
      <ProjectGate>{(projectId) => <CompatibilityInner projectId={projectId} />}</ProjectGate>
    </Suspense>
  );
}
