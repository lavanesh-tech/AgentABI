/**
 * Centralized API client (Phase 14 spec §9). The only module that
 * calls `fetch` against the AgentABI backend — every hook in
 * features/*\/hooks.ts goes through this.
 */

import { clearStoredToken, getStoredToken } from "./auth-storage";
import type { ApiErrorBody, ApiErrorEnvelope } from "@/types/api";

const API_BASE_URL = process.env.NEXT_PUBLIC_AGENTABI_API_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | undefined;
  readonly fields: ApiErrorBody["fields"];

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.requestId = body.request_id;
    this.fields = body.fields;
  }
}

/** Thrown when the response could not even be parsed as the standard
 * error envelope (network failure, non-JSON 5xx from a proxy, etc.) —
 * kept distinct from ApiError so the UI can show a generic message
 * instead of a fabricated backend error code. */
export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NetworkError";
  }
}

export type QueryParams = Record<string, string | number | boolean | undefined | null>;

function buildUrl(path: string, params?: QueryParams): string {
  const base = API_BASE_URL.replace(/\/$/, "");
  const target = `${base}${path}`;

  if (!params) {
    return target;
  }

  const search = new URLSearchParams();

  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      search.set(key, String(value));
    }
  }

  const query = search.toString();

  if (!query) {
    return target;
  }

  return `${target}${target.includes("?") ? "&" : "?"}${query}`;
}

let onUnauthorized: (() => void) | null = null;

/** Registered once by the auth provider so a 401 anywhere clears the
 * session and redirects to /login, without api-client importing React
 * router hooks directly. */
export function registerUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  params?: QueryParams;
  /** Skip attaching the bearer token — only the GitHub OAuth exchange
   * uses this, before a token exists. */
  skipAuth?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, params, skipAuth } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (!skipAuth) {
    const token = getStoredToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, params), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (cause) {
    throw new NetworkError(
      cause instanceof Error ? cause.message : "Network request failed",
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  let parsed: unknown;
  const text = await response.text();
  try {
    parsed = text ? JSON.parse(text) : undefined;
  } catch {
    parsed = undefined;
  }

  if (!response.ok) {
    const envelope = parsed as ApiErrorEnvelope | undefined;
    if (response.status === 401) {
      clearStoredToken();
      onUnauthorized?.();
    }
    if (envelope?.error) {
      throw new ApiError(response.status, envelope.error);
    }
    throw new ApiError(response.status, {
      code: "UNKNOWN_ERROR",
      message: response.statusText || `Request failed with status ${response.status}`,
      request_id: response.headers.get("X-Correlation-ID") ?? "",
    });
  }

  return parsed as T;
}

export const apiClient = {
  get: <T>(path: string, params?: QueryParams) => request<T>(path, { method: "GET", params }),
  post: <T>(path: string, body?: unknown, params?: QueryParams) =>
    request<T>(path, { method: "POST", body, params }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  /** Used only by the OAuth callback exchange, before a token exists. */
  getUnauthenticated: <T>(path: string, params?: QueryParams) =>
    request<T>(path, { method: "GET", params, skipAuth: true }),
};

export function friendlyErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.status) {
      case 401:
        return "Your session has expired. Please sign in again.";
      case 403:
        return "You don't have permission to do that.";
      case 404:
        return "That resource could not be found.";
      case 409:
        return error.message || "This conflicts with existing data.";
      case 413:
        return "That request was too large.";
      case 422:
        return error.message || "The request was invalid.";
      case 429:
        return "You're making requests too quickly. Please wait and try again.";
      case 503:
        return "The service is temporarily unavailable. Please try again shortly.";
      default:
        return error.message || "Something went wrong.";
    }
  }
  if (error instanceof NetworkError) {
    return "Could not reach the AgentABI backend. Check your connection and try again.";
  }
  return "An unexpected error occurred.";
}
