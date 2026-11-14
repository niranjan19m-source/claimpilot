"use client";

import { BookOpenText, FileWarning, Lightbulb, Route, ShieldAlert, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { EvidenceChip, Panel, Tag, Tone } from "@/components/common";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { ClaimDetail, PolicyFinding } from "@/lib/api";

const WORDING_FILE: Record<string, string> = { M: "motor_comprehensive.md", H: "health_floater.md" };

/** A clause citation that opens the exact passage from the policy wording file. */
function ClauseCitation({ f, evidenceId }: { f: PolicyFinding; evidenceId?: string }) {
  return (
    <HoverCard openDelay={120}>
      <HoverCardTrigger asChild>
        <button className="inline-flex items-center gap-1 rounded bg-white/[0.06] px-1.5 py-px font-mono text-[10.5px] text-zinc-200 ring-1 ring-inset ring-white/10 hover:bg-white/10">
          <BookOpenText size={10} /> {f.clause_id}
        </button>
      </HoverCardTrigger>
      <HoverCardContent className="w-96 text-[12px]">
        <div className="flex items-center justify-between gap-2">
          <span className="font-semibold">{f.clause_id} · {f.title}</span>
          <Tag tone={f.outcome === "fail" ? "risk" : f.outcome === "needs_info" ? "missing" : f.outcome === "applied" ? "info" : "verified"}>{f.outcome.replace("_", " ")}</Tag>
        </div>
        <blockquote className="mt-2 border-l-2 border-indigo-400/60 pl-3 leading-relaxed text-zinc-300">{f.text || "Clause text not available."}</blockquote>
        <dl className="mt-2.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 border-t pt-2 text-[11px] text-zinc-500">
          <dt>Source document</dt><dd className="font-mono text-zinc-400">{WORDING_FILE[f.clause_id[0]] ?? "policy wording"}</dd>
          <dt>Page</dt><dd>Not applicable (structured wording, clause-addressed)</dd>
          <dt>Extracted by</dt><dd>Coverage rules engine{evidenceId ? ` (${evidenceId})` : ""}</dd>
          <dt>Status</dt><dd>Verbatim text from the policy file. The engine&apos;s note is the interpretation.</dd>
        </dl>
      </HoverCardContent>
    </HoverCard>
  );
}

function Flag({ tone, kind, title, children, cites }: { tone: Tone; kind: string; title: string; children: ReactNode; cites?: ReactNode }) {
  return (
    <li className="rounded-lg border bg-raised p-3">
      <div className="flex items-start justify-between gap-2">
        <span className="text-[12.5px] font-medium text-zinc-100">{title}</span>
        <Tag tone={tone}>{kind}</Tag>
      </div>
      <div className="mt-1 text-[12px] leading-relaxed text-zinc-400">{children}</div>
      {cites && <div className="mt-1.5 flex flex-wrap items-center gap-1">{cites}</div>}
    </li>
  );
}

function Section({ icon, title, count, children }: { icon: ReactNode; title: string; count?: number; children: ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-zinc-500">{icon}{title}{count !== undefined && <span className="text-zinc-600">({count})</span>}</h3>
      {children}
    </div>
  );
}

/** RIGHT PANE — why ClaimPilot reached its recommendation, with every flag linked to evidence. */
export function WhyPane({ detail, openEvidence }: { detail: ClaimDetail; openEvidence: (id: string) => void }) {
  const t = detail.claim.triage ?? {}, a = t.assessment, rt = t.routing;
  if (!a || !rt) return <Panel title="The why"><p className="text-[13px] text-muted-foreground">Explanations appear after the agent decides.</p></Panel>;
  const ledger = Object.fromEntries((t.ledger ?? []).map((e) => [e.id, e]));
  const covId = (t.ledger ?? []).filter((e) => e.tool === "check_coverage").at(-1)?.id;
  const toolSignals = a.fraud.signals.filter((s) => s.source !== "agent");
  const agentFindings = (t.findings ?? []);
  const coverage = a.coverage.basis.filter((b) => b.outcome !== "pass");
  const verifiedCount = (t.ledger ?? []).filter((e) => e.ok && !e.signals.length).length;

  return (
    <Panel title="The why · explainability" bodyClass="space-y-5">
      <div className="flex flex-wrap gap-1.5 text-[10.5px]">
        <Tag tone="verified">Verified fact</Tag><Tag tone="info">Agent interpretation</Tag><Tag tone="neutral">Unverified claim</Tag><Tag tone="risk">Contradictory evidence</Tag>
      </div>

      <Section icon={<Lightbulb size={12} />} title="Recommended next action">
        <div className="rounded-lg border border-info-line bg-info-bg p-3 text-[12.5px] text-zinc-200">
          {t.report?.recommended_actions?.[0] ?? rt.rationale[0]}
          {(t.report?.recommended_actions?.length ?? 0) > 1 && (
            <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-[12px] text-zinc-400">{t.report!.recommended_actions.slice(1, 4).map((x) => <li key={x}>{x}</li>)}</ul>
          )}
          <div className="mt-1.5 text-[10.5px] text-zinc-500">{t.report?.source === "llm" ? "Drafted by Claude from the evidence ledger" : "Generated by the routing policy"} · agent interpretation</div>
        </div>
      </Section>

      <Section icon={<ShieldAlert size={12} />} title="Risk indicators" count={toolSignals.length}>
        {toolSignals.length ? (
          <ul className="space-y-2">
            {toolSignals.map((s) => (
              <Flag key={s.code} tone="risk" kind="Contradictory evidence" title={s.label}
                cites={<>{s.evidence?.map((e) => <EvidenceChip key={e} id={e} entry={ledger[e]} onOpen={openEvidence} />)}<span className="font-mono text-[10.5px] text-zinc-500">+{s.weight} pts</span></>}>
                {s.detail}
              </Flag>
            ))}
          </ul>
        ) : <p className="rounded-md bg-verified-bg px-3 py-2 text-[12px] text-verified">No check raised a risk indicator. {verifiedCount} checks returned verified results.</p>}
        {toolSignals.some((s) => s.code.startsWith("EXIF")) && (
          <p className="mt-2 text-[11px] leading-relaxed text-zinc-500">Photo metadata can be missing, edited, or reset by messaging apps. An EXIF discrepancy is a lead to investigate, not proof of fraud.</p>
        )}
      </Section>

      {agentFindings.length > 0 && (
        <Section icon={<Sparkles size={12} />} title="Agent findings" count={agentFindings.length}>
          <ul className="space-y-2">{agentFindings.map((f) => (
            <Flag key={f.code} tone="info" kind="Agent interpretation" title={f.label}
              cites={f.evidence?.map((e) => <EvidenceChip key={e} id={e} entry={ledger[e]} onOpen={openEvidence} />)}>{f.detail}</Flag>
          ))}</ul>
        </Section>
      )}

      <Section icon={<BookOpenText size={12} />} title="Coverage findings" count={coverage.length}>
        {coverage.length ? (
          <ul className="space-y-2">
            {coverage.map((b, i) => (
              <Flag key={i} tone={b.outcome === "fail" ? "risk" : b.outcome === "needs_info" ? "missing" : "info"}
                kind={b.outcome === "fail" ? "Coverage issue" : b.outcome === "needs_info" ? "Needs information" : "Adjustment"}
                title={b.title} cites={<><ClauseCitation f={b} evidenceId={covId} />{covId && <EvidenceChip id={covId} entry={ledger[covId]} onOpen={openEvidence} />}</>}>
                {b.note}
              </Flag>
            ))}
          </ul>
        ) : <p className="text-[12px] text-zinc-500">All applicable clauses passed.</p>}
      </Section>

      {(a.documents.missing.length > 0 || a.coverage.conditions.length > 0) && (
        <Section icon={<FileWarning size={12} />} title="Missing information">
          <ul className="space-y-1.5 text-[12.5px]">
            {a.documents.missing.map((m) => <li key={m} className="flex items-center justify-between gap-2"><span className="text-zinc-300">{m}</span>
              <Tag tone="missing">{a.documents.blocking.includes(m) ? "Blocking" : "Requested"}</Tag></li>)}
            {a.coverage.conditions.map((m) => <li key={m} className="text-[12px] text-missing">{m}</li>)}
          </ul>
        </Section>
      )}

      <Section icon={<Route size={12} />} title="Routing rationale">
        <ol className="space-y-1.5 text-[12.5px] text-zinc-300">
          {rt.rationale.map((r, i) => <li key={i} className="flex gap-2"><span className="font-mono text-[11px] text-zinc-600">{i + 1}.</span>{r}</li>)}
        </ol>
        <p className="mt-2 text-[11px] text-zinc-500">Routing is computed by an explicit policy (backend/app/tools/decision.py), not by the language model.</p>
      </Section>
    </Panel>
  );
}
