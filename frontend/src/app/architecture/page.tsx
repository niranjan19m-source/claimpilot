import { ArrowDown, ArrowRight, CornerDownLeft } from "lucide-react";
import { Card, SectionTitle } from "@/components/legacy";

const NODES = [
  { k: "Intake", d: "Reads the form, documents and photos. Extracts structured facts (Claude Haiku). Masks PII." },
  { k: "Plan", d: "Chooses investigation depth and tools, and states the hypotheses to test (Claude, structured output). Guardrails force the mandatory steps." },
  { k: "Investigate", d: "Tool-use loop: calls tools in parallel, reads results, adapts, records cited facts and findings. Bounded tool budget." },
  { k: "Verify", d: "Deterministic critic. Checks required evidence, valid citations, and that coverage reflects the latest facts. Sends gaps back." },
  { k: "Decide", d: "Explainable scoring: noisy-OR fraud score, points-based severity, coverage ledger, routing policy." },
  { k: "Report", d: "Cited triage report, handler brief and claimant letter (Claude)." },
  { k: "Gates", d: "LangGraph interrupts: waits for missing documents (then re-plans) or for a human on SIU, denials or low confidence." },
  { k: "Act", d: "Creates the ticket, assigns by role, authority, region and caseload, sets the SLA, notifies, queues settlement." },
];

const TOOLS = [
  ["Policy admin lookup", "SQLite policy system"], ["Coverage rules engine", "clause-cited, line-by-line payable"],
  ["Policy wording search", "TF-IDF over wording"], ["Document review", "PDF extraction, checklist, cross-checks"],
  ["Image forensics", "EXIF time/GPS, editing software, perceptual hash"], ["Damage assessment", "Claude vision"],
  ["Historical weather", "Open-Meteo archive API (live)"], ["Geocoding", "gazetteer → OpenStreetMap Nominatim"],
  ["Vehicle registry", "VAHAN-style lookup (mocked)"], ["Claims history", "frequency, prior outcomes"],
  ["Entity link analysis", "NetworkX graph over phones, banks, garages"], ["Anomaly model", "Isolation Forest on genuine claims"],
  ["Ticketing & notify", "queue, SLA, handler, claimant"],
];

export default function Architecture() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">How ClaimPilot works</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          A LangGraph state machine with Claude at the reasoning steps and auditable code at the deciding steps.
          The LLM chooses what to investigate and interprets evidence. Rules turn evidence into scores. People sign off on denials and fraud.
        </p>
      </div>
      <Card>
        <SectionTitle>Agent graph</SectionTitle>
        <div className="grid gap-3 md:grid-cols-4">
          {NODES.map((n, i) => (
            <div key={n.k} className="relative rounded-xl border border-border bg-raised p-4">
              <div className="flex items-center gap-2"><span className="grid h-6 w-6 place-items-center rounded-full bg-indigo-500 text-[11px] font-semibold text-white">{i + 1}</span>
                <span className="font-semibold">{n.k}</span></div>
              <p className="mt-2 text-[13px] leading-relaxed text-zinc-300">{n.d}</p>
              {i % 4 !== 3 && <ArrowRight size={16} className="absolute -right-3 top-1/2 hidden -translate-y-1/2 text-muted-foreground md:block" />}
              {i === 3 && <CornerDownLeft size={16} className="absolute -bottom-3 left-1/2 hidden text-missing md:block" />}
              {i === 3 && <ArrowDown size={16} className="absolute -bottom-3 right-6 hidden text-muted-foreground md:block" />}
            </div>))}
        </div>
        <div className="mt-4 flex flex-wrap gap-4 text-xs text-muted-foreground">
          <span><b className="text-missing">Verify → Investigate</b> loop when evidence is missing (max 2)</span>
          <span><b className="text-missing">Gates → Intake</b> when documents arrive (full re-plan)</span>
          <span>State is check-pointed to SQLite: paused claims survive restarts</span>
        </div>
      </Card>
      <div className="grid gap-5 lg:grid-cols-3">
        <Card><SectionTitle>Claude decides</SectionTitle><ul className="space-y-1.5 text-[13px] text-zinc-300">
          <li>How deep to investigate, and why</li><li>Which tool next, and when to stop</li><li>What documents and photos actually say</li>
          <li>Facts and findings, each citing evidence ids</li><li>Report, handler brief, claimant letter</li></ul></Card>
        <Card><SectionTitle>Code decides</SectionTitle><ul className="space-y-1.5 text-[13px] text-zinc-300">
          <li>Coverage: every clause, every rupee</li><li>Fraud score: noisy-OR of flags, mandatory SIU indicators</li>
          <li>Severity points and routing matrix</li><li>Handler selection and SLA</li><li>Rejects uncited findings and facts</li></ul></Card>
        <Card><SectionTitle>People decide</SectionTitle><ul className="space-y-1.5 text-[13px] text-zinc-300">
          <li>Every SIU referral before action</li><li>Every coverage denial</li><li>Any decision below 60% agent confidence</li>
          <li>Overrides are logged to the audit trail</li></ul></Card>
      </div>
      <Card>
        <SectionTitle>Tool catalogue</SectionTitle>
        <div className="grid gap-x-8 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
          {TOOLS.map(([a, b]) => <div key={a} className="flex justify-between gap-3 border-b border-border py-1.5 text-[13px]"><span className="font-medium">{a}</span><span className="text-right text-muted-foreground">{b}</span></div>)}
        </div>
      </Card>
      <Card>
        <SectionTitle>Robustness &amp; responsible AI</SectionTitle>
        <div className="grid gap-4 text-[13px] text-zinc-300 md:grid-cols-2">
          <ul className="space-y-1.5"><li><b>PII masking:</b> phones, emails, PAN, Aadhaar and names become stable pseudonyms before any LLM call, so link analysis still works.</li>
            <li><b>Graceful degradation:</b> a failed tool lowers confidence rather than crashing the run. An LLM outage falls back to the rules plan.</li>
            <li><b>Bounded autonomy:</b> tool budget, verify-loop cap, recursion limit, and refusal fallbacks on the API.</li></ul>
          <ul className="space-y-1.5"><li><b>Audit trail:</b> every plan, tool call, finding, decision and human action is an immutable event.</li>
            <li><b>Explainability:</b> each fraud point maps to a flag, each flag to evidence, and each coverage decision to a clause.</li>
            <li><b>Never accuses:</b> claimant letters carry no fraud language. Indicators go to investigators only.</li></ul>
        </div>
      </Card>
    </div>
  );
}
