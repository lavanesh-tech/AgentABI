import { describe, expect, it } from "vitest";
import { hasPermission } from "@/lib/permissions";

describe("permission-aware controls", () => {
  it("MEMBER can read but not execute/manage", () => {
    expect(hasPermission("MEMBER", "risk:read")).toBe(true);
    expect(hasPermission("MEMBER", "risk:execute")).toBe(false);
    expect(hasPermission("MEMBER", "github_integration:manage")).toBe(false);
    expect(hasPermission("MEMBER", "audit:read")).toBe(false);
  });

  it("ADMIN can execute/manage but not membership/org", () => {
    expect(hasPermission("ADMIN", "risk:execute")).toBe(true);
    expect(hasPermission("ADMIN", "github_integration:manage")).toBe(true);
    expect(hasPermission("ADMIN", "audit:read")).toBe(true);
    expect(hasPermission("ADMIN", "membership:manage")).toBe(false);
  });

  it("OWNER has every permission ADMIN has, plus membership/org", () => {
    expect(hasPermission("OWNER", "membership:manage")).toBe(true);
    expect(hasPermission("OWNER", "org:manage")).toBe(true);
    expect(hasPermission("OWNER", "risk:execute")).toBe(true);
  });

  it("a null role denies everything", () => {
    expect(hasPermission(null, "project:read")).toBe(false);
  });
});
