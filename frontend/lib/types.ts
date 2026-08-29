/** Shared API types. Mirrors the backend Pydantic schemas. */

export type HealthStatus = "ok" | "degraded";

export interface DependencyStatus {
  name: string;
  configured: boolean;
  reachable: boolean | null;
  detail: string | null;
}

export interface HealthResponse {
  status: HealthStatus;
  app: string;
  environment: string;
  version: string;
  timestamp: string;
  dependencies: DependencyStatus[];
}
