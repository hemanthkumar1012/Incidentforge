// Types mirror forge/api/serializers.py. Timestamps are ISO-8601 strings with a UTC offset.

export type Role = "viewer" | "operator" | "approver" | "admin";
export interface Me { username: string; role: Role; permissions: string[] }

export type IncidentStatus = "open" | "investigating" | "diagnosed" | "remediating" | "resolved" | "closed";
export interface Incident {
  id: string; title: string; status: IncidentStatus; severity: "sev1" | "sev2" | "sev3";
  source: "manual" | "detector"; signal: Record<string, unknown>; synthetic_traffic: boolean;
  created_by: string; created_at: string; updated_at: string; resolved_at: string | null;
}
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export interface Hypothesis {
  rank: number; category: string; component: string; faulty_setting: string | null; summary: string;
  confidence: "low" | "medium" | "high"; evidence_ids: string[]; contradicting_evidence_ids: string[];
}
export interface Diagnosis {
  outcome: "diagnosed" | "insufficient_evidence" | "no_incident"; hypotheses: Hypothesis[];
  affected: string[]; limitations: string[]; next_steps: string[];
}
export type InvestigationStatus =
  "queued" | "running" | "completed" | "insufficient_evidence" | "budget_exhausted" | "failed" | "cancelled";
export interface Investigation {
  id: string; incident_id: string; mode: "llm" | "runbook" | "llm_summary"; provider: string; model: string;
  status: InvestigationStatus; diagnosis: Diagnosis | null; usage: Record<string, number>;
  failure_reason: string | null; created_by: string; created_at: string; started_at: string | null;
  finished_at: string | null;
}
export interface Step { seq: number; kind: string; summary: string; tool: string | null; evidence_id: string | null; created_at: string }
export interface Evidence {
  id: string; tool: string; arguments: Record<string, unknown>; ok: boolean; data: unknown;
  error: { code: string; message: string } | null; summary: string; injection_flags: string[];
  truncated: boolean; duration_ms: number; created_at: string; trust: "untrusted";
}
export interface InvestigationDetail extends Investigation { steps: Step[]; evidence: Evidence[] }

export interface ConfigChange { key: string; op: string; old?: unknown; new?: unknown }
export interface Proposal {
  id: string; incident_id: string; investigation_id: string; action_type: string; target: string;
  parameters: Record<string, unknown>; expected_active_version: number; status: string;
  expected_effect?: ConfigChange[]; side_effects?: ConfigChange[]; evidence_ids?: string[];
  preconditions?: string[]; validation_procedure?: string[];
  rollback_procedure?: { description: string; parameters: Record<string, unknown> };
  approval_requirement?: string; rationale?: string; created_at: string;
}
export interface ValidationRun {
  id: string; proposal_id: string; status: "queued" | "running" | "passed" | "failed" | "not_reproducible" | "error";
  production_version: number; requested_by: string; created_at: string; finished_at: string | null;
  report: { verdict?: string; uncertainty?: string[]; steps?: { phase: string; expect?: string; checks?: { name: string; passed: boolean; detail: string }[]; detail?: string }[] };
}
export interface Approval {
  id: string; proposal_id: string; validation_run_id: string; binding: Record<string, unknown>;
  binding_digest: string; status: "pending" | "approved" | "rejected" | "expired" | "invalidated" | "consumed";
  requested_by: string; requested_at: string; expires_at: string; decided_by: string | null;
  decided_at: string | null; note: string | null; incident_id?: string; expected_effect?: ConfigChange[];
}
export interface RecoveryJob {
  id: string; proposal_id: string; approval_id: string; status: string; requested_by: string;
  config_version_before: number | null; config_version_after: number | null; created_at: string;
  finished_at: string | null; created?: boolean;
  result: { verification?: { passed: boolean; checks: { name: string; passed: boolean; status?: number }[] }; reasons?: string[] };
}
export interface Workspace {
  incident: Incident; investigations: Investigation[]; proposals: Proposal[];
  validations: ValidationRun[]; approvals: Approval[]; recoveries: RecoveryJob[];
}
export interface AuditEvent {
  id: number; occurred_at: string; actor: string; action: string; subject_type: string; subject_id: string;
  details: Record<string, unknown>;
}
export interface Overview {
  services: Record<string, { ready: boolean; status_code?: number; error?: string }>;
  topology: Record<string, string[]>;
  checkout_config: { version: number; payload: Record<string, unknown> } | { error: string } | null;
  config_versions: { version: number; author: string; created_at: string; active: boolean }[];
  investigation_default_mode: string; llm_configured: boolean; llm_model: string; investigator_scopes: string[];
}
export interface EvaluationRun {
  generated_at?: string; scenarios?: string[]; error?: string; file?: string;
  summary?: Record<string, string | number | null>[];
  trials?: Record<string, unknown>[];
}
