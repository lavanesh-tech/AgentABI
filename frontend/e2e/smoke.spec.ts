import { test, expect } from "@playwright/test";

/**
 * Phase 14 spec §36 smoke suite. Written and, per the same sandbox
 * network restriction documented throughout this project (no outbound
 * access to install `@playwright/test`'s browser binaries or run
 * `npm install`), NOT executed here — see the phase completion report.
 * Mocks the API at the network layer so these do not depend on a real
 * backend being up.
 */

test("login page renders the GitHub sign-in action", async ({ page }) => {
  await page.route("**/auth/me", (route) => route.fulfill({ status: 401, body: "{}" }));
  await page.goto("/login");
  await expect(page.getByRole("button", { name: /sign in with github/i })).toBeVisible();
});

test("unauthenticated visit to a protected route redirects to /login", async ({ page }) => {
  await page.route("**/auth/me", (route) => route.fulfill({ status: 401, body: "{}" }));
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/);
});

test("dashboard renders the shell and project list once authenticated", async ({ page }) => {
  await page.addInitScript(() => {
    window.sessionStorage.setItem("agentabi_access_token", "fake-token");
  });
  await page.route("**/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        user_id: "00000000-0000-0000-0000-000000000001",
        email: "demo@example.com",
        organization_id: "00000000-0000-0000-0000-000000000002",
        role: "ADMIN",
      }),
    }),
  );
  await page.route("**/organizations/**/projects*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "00000000-0000-0000-0000-000000000003",
            organization_id: "00000000-0000-0000-0000-000000000002",
            name: "Payments",
            slug: "payments",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
        total: 1,
        page: 1,
        page_size: 100,
      }),
    }),
  );
  await page.goto("/dashboard");
  await expect(page.getByText("AgentABI")).toBeVisible();
  await expect(page.getByText("Payments")).toBeVisible();
});

test("risk result renders PASS/WARN/BLOCK with mocked API data", async ({ page }) => {
  await page.addInitScript(() => {
    window.sessionStorage.setItem("agentabi_access_token", "fake-token");
  });
  await page.route("**/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        user_id: "u1",
        email: "demo@example.com",
        organization_id: "org1",
        role: "ADMIN",
      }),
    }),
  );
  await page.route("**/risk/assessments*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "a1",
            compatibility_scan_id: "s1",
            differential_report_id: null,
            decision: "BLOCK",
            score: 85,
            hard_block: true,
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      }),
    }),
  );
  await page.goto("/risk?projectId=p1");
  await expect(page.getByText("BLOCK")).toBeVisible();
});
