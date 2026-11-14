"use client";

import { ArrowLeft, Loader2, Mail, MessageSquare, Radar, RotateCcw, Send, Smartphone } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { TraceTerminal } from "@/components/agent/trace";
import { PlanPanel, WorkflowStepper } from "@/components/agent/workflow";
import { DecisionCenter } from "@/components/claim/decision-center";
import { EvidenceSheet } from "@/components/claim/evidence-sheet";
import { GroundTruthPane } from "@/components/claim/ground-truth";
import { SynthesisPane } from "@/components/claim/synthesis";
import { WhyPane } from "@/components/claim/why";
import { EmptyState, ErrorState, EvidenceChip, Panel, SkeletonRows, Tag, statusTone } from "@/components/common";
import { ImageForensicsPanel } from "@/components/fraud/forensics";
import { RelationshipGraph } from "@/components/fraud/relationship-graph";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useClaimStream } from "@/hooks/use-claim-stream";
import { ClaimDetail, STATUS_LABEL, ToolResult, dateTime, inr, postJSON, titleCase, READ_ONLY } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function ClaimWorkspace() {
  const { id } = useParams<{ id: string }>();
  const { detail, events, error, stream, refresh, resetEvents } = useClaimStream(id);
  const [evidence, setEvidence] = useState<ToolResult | null>(null);
  const [pane, setPane] = useState<"truth" | "synthesis" | "why">("synthesis");
  const [rerunning, setRerunning] = useState(false);

  if (error && !detail) return <ErrorState title="Could not load claim" message={error} onRetry={refresh} />;
  if (!detail) return (
    <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)_380px]">
      <Skeleton className="h-[640px] rounded-xl" /><div className="space-y-4"><Skeleton className="h-40 rounded-xl" /><SkeletonRows rows={8} /></div><Skeleton className="h-[640px] rounded-xl" />
    </div>
  );

  const c = detail.claim, t = c.triage ?? {};
  const ledger = t.ledger ?? [];
  const running = detail.running || c.status === "triaging";
  const openEvidence = (eid: string) => { const e = ledger.find((x) => x.id === eid); if (e) setEvidence(e); };
  const last = (tool: string) => [...ledger].reverse().find((e) => e.tool === tool) ?? null;
  const rerun = async () => {
    setRerunning(true); resetEvents();
    try { await postJSON(`/api/claims/${id}/run`); refresh(); toast.success("Investigation restarted"); }
    catch (e: any) { toast.error(e.message); } finally { setRerunning(false); }
  };

  return (
    <div className="mx-auto max-w-[1760px] space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link href="/claims" className="inline-flex items-center gap-1 text-[12px] text-zinc-500 hover:text-zinc-200"><ArrowLeft size={13} /> Claims queue</Link>
          <div className="mt-1 flex flex-wrap items-center gap-2.5">
            <h1 className="text-xl font-semibold tracking-tight">{titleCase(c.claim_type)} · {inr(c.amount_claimed)}</h1>
            <Tag tone={statusTone(c.status)}>{running && <Loader2 size={10} className="animate-spin" />}{STATUS_LABEL[c.status] ?? c.status}</Tag>
            {t.mode && <Tag>{t.mode === "llm" ? "LLM agent" : "Deterministic mode"}</Tag>}
          </div>
          <div className="mt-0.5 text-[12.5px] text-zinc-500"><span className="font-mono">{c.id}</span> · {c.location}, {c.city} · loss {c.incident_date}</div>
        </div>
        <div className="flex gap-2">
          <Link href={`/investigations/${id}`}><Button variant="outline"><Radar size={14} className={running ? "cp-pulse" : ""} /> Live investigation</Button></Link>
          <Button variant="outline" onClick={rerun} disabled={running || rerunning || READ_ONLY}>{running || rerunning ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />} {c.status === "submitted" ? "Investigate" : "Re-run"}</Button>
        </div>
      </div>

      {/* pane switcher for screens narrower than the 3-pane layout */}
      <div role="tablist" aria-label="Workspace panes" className="flex gap-1 rounded-lg border bg-card p-1 xl:hidden">
        {(["truth", "synthesis", "why"] as const).map((p) => (
          <button key={p} role="tab" aria-selected={pane === p} onClick={() => setPane(p)}
            className={cn("flex-1 rounded-md py-1.5 text-[12.5px]", pane === p ? "bg-white/[0.08] font-medium text-white" : "text-zinc-400")}>
            {{ truth: "Ground truth", synthesis: "Agent synthesis", why: "The why" }[p]}
          </button>
        ))}
      </div>

      <div className="grid items-start gap-4 xl:grid-cols-[340px_minmax(0,1fr)_390px]">
        <div className={cn("space-y-4 xl:sticky xl:top-[72px]", pane !== "truth" && "hidden xl:block")}>
          <GroundTruthPane detail={detail} onUploaded={refresh} />
        </div>

        <div className={cn("min-w-0", pane !== "synthesis" && "hidden xl:block")}>
          <Tabs defaultValue="synthesis">
            <TabsList className="mb-3 flex w-full justify-start overflow-x-auto">
              <TabsTrigger value="synthesis">Synthesis</TabsTrigger>
              <TabsTrigger value="trace">Agent trace {running && <span className="ml-1 h-1.5 w-1.5 rounded-full bg-indigo-400 cp-pulse" />}</TabsTrigger>
              <TabsTrigger value="forensics">Forensics</TabsTrigger>
              <TabsTrigger value="graph">Relationships</TabsTrigger>
              <TabsTrigger value="evidence">Evidence ({ledger.length})</TabsTrigger>
              <TabsTrigger value="comms">Report &amp; letters</TabsTrigger>
            </TabsList>
            <TabsContent value="synthesis"><SynthesisPane detail={detail} openEvidence={openEvidence} /></TabsContent>
            <TabsContent value="trace" className="space-y-4">
              <div className="grid gap-4 2xl:grid-cols-[280px_minmax(0,1fr)]">
                <Panel title="Workflow"><WorkflowStepper events={events} status={c.status} /></Panel>
                <TraceTerminal events={events} stream={stream} claimId={c.id} running={running} onOpenEvidence={openEvidence} height={460} />
              </div>
              <Panel title="Investigation plan"><PlanPanel plan={t.plan} events={events} ledger={ledger} onOpen={openEvidence} /></Panel>
            </TabsContent>
            <TabsContent value="forensics">
              <ImageForensicsPanel entry={last("photo_forensics")} incidentDate={c.incident_date} policyStart={detail.policy?.start_date} />
            </TabsContent>
            <TabsContent value="graph"><RelationshipGraph entry={last("network_analysis")} /></TabsContent>
            <TabsContent value="evidence">
              {ledger.length === 0 ? <EmptyState title="No evidence collected yet" body="Evidence appears as the agent calls tools." /> : (
                <div className="divide-y rounded-xl border bg-card">
                  {ledger.map((e) => (
                    <button key={e.id} onClick={() => setEvidence(e)} className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-white/[0.03]">
                      <span className="w-8 shrink-0 font-mono text-[12px] text-info">{e.id}</span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2 text-[13px] font-medium">{e.label}
                          <Tag tone={!e.ok ? "missing" : e.signals.length ? "risk" : "verified"}>{!e.ok ? "Unverified" : e.signals.length ? "Contradictory" : "Verified"}</Tag></div>
                        <div className="mt-0.5 text-[12.5px] text-zinc-400">{e.summary}</div>
                      </div>
                      <span className="font-mono text-[11px] text-zinc-600">{e.ms}ms</span>
                    </button>
                  ))}
                </div>
              )}
            </TabsContent>
            <TabsContent value="comms"><Communications detail={detail} openEvidence={openEvidence} /></TabsContent>
          </Tabs>
        </div>

        <div className={cn("space-y-4", pane !== "why" && "hidden xl:block")}>
          <DecisionCenter detail={detail} onChanged={refresh} openEvidence={openEvidence} />
          <WhyPane detail={detail} openEvidence={openEvidence} />
        </div>
      </div>

      <EvidenceSheet entry={evidence} claimId={c.id} onClose={() => setEvidence(null)} />
    </div>
  );
}

