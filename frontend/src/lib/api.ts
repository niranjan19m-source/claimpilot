// Typed client for the ClaimPilot FastAPI backend. Every type mirrors a real
// response shape from backend/app/main.py or backend/app/api_extra.py.

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Hosted read-only demo: the UI reads a recorded real backend run instead of a live API. */
export const SNAPSHOT = process.env.NEXT_PUBLIC_SNAPSHOT === "1";
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
export const READ_ONLY = SNAPSHOT;
export const READ_ONLY_MSG = "This hosted demo is a read-only recording of a real agent run, so actions are disabled.";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

const snapCache = new Map<string, Promise<any>>();
function snapshotFile(path: string) {
  return `${BASE_PATH}/snapshot/${path.replace(/^\/api\//, "").replace(/\//g, "__")}.json`;
}
const has = (hay: string, q: string) => hay.toLowerCase().includes(q.toLowerCase());

/** Applies the same query filters the backend would, so filtered views work offline. */
function filterSnapshot(path: string, q: URLSearchParams, data: any) {
  const get = (k: string) => q.get(k);
  if (path === "/api/evidence") return data.filter((e: any) => (!get("claim_id") || e.claim_id === get("claim_id"))
    && (!get("category") || e.category === get("category")) && (!get("status") || e.status === get("status"))
    && (!get("q") || has(`${e.summary} ${e.label} ${e.claim_id}`, get("q")!)));
  if (path === "/api/audit") return data.filter((a: any) => (!get("claim_id") || a.claim_id === get("claim_id"))
    && (!get("category") || a.category === get("category")) && (!get("q") || has(`${a.text} ${a.claim_id} ${a.actor}`, get("q")!)));
  if (path === "/api/decisions") return data.filter((d: any) => !get("claim_id") || d.claim_id === get("claim_id"));
  if (path === "/api/policy-library") {
    const words = (get("q") ?? "").toLowerCase().split(/\s+/).filter(Boolean);
    let clauses = data.clauses.filter((c: any) => (!get("product") || c.product === get("product")) && (!get("kind") || c.kind === get("kind")));
    if (words.length) {
      clauses = clauses.map((c: any) => ({ ...c, score: words.filter((w: string) => has(`${c.title} ${c.text}`, w)).length / words.length }))
        .filter((c: any) => c.score > 0).sort((a: any, b: any) => b.score - a.score);
    }
    return { ...data, clauses };
  }
  return data;
}

