"use client";

import { useAuth } from "@/features/auth/AuthProvider";
import { Button } from "@/components/ui/primitives";

export function Header() {
  const { user, logout } = useAuth();
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface px-4">
      <div />
      <div className="flex items-center gap-3">
        {user && (
          <>
            <span className="text-xs text-ink-muted">{user.email}</span>
            {user.role && (
              <span className="rounded bg-surface-sunken px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-ink-faint">
                {user.role}
              </span>
            )}
            <Button variant="ghost" onClick={logout}>
              Sign out
            </Button>
          </>
        )}
      </div>
    </header>
  );
}
