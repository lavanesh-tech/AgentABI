"use client";

import { useState } from "react";
import { useAuth } from "@/features/auth/AuthProvider";
import { Button, IconButton } from "@/components/ui/primitives";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { MenuIcon, SignOutIcon } from "@/components/ui/icons";

export function Header({ onOpenNav }: { onOpenNav?: () => void }) {
  const { user, logout } = useAuth();
  const [confirmingSignOut, setConfirmingSignOut] = useState(false);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-surface px-3 sm:px-4">
      <div className="flex items-center gap-2">
        {onOpenNav && (
          <IconButton label="Open navigation" onClick={onOpenNav} className="md:hidden">
            <MenuIcon className="h-5 w-5" />
          </IconButton>
        )}
      </div>
      <div className="flex items-center gap-2 sm:gap-3">
        <ThemeToggle />
        {user && (
          <>
            <div className="hidden items-center gap-2 border-l border-border pl-3 sm:flex">
              <span className="max-w-[14rem] truncate text-xs text-ink-muted">{user.email}</span>
              {user.role && (
                <span className="rounded bg-surface-sunken px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-ink-faint">
                  {user.role}
                </span>
              )}
            </div>
            {confirmingSignOut ? (
              <div className="flex items-center gap-1.5">
                <span className="hidden text-xs text-ink-muted sm:inline">Sign out?</span>
                <Button
                  variant="danger"
                  onClick={() => {
                    setConfirmingSignOut(false);
                    logout();
                  }}
                >
                  Confirm
                </Button>
                <Button variant="ghost" onClick={() => setConfirmingSignOut(false)}>
                  Cancel
                </Button>
              </div>
            ) : (
              <IconButton label="Sign out" onClick={() => setConfirmingSignOut(true)}>
                <SignOutIcon className="h-4 w-4" />
              </IconButton>
            )}
          </>
        )}
      </div>
    </header>
  );
}