async function snapshotApi<T>(path: string, init?: RequestInit): Promise<T> {
  if (init?.method && init.method !== "GET") throw new ApiError(405, READ_ONLY_MSG);
  const [p, qs] = path.split("?");
  if (!snapCache.has(p)) {
    snapCache.set(p, fetch(snapshotFile(p)).then((r) => {
      if (!r.ok) throw new ApiError(404, "Not included in the hosted demo snapshot.");
      return r.json();
    }));
  }
  try {
    return filterSnapshot(p, new URLSearchParams(qs ?? ""), await snapCache.get(p)) as T;
  } catch (e) {
    snapCache.delete(p);
    throw e;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  if (SNAPSHOT) return snapshotApi<T>(path, init);
  let r: Response;
  try {
    r = await fetch(`${API}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(0, "Backend unreachable. Is the API running on port 8000?");
  }
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: any) => d.msg).join("; ") : msg;
    } catch {}
    throw new ApiError(r.status, msg);
  }
  return r.json();
}

export const postJSON = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });

export const fileUrl = (docId: number, filename?: string) => SNAPSHOT
  ? `${BASE_PATH}/snapshot/files/${docId}${(filename?.match(/\.[a-z0-9]+$/i)?.[0] ?? "").toLowerCase()}`
  : `${API}/api/documents/${docId}/file`;

// ------------------------------------------------------------------ domain types
export type Queue = "fast_track" | "standard" | "senior" | "medical" | "siu" | "coverage_review";
export type ClaimStatus = "submitted" | "triaging" | "triaged" | "awaiting_review" | "awaiting_documents" | "assigned"
  | "approved" | "error" | "interrupted" | "closed";

export type Signal = {
  code: string; label: string; weight: number; detail: string; kind?: string; evidence?: string[]; source?: string;
};

/** One entry of the evidence ledger: a single tool execution and its result. */
export type ToolResult = {
  id: string; tool: string; label: string; input: Record<string, unknown>; ok: boolean; summary: string;
  data: Record<string, any>; signals: Signal[]; ms: number; auto?: boolean;
};

export type PlanStep = { tool: string; reason: string; label: string };
export type InvestigationPlan = {
  depth: "light" | "standard" | "deep"; rationale: string; hypotheses: string[]; steps: PlanStep[]; source: "llm" | "rules";
};

export type PolicyFinding = {
  clause_id: string; title: string; text: string; outcome: "pass" | "fail" | "needs_info" | "applied"; note: string; effect?: string;
};

export type RiskAssessment = {
  fraud: { score: number; band: "low" | "medium" | "high"; signals: Signal[] };
  severity: { level: "low" | "medium" | "high" | "critical"; points: number; reasons: string[] };
  coverage: {
    status: string; payable: { lines: { label: string; amount: number }[]; net: number; gross: number };
    basis: PolicyFinding[]; failed: string[]; needs_info: string[]; conditions: string[]; flags: Signal[];
  };
  confidence: number;
  documents: { missing: string[]; blocking: string[] };
};

export type RoutingRecommendation = {
  queue: Queue; queue_label: string; requires_human: boolean; priority: string; rationale: string[];
  auto_approve: boolean; human_decision?: Record<string, any>;
};

export type Report = {
  headline: string; summary: string; key_findings: { text: string; evidence_ids: string[]; tone: string }[];
  recommended_actions: string[]; handler_brief: string; claimant_message: { subject: string; body: string }; source: string;
};

export type Verification = {
  checks: { name: string; ok: boolean; detail: string }[]; gaps: string[]; confidence: number; loop: number; decision: string;
};

export type Triage = {
  form?: Record<string, unknown>; mode?: "llm" | "deterministic"; plan?: InvestigationPlan; facts?: Record<string, any>;
  ledger?: ToolResult[]; findings?: Signal[]; verification?: Verification; assessment?: RiskAssessment;
  routing?: RoutingRecommendation; report?: Report; actions?: { kind: string; summary: string }[];
  usage?: { input: number; output: number; calls: number }; pii_masked?: number; decision_ms?: number;
  finished?: { summary: string; open_questions: string[] };
};

export type Claim = {
  id: string; policy_no: string; line: "motor" | "health"; claim_type: string; incident_date: string; incident_time: string;
  reported_date: string; location: string; city: string; description: string; amount_claimed: number; status: ClaimStatus;
  severity: string | null; fraud_score: number | null; coverage_status: string | null; route: Queue | null;
  assigned_handler: string | null; triage: Triage; scenario: string | null; insured_member: string | null;
  triage_ms: number | null; garage_id: string | null; hospital_id: string | null; created_at: string;
};

export type ClaimDocument = {
  id: number; kind: string; label: string; filename: string; mime: string; meta: { fields?: Record<string, any> }; created_at: string;
};

export type Ticket = { id: string; queue: Queue; priority: string; sla_due: string; status: string; handler?: { id: string; name: string; role: string } | null };
export type Notification = { id: number; channel: string; recipient: string; subject: string; body: string; created_at: string };

export type ClaimDetail = {
  claim: Claim; policy: any; customer: { id: string; name: string; city: string; created_at: string } | null;
  documents: ClaimDocument[]; tickets: Ticket[]; notifications: Notification[]; garage: any; hospital: any; running: boolean;
};

export type ClaimRow = {
  id: string; policy_no: string; line: "motor" | "health"; claim_type: string; incident_date: string; city: string;
  amount_claimed: number; status: ClaimStatus; severity: string | null; fraud_score: number | null; coverage_status: string | null;
  route: Queue | null; scenario: string | null; triage_ms: number | null; created_at: string; handler_name?: string;
  queue_label?: string; claimant: string; confidence: number | null; summary: string | null; flags: string[];
  coverage_flags: string[]; missing_documents: string[]; requires_human: boolean; priority: string | null;
};

export type AgentEvent = { id: number; ts: string; type: string; node: string; payload: any };

export type Evidence = {
  evidence_id: string; key: string; claim_id: string; tool: string; label: string; category: string; stage: string;
  summary: string; status: "verified" | "contradictory" | "unverified" | "interpretation"; signals: Signal[];
  ms: number | null; data: any; input: any; auto: boolean;
};

export type AuditEvent = { id: string; claim_id: string; ts: string; category: string; actor: string; type: string; text: string };

export type HumanDecision = {
  id: number; claim_id: string; original_queue: string; decision: string; new_queue: string | null; reason: string;
  note: string; reviewer: string; created_at: string;
};

export type ServiceState = { state: "connected" | "degraded" | "unavailable" | "not_configured" | "disabled" | "mock" | "online"; detail: string };
export type SystemStatus = {
  agent: { state: string; mode: "llm" | "deterministic"; model: string | null; fast_model: string | null };
  services: Record<string, ServiceState>;
  data: { source: string; detail: string };
};

export type ForensicMetadata = {
  filename: string; document_id: number; taken_at?: string; lat?: number; lon?: number; camera?: string | null;
  software?: string | null; format?: string; dimensions?: string; bytes?: number; sha256?: string; phash?: string;
  exif_status: "present" | "missing"; days_from_incident?: number; km_from_incident?: number; flags: string[];
};

export type GraphNode = { id: string; kind: string; label: string; self: boolean; outcome: string | null };
export type ClaimRelationship = { source: string; target: string };

export type Scenario = { id: string; title: string; tag: string; blurb: string; status?: ClaimStatus; route?: Queue; has_upload?: boolean };

// ------------------------------------------------------------------ formatting
export const inr = (v?: number | null) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const n = Math.round(v);
  return (n < 0 ? "−" : "") + "₹" + Math.abs(n).toLocaleString("en-IN");
};
export const inrShort = (v?: number | null) => {
  if (v === null || v === undefined) return "—";
  if (Math.abs(v) >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (Math.abs(v) >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  return inr(v);
};
export const titleCase = (s?: string | null) => (s ?? "").replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
export const timeOf = (ts?: string) => (ts ? new Date(ts).toLocaleTimeString("en-IN", { hour12: false }) : "");
export const dateTime = (ts?: string) => (ts ? new Date(ts).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—");
export const bytes = (n?: number) => (n == null ? "—" : n > 1e6 ? `${(n / 1e6).toFixed(2)} MB` : `${(n / 1e3).toFixed(0)} KB`);
export const maskPolicy = (p?: string) => (p ? p.slice(0, 4) + "•".repeat(Math.max(0, p.length - 6)) + p.slice(-2) : "—");

export const QUEUE_LABEL: Record<Queue, string> = {
  fast_track: "Fast track", standard: "Standard review", senior: "Senior adjuster", medical: "Medical review",
  siu: "SIU / Fraud", coverage_review: "Coverage review",
};
export const STATUS_LABEL: Record<string, string> = {
  submitted: "Submitted", triaging: "Investigating", triaged: "Triaged", awaiting_review: "Human review",
  awaiting_documents: "Awaiting documents", assigned: "Assigned", approved: "Auto-approved", error: "Failed",
  interrupted: "Interrupted", closed: "Closed",
};
