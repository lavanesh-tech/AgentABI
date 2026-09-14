import { Badge } from "@/components/ui/primitives";
import type { RiskDecision } from "@/types/api";

const TONE: Record<RiskDecision, "pass" | "warn" | "block"> = {
  PASS: "pass",
  WARN: "warn",
  BLOCK: "block",
};

export function RiskDecisionBadge({ decision, large }: { decision: RiskDecision; large?: boolean }) {
  return (
    <span
      className={
        large
          ? `inline-flex items-center rounded-md px-3 py-1 text-lg font-bold ring-1 ring-inset ${
              decision === "PASS"
                ? "bg-pass/10 text-pass ring-pass/30"
                : decision === "WARN"
                  ? "bg-warn/10 text-warn ring-warn/30"
                  : "bg-block/10 text-block ring-block/30"
            }`
          : undefined
      }
    >
      {large ? decision : <Badge tone={TONE[decision]}>{decision}</Badge>}
    </span>
  );
}
