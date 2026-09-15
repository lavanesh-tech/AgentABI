"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import { useCurrentProject } from "@/features/projects/useCurrentProject";
import { useProject } from "@/features/projects/hooks";
import { useAuth } from "@/features/auth/AuthProvider";
import { hasPermission } from "@/lib/permissions";
import {
  AgentABIMark,
  AuditIcon,
  CloseIcon,
  CompatibilityIcon,
  ComponentsIcon,
  DashboardIcon,
  DifferentialIcon,
  GitHubIcon,
  GraphIcon,
  ProjectsIcon,
  ReplaysIcon,
  RiskIcon,
  TrajectoriesIcon,
  type IconProps,
} from "@/components/ui/icons";
import type { ComponentType } from "react";

type NavItem = { href: string; label: string; Icon: ComponentType<IconProps> };
type ProjectNavItem = { key: string; label: string; Icon: ComponentType<IconProps> };

const OVERVIEW: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", Icon: DashboardIcon },
  { href: "/projects", label: "Projects", Icon: ProjectsIcon },
];

const ANALYSIS: ProjectNavItem[] = [
  { key: "components", label: "Components", Icon: ComponentsIcon },
  { key: "compatibility", label: "Compatibility", Icon: CompatibilityIcon },
  { key: "graph", label: "Dependency Graph", Icon: GraphIcon },
  { key: "trajectories", label: "Trajectories", Icon: TrajectoriesIcon },
  { key: "replays", label: "Replays", Icon: ReplaysIcon },
  { key: "differential", label: "Differential", Icon: DifferentialIcon },
  { key: "risk", label: "Risk", Icon: RiskIcon },
];

const INTEGRATIONS: ProjectNavItem[] = [{ key: "github", label: "GitHub", Icon: GitHubIcon }];

const OPERATIONS: ProjectNavItem[] = [{ key: "audit", label: "Audit", Icon: AuditIcon }];

function projectHref(key: string, projectId: string | null): string {
  if (!projectId) return "/projects";
  if (key === "components") return `/projects/${projectId}/components`;
  return `/${key}?projectId=${projectId}`;
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const [projectId] = useCurrentProject();
  const { user } = useAuth();
  const { data: currentProject } = useProject(projectId ?? undefined);

  // §3: "Do not display controls the backend would reject" — Audit is
  // ADMIN/OWNER-only server-side, so MEMBERs never see the link at all
  // rather than seeing it disabled.
  const canSeeAudit = hasPermission(user?.role ?? null, "audit:read");

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex h-14 items-center justify-between gap-2 border-b border-border px-4">
        <Link href="/dashboard" className="flex items-center gap-2 overflow-hidden" onClick={onNavigate}>
          <AgentABIMark className="h-5 w-5 shrink-0 text-accent" />
          <span className="truncate text-sm font-bold tracking-tight text-ink">AgentABI</span>
        </Link>
        {onNavigate && (
          <button
            type="button"
            onClick={onNavigate}
            aria-label="Close navigation"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-ink-muted hover:bg-surface-sunken md:hidden"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        )}
      </div>

      {projectId && (
        <div className="border-b border-border px-4 py-2.5">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
            Current project
          </p>
          <p className="mt-0.5 truncate text-sm font-medium text-ink">
            {currentProject?.name ?? "—"}
          </p>
        </div>
      )}

      <nav className="flex-1 space-y-5 overflow-y-auto px-2 py-4">
        <NavGroup label="Overview">
          {OVERVIEW.map((item) => (
            <SidebarLink
              key={item.href}
              href={item.href}
              active={pathname === item.href}
              Icon={item.Icon}
              onClick={onNavigate}
            >
              {item.label}
            </SidebarLink>
          ))}
        </NavGroup>

        <NavGroup label="Analysis">
          {ANALYSIS.map((item) => {
            const href = projectHref(item.key, projectId);
            const active = pathname.startsWith(`/${item.key}`);
            return (
              <SidebarLink
                key={item.key}
                href={href}
                active={active}
                disabled={!projectId}
                Icon={item.Icon}
                onClick={onNavigate}
              >
                {item.label}
              </SidebarLink>
            );
          })}
        </NavGroup>

        <NavGroup label="Integrations">
          {INTEGRATIONS.map((item) => {
            const href = projectHref(item.key, projectId);
            const active = pathname.startsWith(`/${item.key}`);
            return (
              <SidebarLink
                key={item.key}
                href={href}
                active={active}
                disabled={!projectId}
                Icon={item.Icon}
                onClick={onNavigate}
              >
                {item.label}
              </SidebarLink>
            );
          })}
        </NavGroup>

        {canSeeAudit && (
          <NavGroup label="Security & Operations">
            {OPERATIONS.map((item) => {
              const href = projectHref(item.key, projectId);
              const active = pathname.startsWith(`/${item.key}`);
              return (
                <SidebarLink
                  key={item.key}
                  href={href}
                  active={active}
                  disabled={!projectId}
                  Icon={item.Icon}
                  onClick={onNavigate}
                >
                  {item.label}
                </SidebarLink>
              );
            })}
          </NavGroup>
        )}
      </nav>
    </aside>
  );
}

function NavGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
        {label}
      </p>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function SidebarLink({
  href,
  active,
  disabled,
  children,
  Icon,
  onClick,
}: {
  href: string;
  active: boolean;
  disabled?: boolean;
  children: React.ReactNode;
  Icon: ComponentType<IconProps>;
  onClick?: () => void;
}) {
  if (disabled) {
    return (
      <span
        className="flex cursor-not-allowed items-center gap-2 rounded-md px-2 py-1.5 text-sm text-ink-faint"
        title="Select a project first"
      >
        <Icon className="h-4 w-4 shrink-0" />
        {children}
      </span>
    );
  }
  return (
    <Link
      href={href}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={clsx(
        "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
        active
          ? "bg-accent/10 font-medium text-accent"
          : "text-ink-muted hover:bg-surface-sunken hover:text-ink",
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="truncate">{children}</span>
    </Link>
  );
}
