import { Badge } from "@/components/ui/primitives";
import type { RiskRuleResult } from "@/types/api";

/** Per-rule deterministic reasoning trace (spec §23 — "a major
 * differentiator of AgentABI"). */
export function RiskRuleList({ rules }: { rules: RiskRuleResult[] }) {
  if (rules.length === 0) {
    return <p className="p-4 text-sm text-ink-muted">No rules were triggered.</p>;
  }
  return (
    <ul className="divide-y divide-border">
      {rules.map((rule) => (
        <li key={rule.id} className="flex items-start justify-between gap-4 px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <code className="text-xs font-medium text-ink">{rule.rule_id}</code>
              <Badge>{rule.category}</Badge>
              {rule.hard_block && <Badge tone="block">hard block</Badge>}
            </div>
            <p className="mt-1 text-sm text-ink-muted">{rule.description}</p>
            {rule.evidence_refs.length > 0 && (
              <p className="mt-1 truncate text-xs text-ink-faint">
                Evidence: {rule.evidence_refs.join(", ")}
              </p>
            )}
          </div>
          <span
            className={
              "shrink-0 font-mono text-sm font-semibold " +
              (rule.score_delta > 0 ? "text-block" : rule.score_delta < 0 ? "text-pass" : "text-ink-muted")
            }
          >
            {rule.score_delta > 0 ? "+" : ""}
            {rule.score_delta}
          </span>
        </li>
      ))}
    </ul>
  );
}