function Communications({ detail, openEvidence }: { detail: ClaimDetail; openEvidence: (id: string) => void }) {
  const r = detail.claim.triage?.report;
  const ledger = Object.fromEntries((detail.claim.triage?.ledger ?? []).map((e) => [e.id, e]));
  return (
    <div className="grid gap-4 2xl:grid-cols-2">
      <Panel title="Triage report" action={r && <Tag>{r.source === "llm" ? "Drafted by Claude · agent interpretation" : "Template"}</Tag>}>
        {!r ? <p className="text-[13px] text-muted-foreground">The report is written after the decision.</p> : (
          <div className="space-y-3 text-[13px]">
            <div className="text-[14px] font-semibold">{r.headline}</div>
            <p className="leading-relaxed text-zinc-300">{r.summary}</p>
            <ul className="space-y-1.5">{r.key_findings.map((f, i) => (
              <li key={i} className="flex gap-2 leading-relaxed text-zinc-300">
                <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", f.tone === "concern" ? "bg-rose-400" : f.tone === "positive" ? "bg-emerald-400" : "bg-zinc-500")} />
                <span>{f.text} {f.evidence_ids.map((e) => <EvidenceChip key={e} id={e} entry={ledger[e]} onOpen={openEvidence} />)}</span>
              </li>))}</ul>
          </div>
        )}
      </Panel>
      <Panel title="Outbound communications">
        {detail.notifications.length === 0 ? <EmptyState title="Nothing sent yet" body="Messages go out when the claim is assigned or documents are requested." /> : (
          <ul className="space-y-2.5">{detail.notifications.map((n) => (
            <li key={n.id} className="rounded-lg border bg-raised p-3">
              <div className="flex items-center gap-1.5 text-[11px] text-zinc-500">
                {n.channel === "sms" ? <Smartphone size={12} /> : n.channel === "email" ? <Mail size={12} /> : <MessageSquare size={12} />}
                <span className="uppercase">{n.channel}</span> · {n.recipient} · {dateTime(n.created_at)}
              </div>
              <div className="mt-1 text-[13px] font-medium">{n.subject}</div>
              <p className="mt-1 whitespace-pre-line text-[12px] leading-relaxed text-zinc-400">{n.body}</p>
            </li>))}</ul>
        )}
      </Panel>
      <div className="2xl:col-span-2"><Copilot id={detail.claim.id} /></div>
    </div>
  );
}

