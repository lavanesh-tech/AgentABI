import { describe, expect, it } from "vitest";
import { hasPermission } from "@/lib/permissions";

describe("permission-aware controls", () => {
  // Role literals here are the backend's actual wire format
  // (lowercase "owner"/"admin"/"member" — see types/api.ts's
  // OrganizationRole) — this suite previously asserted against
  // uppercase literals that a real backend-issued token never sends,
  // which is why it never caught hasPermission() silently returning
  // false for every real user.
  it("member can read but not execute/manage", () => {
    expect(hasPermission("member", "risk:read")).toBe(true);
    expect(hasPermission("member", "risk:execute")).toBe(false);
    expect(hasPermission("member", "github_integration:manage")).toBe(false);
    expect(hasPermission("member", "audit:read")).toBe(false);
  });

  it("admin can execute/manage but not membership/org", () => {
    expect(hasPermission("admin", "risk:execute")).toBe(true);
    expect(hasPermission("admin", "github_integration:manage")).toBe(true);
    expect(hasPermission("admin", "audit:read")).toBe(true);
    expect(hasPermission("admin", "membership:manage")).toBe(false);
  });

  it("owner has every permission admin has, plus membership/org and project:create", () => {
    expect(hasPermission("owner", "membership:manage")).toBe(true);
    expect(hasPermission("owner", "org:manage")).toBe(true);
    expect(hasPermission("owner", "risk:execute")).toBe(true);
    expect(hasPermission("owner", "project:create")).toBe(true);
  });

  it("a null role denies everything", () => {
    expect(hasPermission(null, "project:read")).toBe(false);
  });

  it("an unknown/unrecognized role string denies everything (fails closed)", () => {
    // Cast past the type system deliberately: this proves hasPermission
    // itself fails closed on a value that isn't one of the three known
    // roles, independent of what TypeScript would otherwise allow.
    expect(hasPermission("OWNER" as never, "project:create")).toBe(false);
  });
});
