"use client";

import { useMemo } from "react";
import ReactFlow, { Background, Controls, type Edge, type Node, MarkerType } from "reactflow";
import "reactflow/dist/style.css";
import type { BlastRadiusResponse, DependencyEdge } from "@/types/api";

type ImpactTier = "changed" | "direct" | "transitive" | "unaffected";

const TIER_COLOR: Record<ImpactTier, string> = {
  changed: "#dc2626",
  direct: "#d97706",
  transitive: "#2563eb",
  unaffected: "#9ca3af",
};

/** Renders real Phase 4 graph data via React Flow (spec §16/§17).
 * Never fabricates a relationship — nodes/edges come directly from
 * the backend's dependents list and blast-radius response. */
export function DependencyGraph({
  centerComponentId,
  centerLabel,
  dependents,
  blastRadius,
}: {
  centerComponentId: string;
  centerLabel: string;
  dependents: DependencyEdge[];
  blastRadius: BlastRadiusResponse | undefined;
}) {
  const { nodes, edges } = useMemo(() => {
    const directIds = new Set(blastRadius?.direct_dependents.map((d) => d.component_id) ?? []);
    const transitiveIds = new Set(
      blastRadius?.transitive_dependents.map((d) => d.component_id) ?? [],
    );

    const tierOf = (id: string): ImpactTier => {
      if (id === centerComponentId) return "changed";
      if (directIds.has(id)) return "direct";
      if (transitiveIds.has(id)) return "transitive";
      return "unaffected";
    };

    const nodeList: Node[] = [
      {
        id: centerComponentId,
        position: { x: 0, y: 0 },
        data: { label: centerLabel },
        style: nodeStyle(tierOf(centerComponentId)),
      },
      ...dependents.map((dep, index) => ({
        id: dep.component_id,
        position: { x: 260, y: index * 90 },
        data: { label: `${dep.name} (${dep.relationship_type})` },
        style: nodeStyle(tierOf(dep.component_id)),
      })),
    ];

    const edgeList: Edge[] = dependents.map((dep) => ({
      id: `${dep.component_id}-${centerComponentId}`,
      source: dep.component_id,
      target: centerComponentId,
      label: dep.relationship_type,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { stroke: TIER_COLOR[tierOf(dep.component_id)] },
    }));

    return { nodes: nodeList, edges: edgeList };
  }, [centerComponentId, centerLabel, dependents, blastRadius]);

  if (nodes.length === 0) {
    return (
      <div className="flex h-[420px] w-full items-center justify-center rounded-md border border-border bg-surface text-sm text-ink-muted">
        No graph data to display.
      </div>
    );
  }

  return (
    <div className="w-full overflow-hidden rounded-md border border-border bg-surface">
      <div className="h-[420px] w-full sm:h-[520px]">
        <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }}>
          <Background gap={16} size={1} color="rgb(var(--border))" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <Legend />
    </div>
  );
}

function nodeStyle(tier: ImpactTier) {
  return {
    border: `2px solid ${TIER_COLOR[tier]}`,
    borderRadius: 6,
    padding: 8,
    fontSize: 12,
    // References the theme's own surface-raised token (a valid plain CSS
    // color) instead of a hardcoded "white" — the prior hardcoded value
    // rendered as a jarring white box in dark mode.
    background: "rgb(var(--surface-raised))",
    color: "rgb(var(--ink))",
  };
}

function Legend() {
  const entries: { tier: ImpactTier; label: string }[] = [
    { tier: "changed", label: "Changed" },
    { tier: "direct", label: "Direct impact" },
    { tier: "transitive", label: "Transitive impact" },
    { tier: "unaffected", label: "Unaffected" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-border px-3 py-2 text-xs text-ink-muted">
      {entries.map((entry) => (
        <span key={entry.tier} className="flex items-center gap-1.5">
          <span
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{ background: TIER_COLOR[entry.tier] }}
          />
          {entry.label}
        </span>
      ))}
    </div>
  );
}
