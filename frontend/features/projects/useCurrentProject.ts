"use client";

/** Remembers the last-selected project across the flat, non-nested
 * routes (§7: /compatibility, /graph, /trajectories, ...). Per-viewer
 * convenience only — never load-bearing data, so plain localStorage is
 * fine here (this is a regular Next.js app, not an Artifact preview). */

import { useCallback, useSyncExternalStore } from "react";

const KEY = "agentabi_current_project_id";

const listeners = new Set<() => void>();

function getSnapshot(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function getServerSnapshot(): string | null {
  return null;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);

  function handleStorage(event: StorageEvent) {
    if (event.key === KEY) {
      listener();
    }
  }

  window.addEventListener("storage", handleStorage);

  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", handleStorage);
  };
}

function notifyListeners() {
  for (const listener of listeners) {
    listener();
  }
}

export function useCurrentProject(): [string | null, (id: string) => void] {
  const projectId = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot,
  );

  const update = useCallback((id: string) => {
    try {
      window.localStorage.setItem(KEY, id);
    } catch {
      // Best effort only; React still remains usable if storage is blocked.
    }

    notifyListeners();
  }, []);

  return [projectId, update];
}
