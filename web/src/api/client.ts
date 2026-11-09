// Centralised typed client for the forge API.
//
// Token handling: the access token lives only in memory (this module), never in
// localStorage/sessionStorage, so an XSS bug cannot read a persisted credential
// and closing the tab ends the session. The cost is re-login after a reload; an
// httpOnly SameSite cookie issued by the API would remove that cost and is the
// documented next step (docs/security.md).
import type {
  Approval, AuditEvent, EvaluationRun, Incident, InvestigationDetail, Investigation, Me, Overview, Page,
  Proposal, RecoveryJob, ValidationRun, Workspace,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, unknown> = {}) {
    super(message);
  }
  get isAuth() { return this.status === 401; }
  get isForbidden() { return this.status === 403; }
}

let token: string | null = null;
let onUnauthorized: () => void = () => {};
export const session = {
  set(t: string | null) { token = t; },
  get active() { return token !== null; },
  onExpired(cb: () => void) { onUnauthorized = cb; },
};

async function request<T>(method: "GET" | "POST", path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(path, {
      method, signal,
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "network_error", "Cannot reach the IncidentForge API. Check that forge-api is running.");
  }
  const text = await resp.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (!resp.ok) {
    const e = (data as { error?: { code?: string; message?: string; details?: Record<string, unknown> } } | null)?.error;
    const error = new ApiError(resp.status, e?.code ?? "http_error", e?.message ?? `Request failed (${resp.status})`, e?.details ?? {});
    if (error.isAuth && path !== "/api/auth/login") { token = null; onUnauthorized(); }
    throw error;
  }
  return data as T;
}

const get = <T,>(path: string, signal?: AbortSignal) => request<T>("GET", path, undefined, signal);
const post = <T,>(path: string, body?: unknown) => request<T>("POST", path, body);

export const api = {
  login: (username: string, password: string) =>
    post<{ access_token: string; user: { username: string; role: string } }>("/api/auth/login", { username, password }),
  me: (s?: AbortSignal) => get<Me>("/api/me", s),
  overview: (s?: AbortSignal) => get<Overview>("/api/system/overview", s),
  incidents: (q: { status?: string; q?: string; sort?: string; order?: string; page?: number }, s?: AbortSignal) => {
    const params = new URLSearchParams(Object.entries(q).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));
    return get<Page<Incident>>(`/api/incidents?${params}`, s);
  },
  registerIncident: (title: string, severity: string, description: string) =>
    post<Incident>("/api/incidents", { title, severity, description }),
  workspace: (id: string, s?: AbortSignal) => get<Workspace>(`/api/incidents/${encodeURIComponent(id)}`, s),
  timeline: (id: string, s?: AbortSignal) => get<{ items: AuditEvent[] }>(`/api/incidents/${encodeURIComponent(id)}/timeline`, s),
  closeIncident: (id: string, reason: string) => post<Incident>(`/api/incidents/${encodeURIComponent(id)}/close`, { reason }),
  startInvestigation: (id: string, mode?: string) =>
    post<Investigation>(`/api/incidents/${encodeURIComponent(id)}/investigations`, mode ? { mode } : {}),
  investigation: (id: string, s?: AbortSignal) => get<InvestigationDetail>(`/api/investigations/${encodeURIComponent(id)}`, s),
  proposal: (id: string, s?: AbortSignal) => get<Proposal & { latest_validation: ValidationRun | null }>(`/api/proposals/${encodeURIComponent(id)}`, s),
  requestValidation: (id: string) => post<ValidationRun>(`/api/proposals/${encodeURIComponent(id)}/validations`),
  requestApproval: (id: string) => post<Approval>(`/api/proposals/${encodeURIComponent(id)}/approvals`),
  approvals: (status: string, s?: AbortSignal) => get<{ items: Approval[] }>(`/api/approvals?status=${encodeURIComponent(status)}`, s),
  decide: (id: string, approve: boolean, note: string, bindingDigest: string) =>
    post<Approval>(`/api/approvals/${encodeURIComponent(id)}/decision`, { approve, note, binding_digest: bindingDigest }),
  requestRecovery: (proposalId: string) => post<RecoveryJob>(`/api/proposals/${encodeURIComponent(proposalId)}/recovery`),
  evaluations: (s?: AbortSignal) => get<{ runs: EvaluationRun[]; source: string }>("/api/evaluations", s),
};
