/**
 * Typed client for the AutoBuy backend.
 *
 * Every network call in the app goes through `apiFetch` so error handling,
 * base-URL resolution, and JSON parsing exist in exactly one place.
 */

import type { HealthResponse } from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** Thrown for any non-2xx response, carrying the status for callers to branch on. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => undefined);
    throw new ApiError(
      `Request to ${path} failed with ${res.status}`,
      res.status,
      body,
    );
  }

  return (await res.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health", { cache: "no-store" });
}
