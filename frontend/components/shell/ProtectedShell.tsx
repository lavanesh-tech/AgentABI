"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/features/auth/AuthProvider";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { LoadingBlock } from "@/components/ui/primitives";

/** Wraps every authenticated route (spec §6/§8). Redirects to /login
 * when unauthenticated; never renders protected content in the
 * meantime. */
export function ProtectedShell({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading || !isAuthenticated) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface">
        <LoadingBlock />
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-surface-sunken">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
