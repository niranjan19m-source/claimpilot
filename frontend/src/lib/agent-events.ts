// Maps raw backend events (see backend/app/events.py emitters) onto the
// glassbox vocabulary: actors, canonical event names and the 10 workflow stages.
// Nothing here invents progress: every stage state is derived from events received.

import type { AgentEvent } from "./api";

export type Actor = "SYSTEM" | "PLANNER" | "TOOL" | "RESULT" | "AGENT" | "VERIFIER" | "SCORER" | "ROUTER" | "REPORTER"
  | "HUMAN" | "ACTION" | "CLAIMANT" | "ERROR";

/** Canonical names (claim.received, tool.completed …) for each backend event type. */
export function describe(e: AgentEvent): { actor: Actor; name: string; text: string; tone: "neutral" | "info" | "ok" | "risk" | "warn" } {
  const p = e.payload ?? {};
  switch (e.type) {
    case "run_started": return { actor: "SYSTEM", name: "claim.received", text: `Investigation started (${p.mode === "llm" ? `LLM agent · ${p.model}` : "deterministic rules mode"})`, tone: "info" };
    case "intake": return { actor: "SYSTEM", name: "claim.structured", text: `Claim structured; ${Object.keys(p.facts ?? {}).length} facts derived`, tone: "neutral" };
    case "plan": return { actor: "PLANNER", name: "plan.created", text: `${cap(p.depth)} investigation plan: ${p.steps?.length ?? 0} steps (${p.source === "llm" ? "planned by Claude" : "rules baseline"})`, tone: "info" };
    case "tool_call": return { actor: "TOOL", name: "tool.started", text: `${p.label} invoked`, tone: "neutral" };
    case "tool_result": return {
      actor: "RESULT", name: p.ok ? "tool.completed" : "tool.failed",
      text: `${p.label}: ${p.summary}`, tone: !p.ok ? "warn" : p.signals?.length ? "risk" : "ok",
    };
    case "thought": return { actor: "AGENT", name: "agent.summary", text: p.text, tone: "neutral" };
    case "fact": return { actor: "AGENT", name: "evidence.created", text: `Fact recorded: ${p.key} = ${String(p.value)}`, tone: "info" };
    case "finding": return { actor: "AGENT", name: "discrepancy.detected", text: `${p.label}: ${p.detail}`, tone: "risk" };
    case "verify": return {
      actor: "VERIFIER", name: "verification.completed",
      text: p.gaps?.length ? `Evidence gaps found: ${p.gaps.join(", ")}. Returning to investigation.` : `All checks passed; confidence ${Math.round((p.confidence ?? 0) * 100)}%`,
      tone: p.gaps?.length ? "warn" : "ok",
    };
    case "assessment": return { actor: "SCORER", name: "risk.assessed", text: `Fraud ${p.fraud?.score} (${p.fraud?.band}) · severity ${p.severity?.level} · coverage ${String(p.coverage?.status ?? "").replace(/_/g, " ")}`, tone: p.fraud?.band === "high" ? "risk" : "info" };
    case "routing": return { actor: "ROUTER", name: "routing.recommended", text: `Recommend ${p.queue_label} (${p.priority})${p.requires_human ? " — human sign-off required" : ""}`, tone: p.queue === "siu" ? "risk" : p.queue === "fast_track" ? "ok" : "info" };
    case "report": return { actor: "REPORTER", name: "report.drafted", text: p.headline, tone: "neutral" };
    case "interrupt": return p.kind === "documents"
      ? { actor: "SYSTEM", name: "documents.required", text: `Paused — waiting for ${p.missing?.join(", ")}`, tone: "warn" }
      : { actor: "SYSTEM", name: "human.review.required", text: "Paused — waiting for an adjuster decision", tone: "warn" };
    case "resume": return p.kind === "documents"
      ? { actor: "CLAIMANT", name: "documents.received", text: "Documents received; re-planning investigation", tone: "info" }
      : { actor: "HUMAN", name: "human.decision", text: `${cap(String(p.decision ?? "").replace(/_/g, " "))}${p.queue ? ` → ${p.queue}` : ""}${p.reason || p.note ? `: ${p.reason || p.note}` : ""} (${p.reviewer ?? "adjuster"})`, tone: "info" };
    case "document_received": return { actor: "CLAIMANT", name: "document.uploaded", text: `${p.label}: ${p.filename}`, tone: "neutral" };
    case "action": return { actor: "ACTION", name: `action.${p.kind}`, text: p.summary, tone: "ok" };
    case "run_completed": return { actor: "SYSTEM", name: "investigation.completed", text: `Investigation completed (${p.status}) in ${((p.decision_ms ?? 0) / 1000).toFixed(1)}s to decision`, tone: "ok" };
    case "paused": return { actor: "SYSTEM", name: "run.paused", text: `Run paused (${p.kind})`, tone: "warn" };
    case "warning": return { actor: "SYSTEM", name: "run.degraded", text: p.message, tone: "warn" };
    case "error": return { actor: "ERROR", name: "run.failed", text: p.message, tone: "risk" };
    default: return { actor: "SYSTEM", name: e.type, text: JSON.stringify(p).slice(0, 120), tone: "neutral" };
  }
}

const cap = (s?: string) => (s ? s[0].toUpperCase() + s.slice(1) : "");

// ------------------------------------------------------------------ workflow stages
export type StageState = "pending" | "running" | "completed" | "failed" | "review" | "skipped";
export type Stage = { key: string; label: string; state: StageState; started?: string; ended?: string; note?: string };

