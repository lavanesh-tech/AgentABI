import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { apiClient, ApiError, friendlyErrorMessage, NetworkError } from "@/lib/api-client";

const originalFetch = global.fetch;

beforeEach(() => {
  window.sessionStorage.clear();
});

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

function mockResponse(status: number, body: unknown) {
  return {
    status,
    ok: status >= 200 && status < 300,
    statusText: "",
    headers: new Headers(),
    text: async () => JSON.stringify(body),
  } as Response;
}

describe("apiClient error parsing", () => {
  it("parses the standardized error envelope into an ApiError", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      mockResponse(404, {
        error: { code: "RESOURCE_NOT_FOUND", message: "Project not found", request_id: "req-1" },
      }),
    );

    await expect(apiClient.get("/projects/does-not-exist")).rejects.toMatchObject({
      status: 404,
      code: "RESOURCE_NOT_FOUND",
      requestId: "req-1",
    });
  });

  it("includes validation fields for 422 responses", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      mockResponse(422, {
        error: {
          code: "VALIDATION_ERROR",
          message: "Invalid request",
          request_id: "req-2",
          fields: [{ location: ["body", "name"], message: "required", type: "missing" }],
        },
      }),
    );

    try {
      await apiClient.get("/projects");
      throw new Error("expected rejection");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).fields?.[0]?.message).toBe("required");
    }
  });

  it("throws NetworkError when fetch itself fails", async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError("network down"));
    await expect(apiClient.get("/projects")).rejects.toBeInstanceOf(NetworkError);
  });

  it("maps status codes to friendly messages", () => {
    const err = new ApiError(429, { code: "RATE_LIMITED", message: "", request_id: "r" });
    expect(friendlyErrorMessage(err)).toMatch(/too quickly/);
  });
});
