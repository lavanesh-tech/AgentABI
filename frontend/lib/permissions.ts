/**
 * Frontend mirror of app/authz/permissions.py's role -> permission map
 * (Phase 14 spec §29). This is UX only — hides/disables controls the
 * backend would reject anyway. The backend remains the sole authority;
 * never treat a client-side allow as proof of authorization.
 */

import type { OrganizationRole } from "@/types/api";

export type Permission =
  | "project:read"
  | "project:create"
  | "project:update"
  | "component:read"
  | "component:write"
  | "scan:read"
  | "scan:execute"
  | "trajectory:read"
  | "trajectory:write"
  | "replay:read"
  | "replay:execute"
  | "graph:read"
  | "graph:write"
  | "membership:manage"
  | "org:manage"
  | "audit:read"
  | "differential:read"
  | "differential:execute"
  | "risk:read"
  | "risk:execute"
  | "github_integration:read"
  | "github_integration:manage";

const READ_PERMISSIONS: Permission[] = [
  "project:read",
  "component:read",
  "scan:read",
  "trajectory:read",
  "replay:read",
  "graph:read",
  "differential:read",
  "risk:read",
  "github_integration:read",
];

const WRITE_PERMISSIONS: Permission[] = [
  "project:create",
  "project:update",
  "component:write",
  "scan:execute",
  "trajectory:write",
  "replay:execute",
  "graph:write",
  "differential:execute",
  "risk:execute",
  "github_integration:manage",
];

const MEMBER_PERMISSIONS = new Set<Permission>([...READ_PERMISSIONS, "differential:read", "risk:read"]);
const ADMIN_PERMISSIONS = new Set<Permission>([
  ...MEMBER_PERMISSIONS,
  ...WRITE_PERMISSIONS,
  "audit:read",
]);
const OWNER_PERMISSIONS = new Set<Permission>([
  ...ADMIN_PERMISSIONS,
  "membership:manage",
  "org:manage",
]);

export function hasPermission(role: OrganizationRole | null, permission: Permission): boolean {
  if (!role) return false;
  if (role === "OWNER") return OWNER_PERMISSIONS.has(permission);
  if (role === "ADMIN") return ADMIN_PERMISSIONS.has(permission);
  if (role === "MEMBER") return MEMBER_PERMISSIONS.has(permission);
  return false;
}
