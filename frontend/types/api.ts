/**
 * Domain types mirroring the AgentABI backend's actual FastAPI response
 * schemas (Phase 14 spec §34) — inventoried directly from
 * backend/app/api/v1/*.py. Never invent a field here that the backend
 * does not actually return.
 */

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ---- errors ---------------------------------------------------------

export interface ApiErrorField {
  location: string[];
  message: string;
  type: string;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  request_id: string;
  fields?: ApiErrorField[];
}

export interface ApiErrorEnvelope {
  error: ApiErrorBody;
}

// ---- auth -------------------------------------------------------------

export type OrganizationRole = "MEMBER" | "ADMIN" | "OWNER";

export interface AuthMeResponse {
  user_id: string;
  email: string;
  organization_id: string | null;
  role: OrganizationRole | null;
}

export interface GitHubCallbackResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  email: string;
  organization_id: string | null;
  role: OrganizationRole | null;
  requires_onboarding: boolean;
}

// ---- projects -----------------------------------------------------------

export interface Project {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  created_at: string;
  updated_at: string;
}

// ---- components -----------------------------------------------------------

export type ComponentStatus = "active" | "deprecated" | "archived" | string;

export interface Component {
  id: string;
  project_id: string;
  organization_id: string;
  component_type: string;
  name: string;
  slug: string;
  description: string | null;
  status: ComponentStatus;
  created_at: string;
  updated_at: string;
}

export interface ComponentVersion {
  id: string;
  component_id: string;
  version: string;
  sequence: number;
  content: Record<string, unknown>;
  checksum: string;
  version_metadata: Record<string, unknown> | null;
  created_at: string;
}

// ---- compatibility -----------------------------------------------------------

export type Classification = "compatible" | "potentially_breaking" | "breaking";
export type Severity = "info" | "low" | "medium" | "high" | "critical";
export type CompatibilityStatus = "compatible" | "warning" | "breaking" | string;

export interface ScanChange {
  id: string;
  order_index: number;
  change_type: string;
  path: string;
  classification: Classification;
  severity: Severity;
  message: string;
  old_value: unknown;
  new_value: unknown;
  evidence: Record<string, unknown> | null;
}

export interface ScanSummary {
  total_changes: number;
  compatible_count: number;
  potentially_breaking_count: number;
  breaking_count: number;
  severity_info_count: number;
  severity_low_count: number;
  severity_medium_count: number;
  severity_high_count: number;
  severity_critical_count: number;
}

export interface CompatibilityScan {
  id: string;
  project_id: string;
  component_id: string;
  baseline_version_id: string;
  candidate_version_id: string;
  status: CompatibilityStatus;
  created_at: string;
  summary: ScanSummary;
  changes: ScanChange[];
}

export interface CompatibilityScanListItem {
  id: string;
  project_id: string;
  component_id: string;
  status: CompatibilityStatus;
  created_at: string;
  summary: ScanSummary;
}

export interface ExplanationReference {
  reference_id: string;
  note: string;
}

export interface ExplanationResponse {
  summary: string;
  key_findings: string[];
  likely_impact: string[];
  remediation_steps: string[];
  evidence_references: ExplanationReference[];
  limitations: string[];
  provider: string;
  model: string;
}

// ---- graph -----------------------------------------------------------

export interface GraphNode {
  component_id: string;
  project_id: string;
  organization_id: string;
  component_type: string;
  name: string;
  slug: string;
  version: string;
  checksum: string;
  synced_at: string;
}

export interface DependencyEdge {
  component_id: string;
  component_type: string;
  name: string;
  slug: string;
  relationship_type: string;
}

export interface BlastRadiusEntry {
  component_id: string;
  component_type: string;
  name: string;
  slug: string;
  depth: number;
  path: string[];
}

export interface BlastRadiusResponse {
  component_id: string;
  max_depth: number;
  total_affected: number;
  direct_dependents: BlastRadiusEntry[];
  transitive_dependents: BlastRadiusEntry[];
  affected_by_type: Record<string, number>;
}

// ---- trajectories -----------------------------------------------------------

export type TrajectoryStatus = "running" | "completed" | "failed" | string;

export interface Trajectory {
  id: string;
  project_id: string;
  organization_id: string;
  workflow_component_id: string | null;
  workflow_version_id: string | null;
  external_run_id: string | null;
  status: TrajectoryStatus;
  environment: string | null;
  correlation_id: string | null;
  trace_id: string | null;
  span_id: string | null;
  tags: string[] | null;
  metadata: Record<string, unknown> | null;
  error: string | null;
  started_at: string;
  completed_at: string | null;
  duration_seconds: number | null;
  event_count: number;
}

