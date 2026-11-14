"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, ExternalLink, Globe, Loader2, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { TraceTerminal } from "@/components/agent/trace";
import { PlanPanel, WorkflowStepper } from "@/components/agent/workflow";
import { EvidenceSheet } from "@/components/claim/evidence-sheet";
import { EmptyState, ErrorState, Panel, Tag, fraudLabel, fraudTone, statusTone } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useClaimStream } from "@/hooks/use-claim-stream";
import { STATUS_LABEL, ToolResult, inr, postJSON, titleCase } from "@/lib/api";
import { TOOL_SOURCE } from "@/lib/agent-events";

const EXTERNAL = new Set(["check_weather", "geocode_location"]);

export default function LiveInvestigation() {
  const { id } = useParams<{ id: string }>();
  const { detail, events, error, stream, refresh, resetEvents } = useClaimStream(id);
  const [evidence, setEvidence] = useState<ToolResult | null>(null);
  const [busy, setBusy] = useState(false);

  // Evidence activity from the stream itself (works mid-run, before the ledger is persisted).
  const results = useMemo(() => events.filter((e) => e.type === "tool_result"), [events]);
  if (error && !detail) return <ErrorState title="Could not load investigation" message={error} onRetry={refresh} />;
  if (!detail) return <div className="grid gap-4 xl:grid-cols-[300px_1fr_340px]"><Skeleton className="h-[600px] rounded-xl" /><Skeleton className="h-[600px] rounded-xl" /><Skeleton className="h-[600px] rounded-xl" /></div>;

  const c = detail.claim, t = c.triage ?? {};
  const running = detail.running || c.status === "triaging";
  const ledger = t.ledger ?? [];
  const plan = t.plan ?? events.filter((e) => e.type === "plan").at(-1)?.payload;
  const assessment = t.assessment ?? events.filter((e) => e.type === "assessment").at(-1)?.payload;
  const routing = t.routing ?? events.filter((e) => e.type === "routing").at(-1)?.payload;
  const open = (eid: string) => { const e = ledger.find((x) => x.id === eid); if (e) setEvidence(e); else toast.info("Evidence detail is available once the step is persisted."); };
  const start = async () => {
    setBusy(true); resetEvents();
    try { await postJSON(`/api/claims/${id}/run`); refresh(); } catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="mx-auto max-w-[1760px] space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href="/investigations" className="inline-flex items-center gap-1 text-[12px] text-zinc-500 hover:text-zinc-200"><ArrowLeft size={13} /> Live investigations</Link>
          <div className="mt-1 flex flex-wrap items-center gap-2.5">
            <h1 className="text-xl font-semibold tracking-tight">{titleCase(c.claim_type)} · {inr(c.amount_claimed)}</h1>
            <Tag tone={statusTone(c.status)}>{running && <Loader2 size={10} className="animate-spin" />}{STATUS_LABEL[c.status]}</Tag>
          </div>
          <div className="mt-0.5 text-[12.5px] text-zinc-500"><span className="font-mono">{c.id}</span> · {c.location}, {c.city}</div>
        </div>
        <div className="flex gap-2">
          <Link href={`/claims/${id}`}><Button variant="outline">Open workspace</Button></Link>
          <Button onClick={start} disabled={running || busy}>{running || busy ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />} {c.status === "submitted" ? "Start investigation" : "Re-run"}</Button>
        </div>
      </div>

      <div className="grid items-start gap-4 xl:grid-cols-[310px_minmax(0,1fr)_350px]">
        <div className="space-y-4">
          <Panel title="Workflow"><WorkflowStepper events={events} status={c.status} /></Panel>
          <Panel title="Investigation plan">
            {plan ? <PlanPanel plan={plan} events={events} ledger={ledger} onOpen={open} /> : running ? <div className="space-y-2"><Skeleton className="h-4 w-2/3" /><Skeleton className="h-16" /><Skeleton className="h-24" /></div>
              : <EmptyState title="No plan yet" body="Start the investigation to generate a plan." />}
          </Panel>
        </div>

        <div className="min-w-0 space-y-4">
          <TraceTerminal events={events} stream={stream} claimId={c.id} running={running} onOpenEvidence={open} height={640} />
          {c.status === "awaiting_review" && (
            <div className="flex items-center justify-between gap-3 rounded-xl border border-missing-line bg-missing-bg px-4 py-3 text-[13px]">
              <span className="text-missing">The agent has paused for a human decision.</span>
              <Link href={`/claims/${id}`}><Button size="sm">Go to decision center</Button></Link>
            </div>
          )}
          {c.status === "awaiting_documents" && (
            <div className="flex items-center justify-between gap-3 rounded-xl border border-missing-line bg-missing-bg px-4 py-3 text-[13px]">
              <span className="text-missing">Waiting for claimant documents: {t.assessment?.documents.blocking.join(", ") || "requested documents"}.</span>
              <Link href={`/claims/${id}`}><Button size="sm">Upload in workspace</Button></Link>
            </div>
          )}
        </div>

        <div className="space-y-4">
          <Panel title="Assessment">
            {assessment && routing ? (
              <div className="space-y-2.5 text-[12.5px]">
                <div className="flex items-center justify-between"><span className="text-zinc-500">Fraud indicator</span><Tag tone={fraudTone(assessment.fraud.score)}>{fraudLabel(assessment.fraud.score)} · {assessment.fraud.score}</Tag></div>
                <div className="flex items-center justify-between"><span className="text-zinc-500">Severity</span><span>{titleCase(assessment.severity.level)}</span></div>
                <div className="flex items-center justify-between"><span className="text-zinc-500">Coverage</span><span>{titleCase(assessment.coverage.status)}</span></div>
                <div className="flex items-center justify-between"><span className="text-zinc-500">Confidence</span><span>{Math.round(assessment.confidence * 100)}%</span></div>
                <div className="rounded-lg border bg-raised p-2.5"><div className="text-[11px] text-zinc-500">Recommendation</div><div className="font-medium">{routing.queue_label} · {routing.priority}</div></div>
              </div>
            ) : running ? <div className="space-y-2"><Skeleton className="h-4" /><Skeleton className="h-4" /><Skeleton className="h-12" /></div>
              : <p className="text-[12.5px] text-muted-foreground">Appears after risk assessment.</p>}
          </Panel>
          <Panel title={`Evidence activity (${results.length})`} bodyClass="p-0">
            {results.length === 0 ? <div className="p-4"><EmptyState title="No evidence yet" body={running ? "Waiting for the first tool result…" : "Start the investigation."} /></div> : (
              <ul className="max-h-[420px] divide-y overflow-y-auto scroll-thin">
                <AnimatePresence initial={false}>
                  {[...results].reverse().map((e) => (
                    <motion.li key={e.id} initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }}>
                      <button onClick={() => open(e.payload.evidence_id)} className="w-full px-4 py-2.5 text-left hover:bg-white/[0.03]">
                        <div className="flex items-center justify-between gap-2 text-[12.5px]">
                          <span className="font-medium">{e.payload.label}</span>
                          <Tag tone={!e.payload.ok ? "missing" : e.payload.signals?.length ? "risk" : "verified"}>{!e.payload.ok ? "Unverified" : e.payload.signals?.length ? `${e.payload.signals.length} flag(s)` : "Verified"}</Tag>
                        </div>
                        <div className="mt-0.5 line-clamp-2 text-[11.5px] text-zinc-400">{e.payload.summary}</div>
                      </button>
                    </motion.li>
                  ))}
                </AnimatePresence>
              </ul>
            )}
          </Panel>
          <Panel title="Sources consulted">
            <ul className="space-y-2 text-[12px]">
              {[...new Set(results.map((e) => e.payload.tool as string))].map((tool) => (
                <li key={tool} className="flex items-start gap-2">
                  {EXTERNAL.has(tool) ? <Globe size={13} className="mt-0.5 text-sky-300" /> : <ExternalLink size={13} className="mt-0.5 text-zinc-500" />}
                  <span className="text-zinc-300">{TOOL_SOURCE[tool] ?? tool}{EXTERNAL.has(tool) && <Tag tone="info" className="ml-1.5">external API</Tag>}</span>
                </li>
              ))}
              {results.length === 0 && <li className="text-zinc-500">None yet.</li>}
            </ul>
          </Panel>
        </div>
      </div>
      <EvidenceSheet entry={evidence} claimId={c.id} onClose={() => setEvidence(null)} />
    </div>
  );
}