function Copilot({ id }: { id: string }) {
  const [q, setQ] = useState("");
  const [log, setLog] = useState<{ q: string; a?: string; src?: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const ask = async (question: string) => {
    if (!question.trim()) return;
    setBusy(true); setLog((l) => [...l, { q: question }]); setQ("");
    try {
      const r = await postJSON<{ answer: string; source: string }>(`/api/claims/${id}/ask`, { question });
      setLog((l) => l.map((x, i) => (i === l.length - 1 ? { ...x, a: r.answer, src: r.source } : x)));
    } catch (e: any) { setLog((l) => l.map((x, i) => (i === l.length - 1 ? { ...x, a: `Error: ${e.message}` } : x))); }
    finally { setBusy(false); }
  };
  return (
    <Panel title="Adjuster copilot · ask about this claim">
      <div className="space-y-3">
        {log.map((m, i) => (
          <div key={i} className="space-y-1.5">
            <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-indigo-500/90 px-3.5 py-2 text-[13px] text-white">{m.q}</div>
            <div className="w-fit max-w-[92%] whitespace-pre-line rounded-2xl rounded-bl-sm bg-raised px-3.5 py-2.5 text-[13px] leading-relaxed text-zinc-300 ring-1 ring-white/10">
              {m.a ?? <Loader2 size={14} className="animate-spin" />}
              {m.src && <div className="mt-1 text-[10.5px] text-zinc-500">{m.src === "llm" ? "Answered by Claude from the triage record" : "LLM disabled: keyword retrieval over evidence"}</div>}
            </div>
          </div>))}
        {log.length === 0 && !READ_ONLY && <div className="flex flex-wrap gap-2">{["Why was this routed here?", "What evidence would change the decision?", "Summarise the coverage position."].map((s) =>
          <button key={s} onClick={() => ask(s)} className="rounded-full border px-3 py-1.5 text-[12.5px] text-zinc-400 hover:bg-white/5">{s}</button>)}</div>}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); ask(q); }} className="mt-3 flex gap-2">
        <Input value={q} onChange={(e) => setQ(e.target.value)} disabled={READ_ONLY} placeholder={READ_ONLY ? "Copilot needs the live backend; disabled in the hosted demo" : "Ask a question about this claim…"} aria-label="Question" />
        <Button type="submit" size="icon" disabled={busy} aria-label="Send"><Send size={14} /></Button>
      </form>
    </Panel>
  );
}
