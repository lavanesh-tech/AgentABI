"use client";

import { Suspense, useState } from "react";
import { ProjectGate } from "@/components/shell/ProjectGate";
import { useRiskAssessment, useRiskAssessments } from "@/features/risk/hooks";
import { Card, CardHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { RiskDecisionBadge } from "@/components/risk/RiskDecisionBadge";
import { RiskScoreBar } from "@/components/risk/RiskScoreBar";
import { RiskRuleList } from "@/components/risk/RiskRuleList";
import { formatDateTime } from "@/lib/format";

function RiskInner({ projectId }: { projectId: string }) {
  const assessmentsQuery = useRiskAssessments(projectId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const assessmentQuery = useRiskAssessment(projectId, selectedId ?? undefined);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-ink">Deterministic Deployment Risk</h1>
        <p className="text-xs text-ink-faint">
          Computed entirely by AgentABI&apos;s versioned rule engine — never an AI-generated score.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
        <Card>
          <CardHeader title="Assessments" />
          <QueryState
            isLoading={assessmentsQuery.isLoading}
            isError={assessmentsQuery.isError}
            error={assessmentsQuery.error}
            data={assessmentsQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No risk assessments yet."
          >
            {(data) => (
              <ul className="max-h-[600px] divide-y divide-border overflow-y-auto">
                {data.items.map((a) => (
                  <li key={a.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(a.id)}
                      className={`flex w-full items-center justify-between px-4 py-3 text-left hover:bg-surface-sunken ${selectedId === a.id ? "bg-accent/5" : ""}`}
                    >
                      <RiskDecisionBadge decision={a.decision} />
                      <span className="font-mono text-xs text-ink-muted">{a.score}</span>
                      <span className="text-xs text-ink-faint">{formatDateTime(a.created_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </QueryState>
        </Card>

        <Card>
          <CardHeader title="Assessment detail" subtitle={selectedId ? undefined : "Select an assessment"} />
          {!selectedId ? (
            <p className="p-4 text-sm text-ink-muted">Select an assessment to see the deterministic reasoning trace.</p>
          ) : (
            <QueryState
              isLoading={assessmentQuery.isLoading}
              isError={assessmentQuery.isError}
              error={assessmentQuery.error}
              data={assessmentQuery.data}
              emptyMessage="Assessment not found."
            >
              {(assessment) => (
                <div>
                  <div className="flex items-center justify-between gap-4 border-b border-border px-4 py-4">
                    <div className="flex items-center gap-4">
                      <RiskDecisionBadge decision={assessment.decision} large />
                      <div>
                        <p className="font-mono text-2xl font-bold text-ink">{assessment.score}</p>
                        <p className="text-xs text-ink-faint">/ 100</p>
                      </div>
                    </div>
                    <div className="text-right text-xs text-ink-faint">
                      <p>Engine {assessment.risk_engine_version}</p>
                      <p>{formatDateTime(assessment.created_at)}</p>
                    </div>
                  </div>
                  <div className="px-4 py-4">
                    <RiskScoreBar score={assessment.score} hardBlock={assessment.hard_block} />
                  </div>
                  <div className="border-t border-border">
                    <p className="px-4 pt-3 text-xs font-semibold uppercase tracking-wide text-ink-faint">
                      Triggered rules
                    </p>
                    <RiskRuleList rules={assessment.rule_results} />
                  </div>
                </div>
              )}
            </QueryState>
          )}
        </Card>
      </div>
    </div>
  );
}

export default function RiskPage() {
  return (
    <Suspense>
      <ProjectGate>{(projectId) => <RiskInner projectId={projectId} />}</ProjectGate>
    </Suspense>
  );
}
