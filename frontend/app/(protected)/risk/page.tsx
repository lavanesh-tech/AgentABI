"use client";

import { Suspense, useState } from "react";
import clsx from "clsx";
import { ProjectGate } from "@/components/shell/ProjectGate";
import { useRiskAssessment, useRiskAssessments } from "@/features/risk/hooks";
import { Card, CardHeader, PageHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/QueryState";
import { RiskDecisionBadge } from "@/components/risk/RiskDecisionBadge";
import { RiskScoreBar } from "@/components/risk/RiskScoreBar";
import { RiskRuleList } from "@/components/risk/RiskRuleList";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { RiskDecision } from "@/types/api";

const HERO_TONE: Record<RiskDecision, string> = {
  PASS: "bg-pass/[0.06] border-pass/30",
  WARN: "bg-warn/[0.06] border-warn/30",
  BLOCK: "bg-block/[0.06] border-block/30",
};

function RiskInner({ projectId }: { projectId: string }) {
  const assessmentsQuery = useRiskAssessments(projectId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const assessmentQuery = useRiskAssessment(projectId, selectedId ?? undefined);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Deterministic decision"
        title="Deployment Risk"
        description="Computed entirely by AgentABI's versioned rule engine from compatibility and differential evidence — never an AI-generated score."
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
        <Card>
          <CardHeader title="Assessments" />
          <QueryState
            isLoading={assessmentsQuery.isLoading}
            isError={assessmentsQuery.isError}
            error={assessmentsQuery.error}
            data={assessmentsQuery.data}
            isEmpty={(d) => d.items.length === 0}
            emptyMessage="No risk assessments yet"
            emptyHint="Run a compatibility scan and differential report to produce one."
          >
            {(data) => (
              <ul className="max-h-[640px] divide-y divide-border overflow-y-auto">
                {data.items.map((a) => (
                  <li key={a.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(a.id)}
                      aria-current={selectedId === a.id}
                      className={clsx(
                        "flex w-full items-center justify-between gap-2 px-4 py-3 text-left transition-colors hover:bg-surface-sunken",
                        selectedId === a.id && "bg-accent/5",
                      )}
                    >
                      <RiskDecisionBadge decision={a.decision} />
                      <span className="font-mono text-xs text-ink-muted">{a.score}</span>
                      <span className="shrink-0 text-xs text-ink-faint">{formatRelative(a.created_at)}</span>
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
                <p className="text-sm font-medium text-ink-muted">Select an assessment</p>
                <p className="text-xs text-ink-faint">
                  Choose one from the list to see its full deterministic reasoning trace.
                </p>
              </div>
            </Card>
          ) : (
            <QueryState
              isLoading={assessmentQuery.isLoading}
              isError={assessmentQuery.isError}
              error={assessmentQuery.error}
              data={assessmentQuery.data}
              emptyMessage="Assessment not found."
            >
              {(assessment) => (
                <div className="space-y-4">
                  {/* Hero decision panel — the strongest visual hierarchy on
                      the page (spec §10). */}
                  <div className={clsx("rounded-lg border-2 p-6", HERO_TONE[assessment.decision])}>
                    <div className="flex flex-wrap items-center justify-between gap-4">
                      <div className="flex items-center gap-4">
                        <RiskDecisionBadge decision={assessment.decision} large />
                        <div>
                          <p className="font-mono text-3xl font-bold leading-none text-ink">
                            {assessment.score}
                            <span className="text-base font-medium text-ink-faint"> / 100</span>
                          </p>
                        </div>
                      </div>
                      <div className="text-right text-xs text-ink-faint">
                        <p>Risk engine {assessment.risk_engine_version}</p>
                        <p>{formatDateTime(assessment.created_at)}</p>
                      </div>
                    </div>
                    <div className="mt-5">
                      <RiskScoreBar score={assessment.score} hardBlock={assessment.hard_block} />
                    </div>
                    <p className="mt-4 text-xs text-ink-faint">
                      This decision was produced by AgentABI&apos;s deterministic risk engine from
                      compatibility and differential evidence below — it is not generated by AI.
                    </p>
                  </div>

                  <Card>
                    <CardHeader
                      title="Rule-by-rule contribution"
                      subtitle={`${assessment.rule_results.length} rule(s) evaluated`}
                    />
                    <RiskRuleList rules={assessment.rule_results} />
                  </Card>
                </div>
              )}
            </QueryState>
          )}
        </div>
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
