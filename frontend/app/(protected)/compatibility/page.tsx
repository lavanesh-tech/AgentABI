"use client";

import { Suspense, useState } from "react";
import { ProjectGate } from "@/components/shell/ProjectGate";
import { useCompatibilityScan, useCompatibilityScans, useExplainScan } from "@/features/compatibility/hooks";
import { Badge, Button, Card, CardHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { StructuredDiffTable, type StructuredDiffRow } from "@/components/diff/StructuredDiffTable";
import { formatDateTime } from "@/lib/format";
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
    <div className="mx-auto max-w-6xl space-y-6">
      <h1 className="text-lg font-semibold text-ink">Compatibility</h1>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
        <Card>
          <CardHeader title="Scans" />
          <QueryState
            isLoading={scansQuery.isLoading}
            isError={scansQuery.isError}
            error={scansQuery.error}
            data={scansQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No compatibility scans yet."
          >
            {(data) => (
              <ul className="max-h-[600px] divide-y divide-border overflow-y-auto">
                {data.items.map((scan) => (
                  <li key={scan.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedScanId(scan.id)}
                      className={`block w-full px-4 py-3 text-left hover:bg-surface-sunken ${selectedScanId === scan.id ? "bg-accent/5" : ""}`}
                    >
                      <div className="flex items-center justify-between">
                        <Badge tone={STATUS_TONE[scan.status as CompatibilityStatus] ?? "neutral"}>
                          {scan.status}
                        </Badge>
                        <span className="text-xs text-ink-faint">{formatDateTime(scan.created_at)}</span>
                      </div>
                      <p className="mt-1 text-xs text-ink-muted">
                        {scan.summary.total_changes} change(s) — {scan.summary.breaking_count} breaking,{" "}
                        {scan.summary.potentially_breaking_count} potentially breaking
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </QueryState>
        </Card>

        <Card>
          <CardHeader
            title="Scan detail"
            subtitle={selectedScanId ? undefined : "Select a scan to see what changed"}
            action={
              selectedScanId && (
                <Button
                  variant="secondary"
                  onClick={() => explain.mutate()}
                  disabled={explain.isPending}
                >
                  {explain.isPending ? "Generating…" : "Generate AI Explanation"}
                </Button>
              )
            }
          />
          {!selectedScanId ? (
            <p className="p-4 text-sm text-ink-muted">Select a scan from the list.</p>
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
                  <div>
                    <div className="flex flex-wrap gap-4 border-b border-border px-4 py-3 text-xs text-ink-muted">
                      <span>Baseline: <code>{scan.baseline_version_id}</code></span>
                      <span>Candidate: <code>{scan.candidate_version_id}</code></span>
                      <span>Status: <Badge tone={STATUS_TONE[scan.status as CompatibilityStatus] ?? "neutral"}>{scan.status}</Badge></span>
                    </div>
                    <StructuredDiffTable rows={rows} />

                    {explain.isError && (
                      <p className="border-t border-border px-4 py-2 text-xs text-block">
                        {friendlyErrorMessage(explain.error)}
                      </p>
                    )}
                    {explain.data && (
                      <div className="border-t border-border px-4 py-3">
                        <p className="text-xs font-semibold uppercase tracking-wide text-ink-faint">
                          AI explanation of deterministic evidence
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

export default function CompatibilityPage() {
  return (
    <Suspense>
      <ProjectGate>{(projectId) => <CompatibilityInner projectId={projectId} />}</ProjectGate>
    </Suspense>
  );
}
