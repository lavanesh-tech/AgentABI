import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskDecisionBadge } from "@/components/risk/RiskDecisionBadge";
import { RiskScoreBar } from "@/components/risk/RiskScoreBar";
import { RiskRuleList } from "@/components/risk/RiskRuleList";

describe("PASS/WARN/BLOCK rendering", () => {
  it.each([["PASS"], ["WARN"], ["BLOCK"]] as const)("renders the %s decision", (decision) => {
    render(<RiskDecisionBadge decision={decision} />);
    expect(screen.getByText(decision)).toBeInTheDocument();
  });

  it("shows the hard-block explanation only when hard_block is true", () => {
    const { rerender } = render(<RiskScoreBar score={20} hardBlock={false} />);
    expect(screen.queryByText(/forced by a hard-block rule/)).not.toBeInTheDocument();

    rerender(<RiskScoreBar score={20} hardBlock />);
    expect(screen.getByText(/forced by a hard-block rule/)).toBeInTheDocument();
  });
});

describe("rule contribution rendering", () => {
  it("renders each rule's id, score delta and hard-block flag", () => {
    render(
      <RiskRuleList
        rules={[
          {
            id: "r1",
            order_index: 0,
            rule_id: "BREAKING_FIELD_REMOVED",
            category: "compatibility",
            description: "A required field was removed",
            score_delta: 40,
            evidence_refs: ["scan-change-1"],
            hard_block: true,
          },
        ]}
      />,
    );
    expect(screen.getByText("BREAKING_FIELD_REMOVED")).toBeInTheDocument();
    expect(screen.getByText("+40")).toBeInTheDocument();
    expect(screen.getByText("hard block")).toBeInTheDocument();
  });

  it("shows an explicit empty state when no rules triggered", () => {
    render(<RiskRuleList rules={[]} />);
    expect(screen.getByText(/No rules were triggered/)).toBeInTheDocument();
  });
});
