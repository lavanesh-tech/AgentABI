"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useAuth } from "@/features/auth/AuthProvider";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { LoadingBlock } from "@/components/ui/primitives";

/** Wraps every authenticated route (spec §6/§8). Redirects to /login
 * when unauthenticated; never renders protected content in the
 * meantime. Sidebar is a fixed column at md+ widths and an off-canvas
 * drawer below that (spec §3/§14 responsive behavior). */
export function ProtectedShell({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isLoading, isAuthenticated, router]);

  // Close the mobile drawer automatically on navigation.
  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  if (isLoading || !isAuthenticated) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface">
        <LoadingBlock />
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-surface-sunken">
      <div className="hidden md:block">
        <Sidebar />
      </div>

      {navOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-ink/30"
            onClick={() => setNavOpen(false)}
            aria-hidden
          />
          <div className="absolute inset-y-0 left-0">
            <Sidebar onNavigate={() => setNavOpen(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <Header onOpenNav={() => setNavOpen(true)} />
        <main className="flex-1 overflow-y-auto p-4 sm:p-6">
          <div className="mx-auto max-w-7xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
