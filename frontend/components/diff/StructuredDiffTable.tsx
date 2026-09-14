"use client";

import { Fragment, useState } from "react";
import { Badge } from "@/components/ui/primitives";
import type { Classification, Severity } from "@/types/api";

export interface StructuredDiffRow {
  id: string;
  changeType: string;
  path: string;
  before: unknown;
  after: unknown;
  severity: Severity;
  classification: Classification;
  message: string;
  evidence?: unknown;
}

const SEVERITY_TONE: Record<Severity, "neutral" | "warn" | "block"> = {
  info: "neutral",
  low: "neutral",
  medium: "warn",
  high: "block",
  critical: "block",
};

const CLASSIFICATION_TONE: Record<Classification, "pass" | "warn" | "block"> = {
  compatible: "pass",
  potentially_breaking: "warn",
  breaking: "block",
};

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/** Reusable structured-diff view (spec §15) shared by the Compatibility
 * and Differential screens: Change Type / Path / Before / After /
 * Severity / Evidence, with raw JSON only as an expandable secondary
 * view — never the primary display. */
export function StructuredDiffTable({ rows }: { rows: StructuredDiffRow[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (rows.length === 0) {
    return <p className="p-4 text-sm text-ink-muted">No changes recorded.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-border text-xs uppercase tracking-wide text-ink-faint">
          <tr>
            <th className="px-3 py-2 font-medium">Change type</th>
            <th className="px-3 py-2 font-medium">Path</th>
            <th className="px-3 py-2 font-medium">Before</th>
            <th className="px-3 py-2 font-medium">After</th>
            <th className="px-3 py-2 font-medium">Severity</th>
            <th className="px-3 py-2 font-medium">Classification</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row) => (
            <Fragment key={row.id}>
              <tr className="align-top hover:bg-surface-sunken/60">
                <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-ink">
                  {row.changeType}
                </td>
                <td className="px-3 py-2 font-mono text-xs text-ink-muted">{row.path}</td>
                <td className="max-w-xs truncate px-3 py-2 font-mono text-xs text-block">
                  {renderValue(row.before)}
                </td>
                <td className="max-w-xs truncate px-3 py-2 font-mono text-xs text-pass">
                  {renderValue(row.after)}
                </td>
                <td className="px-3 py-2">
                  <Badge tone={SEVERITY_TONE[row.severity]}>{row.severity}</Badge>
                </td>
                <td className="px-3 py-2">
                  <Badge tone={CLASSIFICATION_TONE[row.classification]}>
                    {row.classification.replace(/_/g, " ")}
                  </Badge>
                </td>
              </tr>
              <tr className="bg-surface-sunken/30">
                <td colSpan={6} className="px-3 py-2 text-xs text-ink-muted">
                  <p>{row.message}</p>
                  {row.evidence !== undefined && (
                    <button
                      type="button"
                      onClick={() => toggle(row.id)}
                      className="mt-1 text-accent hover:underline"
                    >
                      {expanded.has(row.id) ? "Hide raw evidence" : "Show raw evidence"}
                    </button>
                  )}
                  {expanded.has(row.id) && (
                    <pre className="mt-2 overflow-x-auto rounded bg-surface-sunken p-2 text-[11px] text-ink-muted">
                      {JSON.stringify(row.evidence, null, 2)}
                    </pre>
                  )}
                </td>
              </tr>
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
