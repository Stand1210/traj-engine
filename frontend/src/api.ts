export interface Page<T> {
  data: T[];
  page: { nextCursor: string | null; limit: number };
}

export interface ProfileInfo {
  profile: string;
  baseUrl: string;
  versionConstraint: string;
}

export interface StartupRecord {
  id: string;
  profile: string;
  profileHash: string;
  langfuseVersion: string | null;
  checkedAt: string;
  skipped: boolean;
}

export interface Tenant {
  id: string;
  displayName: string;
  orgId: string;
  projectId: string;
}

export interface Ontology {
  id: string;
  tenantId: string;
  currentVersion: number;
  tier: string;
}

export interface Run {
  id: string;
  tenantId: string;
  ontologyId: string;
  ontologyVersion: number;
  runType: string;
  source: string;
  sourceRef: string | null;
  status: string;
  structureVersion: string | null;
  codeHash: string;
  error: string | null;
  createdAt: string;
  startedAt: string | null;
  endedAt: string | null;
}

export interface RunStep {
  id: string;
  runId: string;
  name: string;
  status: string;
  startedAt: string;
  endedAt: string | null;
  payload: Record<string, unknown> | null;
}

export interface Cell {
  id: string;
  runId: string;
  cellKey: string;
  label: string | null;
  size: number;
  metrics: Record<string, unknown>;
}

export interface TraceScore {
  id: string;
  runId: string;
  traceId: string;
  cellId: string | null;
  totalScore: number;
  resultScore: number;
  processScore: number;
  latencyScore: number;
  costScore: number;
  robustnessScore: number;
  isAlert: boolean;
  isAbstain: boolean;
  structureVersion: string | null;
  ontologyVersion: number;
  codeHash: string;
}

export interface Evidence {
  id: string;
  traceScoreId: string;
  dimension: string;
  spanId: string | null;
  contribution: number;
  explanation: string;
  payload: Record<string, unknown> | null;
}

export interface TraceScoreDetail extends TraceScore {
  evidence: Evidence[];
}

export interface Calibration {
  runId: string;
  kind: string;
  labelCount: number | null;
  ece: number | null;
  metrics: Record<string, unknown>;
}

export interface RunInput {
  tenantId: string;
  ontologyId: string;
  source: "jsonl" | "langfuse";
  sourceRef: string;
  runType: "R1" | "R2" | "R3";
  windowStart: string;
  windowEnd: string;
  samplingRate: number;
  limit?: number;
  triggerReason?: string;
  idempotencyKey?: string;
  writebackToLangfuse?: boolean;
  writebackStrict?: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      // Keep the HTTP status message.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; version: string }>("/api/v1/health"),
  profile: () => request<ProfileInfo>("/api/v1/config/profile"),
  startup: () => request<StartupRecord>("/api/v1/startup-records/current"),
  tenants: () => request<Page<Tenant>>("/api/v1/tenants?limit=100"),
  ontologies: () => request<Page<Ontology>>("/api/v1/ontologies?limit=100"),
  runs: () => request<Page<Run>>("/api/v1/runs?limit=100"),
  run: (id: string) => request<Run>(`/api/v1/runs/${id}`),
  runSteps: (id: string) => request<RunStep[]>(`/api/v1/runs/${id}/steps`),
  cells: (id: string) => request<Cell[]>(`/api/v1/runs/${id}/cells`),
  traces: (id: string, query = "") =>
    request<Page<TraceScore>>(`/api/v1/runs/${id}/traces?limit=100${query}`),
  trace: (runId: string, traceId: string) =>
    request<TraceScoreDetail>(`/api/v1/runs/${runId}/traces/${traceId}`),
  alerts: (id: string) => request<TraceScore[]>(`/api/v1/runs/${id}/alerts?limit=100`),
  calibration: (id: string) => request<Calibration>(`/api/v1/runs/${id}/calibration`),
  createRun: (input: RunInput) =>
    request<Run>("/api/v1/runs", { method: "POST", body: JSON.stringify(input) })
};
