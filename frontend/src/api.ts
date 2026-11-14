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

export interface LineageEdge {
  id: string;
  runId: string;
  oldCellId: string;
  newCellId: string;
  relation: "continued" | "split" | "merged" | "born" | "died";
  overlap: number;
  oldCellKey: string | null;
  newCellKey: string | null;
  oldCellSize: number | null;
  newCellSize: number | null;
  createdAt: string;
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

export interface AlertTraceScore extends TraceScore {
  alertStatus: "alerted" | "candidate" | "suppressed_duplicate";
  priority: number;
  priorityRank: number;
  groupKey: string;
  groupRank: number;
  groupSize: number;
  cause: string;
  causeKind: string;
  reasons: string[];
}

export interface AlertSummary {
  budget: number;
  totalAlerts: number;
  groups: number;
  emitted: number;
  candidates: number;
  statusCounts: Record<string, number>;
  topGroups: Array<{
    groupKey: string;
    cause: string;
    causeKind: string;
    groupSize: number;
    topPriority: number;
    status: string;
  }>;
}

export interface Calibration {
  runId: string;
  kind: string;
  labelCount: number | null;
  ece: number | null;
  metrics: Record<string, unknown>;
}

export interface ReviewCalibration {
  id: string;
  tenantId: string;
  sourceRunId: string;
  labelCount: number;
  traceCount: number;
  verdictCounts: Record<string, number>;
  alertReviewed: number;
  alertAgree: number;
  alertDisagree: number;
  alertPrecision: number | null;
  ece: number | null;
  brier: number | null;
  metrics: Record<string, unknown>;
  parameters: Record<string, unknown>;
  codeHash: string;
  createdBy: string;
  createdAt: string;
  activatedAt: string | null;
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

export interface LifecycleSchedule {
  id: string;
  ontologyId: string;
  enabled: boolean;
  source: "jsonl" | "langfuse";
  sourceRef: string;
  intervalHours: number;
  windowHours: number;
  samplingRate: number;
  maxTraces: number | null;
  r2NoveltyThreshold: number;
  r2MinNoveltyTraces: number;
  r2AlertRateThreshold: number;
  writebackToLangfuse: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface LifecycleInput {
  enabled: boolean;
  source: "jsonl" | "langfuse";
  sourceRef: string;
  intervalHours: number;
  windowHours: number;
  samplingRate: number;
  maxTraces?: number | null;
  r2NoveltyThreshold: number;
  r2MinNoveltyTraces: number;
  r2AlertRateThreshold: number;
  writebackToLangfuse: boolean;
}

export interface LifecycleEvaluation {
  id: string;
  ontologyId: string;
  decision: "skipped" | "created_r1" | "created_r2";
  reason: string;
  metrics: {
    runId?: string | null;
    traceCount?: number;
    noveltyRate?: number | null;
    accumulatedNoveltyTraces?: number;
    r2MinNoveltyTraces?: number;
    alertRate?: number | null;
    elapsedHours?: number | null;
  };
  createdRunId: string | null;
  createdAt: string;
  run: Run | null;
  windowStart: string;
  windowEnd: string;
  evaluationBucket: string;
}

export interface SchedulerLatestScan {
  id: string;
  status: "running" | "succeeded" | "failed";
  startedAt: string;
  finishedAt: string | null;
  watchdogFailedRuns: number;
  evaluationCount: number;
  createdRunCount: number;
  result: Record<string, unknown>;
  error: string | null;
}

export interface SchedulerStatus {
  lock: {
    id: string;
    ownerId: string;
    acquiredAt: string;
    expiresAt: string;
  } | null;
  enabledSchedules: number;
  latestScan: SchedulerLatestScan | null;
}

export interface SchedulerScanResult {
  status: "succeeded" | "failed" | "skipped";
  scanId?: string;
  reason?: string;
  error?: string;
  watchdogFailedRuns?: string[];
  evaluations?: Array<{
    ontologyId: string;
    decision: string;
    reason: string;
    runId: string | null;
  }>;
}

export interface ReviewQueueResult {
  runId: string;
  queueId: string;
  pushed?: number;
  imported?: number;
  statusUpdates?: number;
  awaitingReview?: number;
}

export interface Review {
  id: string;
  traceScoreId: string;
  reviewer: string;
  verdict: string;
  label: string | null;
  comment: string | null;
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
  lineage: (id: string) => request<LineageEdge[]>(`/api/v1/runs/${id}/lineage`),
  traces: (id: string, query = "") =>
    request<Page<TraceScore>>(`/api/v1/runs/${id}/traces?limit=100${query}`),
  trace: (runId: string, traceId: string) =>
    request<TraceScoreDetail>(`/api/v1/runs/${runId}/traces/${traceId}`),
  alerts: (id: string) => request<AlertTraceScore[]>(`/api/v1/runs/${id}/alerts?limit=100`),
  alertCandidates: (id: string) =>
    request<AlertTraceScore[]>(`/api/v1/runs/${id}/alert-candidates?limit=100`),
  alertSummary: (id: string) => request<AlertSummary>(`/api/v1/runs/${id}/alerts/summary`),
  alertConfig: () => request<Record<string, unknown>>("/api/v1/config/alerts"),
  calibration: (id: string) => request<Calibration>(`/api/v1/runs/${id}/calibration`),
  reviews: (runId: string) => request<Page<Review>>(`/api/v1/reviews?runId=${runId}&limit=100`),
  reviewCalibrations: (runId: string) =>
    request<Page<ReviewCalibration>>(`/api/v1/calibrations?runId=${runId}&limit=100`),
  triggerCalibration: (runId: string, createdBy: string) =>
    request<ReviewCalibration>(`/api/v1/runs/${runId}/calibration/trigger`, {
      method: "POST",
      body: JSON.stringify({ createdBy })
    }),
  activateCalibration: (id: string) =>
    request<ReviewCalibration>(`/api/v1/calibrations/${id}/activate`, {
      method: "POST"
    }),
  createRun: (input: RunInput) =>
    request<Run>("/api/v1/runs", { method: "POST", body: JSON.stringify(input) })
  ,
  lifecycle: (ontologyId: string) =>
    request<LifecycleSchedule>(`/api/v1/ontologies/${ontologyId}/lifecycle`),
  saveLifecycle: (ontologyId: string, input: LifecycleInput) =>
    request<LifecycleSchedule>(`/api/v1/ontologies/${ontologyId}/lifecycle`, {
      method: "PUT",
      body: JSON.stringify(input)
    }),
  evaluateLifecycle: (ontologyId: string, forceR2 = false) =>
    request<LifecycleEvaluation>(`/api/v1/ontologies/${ontologyId}/lifecycle/evaluate`, {
      method: "POST",
      body: JSON.stringify({ forceR2 })
    }),
  lifecycleEvaluations: (ontologyId: string) =>
    request<Page<LifecycleEvaluation>>(`/api/v1/ontologies/${ontologyId}/lifecycle/evaluations?limit=50`),
  schedulerStatus: () => request<SchedulerStatus>("/api/v1/scheduler/status"),
  evaluateAllLifecycles: () =>
    request<SchedulerScanResult>("/api/v1/scheduler/evaluate-all", { method: "POST" }),
  createReviewQueue: (runId: string, input: { scope: "alerts" | "abstains" | "all"; limit?: number }) =>
    request<ReviewQueueResult>(`/api/v1/runs/${runId}/review-queue`, {
      method: "POST",
      body: JSON.stringify(input)
    }),
  syncReviewQueue: (runId: string) =>
    request<ReviewQueueResult>(`/api/v1/runs/${runId}/review-queue/sync`, { method: "POST" })
};
