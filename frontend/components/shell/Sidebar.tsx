"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import { useCurrentProject } from "@/features/projects/useCurrentProject";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/projects", label: "Projects" },
];

const PROJECT_NAV = [
  { key: "components", label: "Components" },
  { key: "compatibility", label: "Compatibility" },
  { key: "graph", label: "Dependency Graph" },
  { key: "trajectories", label: "Trajectories" },
  { key: "replays", label: "Replays" },
  { key: "differential", label: "Differential" },
  { key: "risk", label: "Risk" },
  { key: "github", label: "GitHub" },
  { key: "audit", label: "Audit" },
];

export function Sidebar() {
  const pathname = usePathname();
  const [projectId] = useCurrentProject();

  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex h-14 items-center border-b border-border px-4">
        <span className="text-sm font-bold tracking-tight text-ink">AgentABI</span>
      </div>
      <nav className="flex-1 space-y-4 overflow-y-auto px-2 py-4">
        <div className="space-y-0.5">
          {NAV.map((item) => (
            <SidebarLink key={item.href} href={item.href} active={pathname === item.href}>
              {item.label}
            </SidebarLink>
          ))}
        </div>
        <div>
          <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
            Current project
          </p>
          <div className="space-y-0.5">
            {PROJECT_NAV.map((item) => {
              const href = projectId
                ? item.key === "components"
                  ? `/projects/${projectId}/components`
                  : `/${item.key}?projectId=${projectId}`
                : "/projects";
              const active =
                pathname === href.split("?")[0] || pathname.startsWith(`/${item.key}`);
              return (
                <SidebarLink key={item.key} href={href} active={active} disabled={!projectId}>
                  {item.label}
                </SidebarLink>
              );
            })}
          </div>
        </div>
      </nav>
    </aside>
  );
}

function SidebarLink({
  href,
  active,
  disabled,
  children,
}: {
  href: string;
  active: boolean;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  if (disabled) {
    return (
      <span className="block cursor-not-allowed rounded px-2 py-1.5 text-sm text-ink-faint">
        {children}
      </span>
    );
  }
  return (
    <Link
      href={href}
      className={clsx(
        "block rounded px-2 py-1.5 text-sm transition-colors",
        active ? "bg-accent/10 font-medium text-accent" : "text-ink-muted hover:bg-surface-sunken hover:text-ink",
      )}
    >
      {children}
    </Link>
  );
}