const STAGE_TOOLS: Record<string, string[]> = {
  policy: ["lookup_policy", "check_coverage", "search_policy_wording"],
  external: ["geocode_location", "check_weather", "vehicle_registry", "assess_damage_photos"],
  fraud: ["photo_forensics", "claims_history", "network_analysis", "anomaly_model"],
  extraction: ["review_documents", "read_document"],
};

export const STAGE_DEFS = [
  { key: "intake", label: "Claim intake" },
  { key: "extraction", label: "Data extraction" },
  { key: "plan", label: "Investigation planning" },
  { key: "policy", label: "Policy verification" },
  { key: "external", label: "External investigation" },
  { key: "fraud", label: "Fraud analysis" },
  { key: "verify", label: "Evidence verification" },
  { key: "risk", label: "Risk assessment" },
  { key: "routing", label: "Claim routing" },
  { key: "human", label: "Human review" },
];

/** Derive each stage's state from the events actually received for the current run. */
export function deriveStages(all: AgentEvent[], claimStatus?: string): Stage[] {
  // Only the latest run (after the last intake re-entry) counts for stages 2+.
  const lastIntake = [...all].reverse().findIndex((e) => e.type === "node" && e.node === "intake" && e.payload?.status === "start");
  const events = lastIntake >= 0 ? all.slice(all.length - 1 - lastIntake) : all;
  const s: Record<string, Stage> = Object.fromEntries(STAGE_DEFS.map((d) => [d.key, { ...d, state: "pending" as StageState }]));
  const touch = (k: string, state: StageState, ts: string) => {
    const st = s[k];
    if (!st.started) st.started = ts;
    st.ended = ts;
    st.state = state;
  };
  const plannedTools = new Set<string>(
    (events.find((e) => e.type === "plan")?.payload?.steps ?? []).map((x: any) => x.tool));
  for (const e of all) if (e.type === "run_started") touch("intake", "running", e.ts);
  for (const e of events) {
    const p = e.payload ?? {};
    if (e.type === "intake") touch("intake", "completed", e.ts);
    if (e.type === "node" && e.node === "plan" && p.status === "start") touch("plan", "running", e.ts);
    if (e.type === "plan") touch("plan", "completed", e.ts);
    if (e.type === "tool_call" || e.type === "tool_result") {
      for (const [k, tools] of Object.entries(STAGE_TOOLS)) {
        if (!tools.includes(p.tool)) continue;
        touch(k, e.type === "tool_call" ? "running" : "running", e.ts);
      }
    }
    if (e.type === "node" && e.node === "verify" && p.status === "start") touch("verify", "running", e.ts);
    if (e.type === "verify") touch("verify", "completed", e.ts);
    if (e.type === "assessment") touch("risk", "completed", e.ts);
    if (e.type === "routing") { touch("routing", "completed", e.ts); if (!p.requires_human) { s.human.state = "skipped"; s.human.note = "Not required by policy"; } }
    if (e.type === "interrupt") touch("human", "review", e.ts);
    if (e.type === "resume" && p.kind === "human_review") touch("human", "completed", e.ts);
    if (e.type === "error") {
      const running = Object.values(s).find((x) => x.state === "running");
      if (running) { running.state = "failed"; running.note = p.message; }
    }
  }
  // Tool stages complete once verification has started; mark unplanned stages as skipped.
  const verified = events.some((e) => e.type === "node" && e.node === "verify");
  for (const k of ["extraction", "policy", "external", "fraud"]) {
    if (s[k].state === "running" && verified) s[k].state = "completed";
    if (s[k].state === "pending" && verified && !STAGE_TOOLS[k].some((t) => plannedTools.has(t))) {
      s[k].state = "skipped"; s[k].note = "Not in plan for this claim";
    }
  }
  const docsPause = events.some((e) => e.type === "interrupt" && e.payload?.kind === "documents") && claimStatus === "awaiting_documents";
  if (docsPause) { s.human.state = "review"; s.human.note = "Waiting for claimant documents"; }
  return STAGE_DEFS.map((d) => s[d.key]);
}

/** Pairs tool_call with its tool_result so the detail view can show input, output and duration together. */
export function toolPairs(events: AgentEvent[]) {
  const calls = new Map<string, AgentEvent>();
  const out = new Map<string, { call?: AgentEvent; result?: AgentEvent }>();
  for (const e of events) {
    const id = e.payload?.evidence_id;
    if (!id) continue;
    if (e.type === "tool_call") { calls.set(id, e); out.set(id, { call: e }); }
    if (e.type === "tool_result") out.set(id, { call: calls.get(id), result: e });
  }
  return out;
}

export const TOOL_SOURCE: Record<string, string> = {
  lookup_policy: "Policy administration DB (SQLite, synthetic)",
  check_coverage: "Coverage rules engine (backend/app/tools/coverage.py) + policy wording",
  search_policy_wording: "Policy wording index (TF-IDF)",
  review_documents: "Submitted documents (pypdf extraction)",
  read_document: "Submitted document text",
  geocode_location: "Offline gazetteer → OpenStreetMap Nominatim",
  check_weather: "Open-Meteo Historical Weather API (archive-api.open-meteo.com)",
  vehicle_registry: "Simulated VAHAN registry (mock)",
  photo_forensics: "EXIF metadata + local perceptual-hash index of past claim photos",
  assess_damage_photos: "Claude vision (only in LLM mode)",
  claims_history: "Claims database (synthetic history)",
  network_analysis: "Entity graph over claims database (NetworkX)",
  anomaly_model: "Isolation Forest trained on historical genuine claims",
};
