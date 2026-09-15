import { Badge } from "@/components/ui/primitives";
import type { RiskDecision } from "@/types/api";

const TONE: Record<RiskDecision, "pass" | "warn" | "block"> = {
  PASS: "pass",
  WARN: "warn",
  BLOCK: "block",
};

const LARGE_TONE_CLASSES: Record<RiskDecision, string> = {
  PASS: "bg-pass/10 text-pass ring-pass/30",
  WARN: "bg-warn/10 text-warn ring-warn/30",
  BLOCK: "bg-block/10 text-block ring-block/30",
};

/** The PASS/WARN/BLOCK decision — the single most important visual on the
 * Risk screen (spec §10). `large` renders the hero-scale presentation used
 * once per assessment; the default is the compact inline badge used in
 * lists (Project overview, GitHub PR history). Decision text is always
 * rendered as literal PASS/WARN/BLOCK — never conveyed by color alone. */
export function RiskDecisionBadge({ decision, large }: { decision: RiskDecision; large?: boolean }) {
  if (!large) {
    return <Badge tone={TONE[decision]}>{decision}</Badge>;
  }
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-2xl font-extrabold tracking-tight ring-2 ring-inset ${LARGE_TONE_CLASSES[decision]}`}
    >
      {decision}
    </span>
  );
}