export interface TrajectoryEvent {
  id: string;
  trajectory_id: string;
  sequence_number: number;
  event_type: string;
  occurred_at: string;
  recorded_at: string;
  component_id: string | null;
  component_version_id: string | null;
  parent_event_id: string | null;
  correlation_id: string | null;
  external_event_id: string | null;
  input: unknown;
  output: unknown;
  error: unknown;
  metadata: Record<string, unknown> | null;
  duration_ms: number | null;
  payload_truncated: boolean;
  payload_original_size_bytes: number | null;
  content_hash: string;
}

// ---- replays -----------------------------------------------------------

export type ReplayStatus = "pending" | "running" | "completed" | "failed";
export type StepKind =
  | "reused_evidence"
  | "substituted_execution"
  | "provider_execution_required"
  | "skipped";
export type StepStatus =
  | "pending"
  | "reused"
  | "executed"
  | "failed"
  | "skipped"
  | "provider_required";

export interface Replay {
  id: string;
  project_id: string;
  organization_id: string;
  source_trajectory_id: string;
  component_id: string;
  baseline_component_version_id: string;
  candidate_component_version_id: string;
  status: ReplayStatus;
  idempotency_key: string | null;
  configuration: Record<string, unknown> | null;
  plan: Record<string, unknown>[] | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  step_count: number;
}

export interface ReplayStep {
  id: string;
  replay_run_id: string;
  sequence_number: number;
  source_event_id: string;
  kind: StepKind;
  status: StepStatus;
  component_id: string | null;
  component_version_id: string | null;
  input: unknown;
  output: unknown;
  error: unknown;
  justification: string | null;
  duration_ms: number | null;
}

// ---- differential -----------------------------------------------------------

export interface DifferentialChange {
  id: string;
  order_index: number;
  alignment_method: string;
  difference_types: string[];
  sequence_number: number | null;
  baseline_step_id: string | null;
  candidate_step_id: string | null;
  baseline_status: string | null;
  candidate_status: string | null;
  output_differences: Record<string, unknown>[];
  error_difference: Record<string, unknown> | null;
  latency_delta_ms: number | null;
  latency_percent_delta: number | null;
}

export interface DifferentialSummary {
  total_baseline_steps: number;
  total_candidate_steps: number;
  matched_steps: number;
  added_steps: number;
  removed_steps: number;
  changed_steps: number;
  new_failures: number;
  resolved_failures: number;
  changed_outputs: number;
  schema_changes: number;
}

export interface DifferentialReport {
  id: string;
  project_id: string;
  baseline_replay_id: string;
  candidate_replay_id: string;
  compatibility_scan_id: string | null;
  analyzer_version: string;
  content_hash: string;
  created_at: string;
  summary: DifferentialSummary;
  changes: DifferentialChange[];
}

// ---- risk -----------------------------------------------------------

export type RiskDecision = "PASS" | "WARN" | "BLOCK";

export interface RiskRuleResult {
  id: string;
  order_index: number;
  rule_id: string;
  category: string;
  description: string;
  score_delta: number;
  evidence_refs: string[];
  hard_block: boolean;
}

export interface RiskAssessment {
  id: string;
  project_id: string;
  compatibility_scan_id: string | null;
  differential_report_id: string | null;
  risk_engine_version: string;
  decision: RiskDecision;
  score: number;
  hard_block: boolean;
  content_hash: string;
  created_at: string;
  rule_results: RiskRuleResult[];
}

export interface RiskAssessmentListItem {
  id: string;
  compatibility_scan_id: string | null;
  differential_report_id: string | null;
  decision: RiskDecision;
  score: number;
  hard_block: boolean;
  created_at: string;
}

// ---- github -----------------------------------------------------------

export interface GitHubRepositoryMapping {
  id: string;
  project_id: string;
  component_id: string | null;
  github_repository_id: number;
  github_repository_full_name: string;
  github_installation_id: number | null;
  baseline_version: string | null;
  created_at: string;
}

export type GitHubPRAnalysisStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "failed"
  | "publish_failed";

export interface GitHubPRAnalysis {
  id: string;
  project_id: string;
  github_repository_id: number;
  pull_request_number: number;
  head_sha: string;
  base_sha: string;
  analysis_version: string;
  status: GitHubPRAnalysisStatus;
  decision: RiskDecision | null;
  compatibility_scan_id: string | null;
  risk_assessment_id: string | null;
  check_run_id: number | null;
  publish_error: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

// ---- audit -----------------------------------------------------------

export interface AuditEvent {
  id: string;
  organization_id: string | null;
  actor_user_id: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  request_id: string | null;
  correlation_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}
