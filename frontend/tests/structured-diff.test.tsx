import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StructuredDiffTable, type StructuredDiffRow } from "@/components/diff/StructuredDiffTable";

const row: StructuredDiffRow = {
  id: "c1",
  changeType: "REQUIRED_FIELD_ADDED",
  path: "$.input.amount",
  before: null,
  after: "required",
  severity: "critical",
  classification: "breaking",
  message: "A new required field was added.",
  evidence: { rule: "field_added" },
};

describe("StructuredDiffTable", () => {
  it("renders change type, path, before/after and severity/classification", () => {
    render(<StructuredDiffTable rows={[row]} />);
    expect(screen.getByText("REQUIRED_FIELD_ADDED")).toBeInTheDocument();
    expect(screen.getByText("$.input.amount")).toBeInTheDocument();
    expect(screen.getByText("critical")).toBeInTheDocument();
    expect(screen.getByText("breaking")).toBeInTheDocument();
  });

  it("keeps raw JSON evidence collapsed by default", () => {
    render(<StructuredDiffTable rows={[row]} />);
    expect(screen.queryByText(/"rule": "field_added"/)).not.toBeInTheDocument();
    expect(screen.getByText("Show raw evidence")).toBeInTheDocument();
  });

  it("shows an explicit empty state with no rows", () => {
    render(<StructuredDiffTable rows={[]} />);
    expect(screen.getByText(/No changes recorded/)).toBeInTheDocument();
  });
});
