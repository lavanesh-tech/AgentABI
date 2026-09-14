"use client";

/** Remembers the last-selected project across the flat, non-nested
 * routes (§7: /compatibility, /graph, /trajectories, ...). Per-viewer
 * convenience only — never load-bearing data, so plain localStorage is
 * fine here (this is a regular Next.js app, not an Artifact preview). */

import { useCallback, useEffect, useState } from "react";

const KEY = "agentabi_current_project_id";

export function useCurrentProject(): [string | null, (id: string) => void] {
  const [projectId, setProjectId] = useState<string | null>(null);

  useEffect(() => {
    try {
      setProjectId(window.localStorage.getItem(KEY));
    } catch {
      // ignore
    }
  }, []);

  const update = useCallback((id: string) => {
    setProjectId(id);
    try {
      window.localStorage.setItem(KEY, id);
    } catch {
      // ignore
    }
  }, []);

  return [projectId, update];
}
