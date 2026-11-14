"use client";

import { DndContext, DragEndEvent, DragOverlay, DragStartEvent, KeyboardSensor, PointerSensor, useDraggable, useDroppable, useSensor, useSensors } from "@dnd-kit/core";
import { Loader2, Play, Radar, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { ClaimCard, DragGrip } from "@/components/claims/claim-card";
import { EmptyState, ErrorState, Metric, PageHeader, Tag } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useApi } from "@/hooks/use-api";
import { ClaimRow, READ_ONLY, Scenario, postJSON, titleCase } from "@/lib/api";
import { REVIEWER } from "@/lib/user";
import { cn } from "@/lib/utils";

type Col = "fast_track" | "standard" | "siu" | "documents";
const COLUMNS: { key: Col; title: string; hint: string; dot: string }[] = [
  { key: "fast_track", title: "Fast track", hint: "Low risk · complete documents · no discrepancies", dot: "bg-emerald-400" },
  { key: "standard", title: "Standard review", hint: "Adjuster, senior, medical and coverage review", dot: "bg-indigo-400" },
  { key: "siu", title: "SIU / Fraud investigation", hint: "Substantial indicators · human sign-off", dot: "bg-rose-500" },
  { key: "documents", title: "Awaiting documents", hint: "FIR, invoices, bills or other evidence missing", dot: "bg-amber-400" },
];

function columnOf(c: ClaimRow): Col | null {
  if (c.status === "awaiting_documents") return "documents";
  if (!c.route || c.status === "triaging") return null;
  if (c.route === "fast_track") return "fast_track";
  if (c.route === "siu") return "siu";
  return "standard";
}

export default function Overview() {
  const router = useRouter();
  const claims = useApi<ClaimRow[]>("/api/claims", 4000);
  const scen = useApi<Scenario[]>("/api/scenarios", 8000);
  const [filters, setFilters] = useState({ risk: "all", type: "all", q: "" });
  const [dragging, setDragging] = useState<ClaimRow | null>(null);
  const [move, setMove] = useState<{ claim: ClaimRow; to: Col } | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }), useSensor(KeyboardSensor));

  const rows = useMemo(() => claims.data ?? [], [claims.data]);
  const filtered = useMemo(() => rows.filter((c) => {
    const f = c.fraud_score ?? -1;
    const riskOk = filters.risk === "all" || (filters.risk === "high" ? f >= 60 : filters.risk === "elevated" ? f >= 30 && f < 60 : f >= 0 && f < 30);
    return riskOk && (filters.type === "all" || c.line === filters.type)
      && (!filters.q || `${c.id} ${c.city} ${c.claim_type}`.toLowerCase().includes(filters.q.toLowerCase()));
  }), [rows, filters]);
  const times = rows.map((c) => c.triage_ms).filter(Boolean) as number[];
  const intake = rows.filter((c) => !columnOf(c));

  const start = async (id: string) => {
    setStarting(id);
    try { await postJSON(`/api/claims/${id}/run`); router.push(`/investigations/${id}`); }
    catch (e: any) { toast.error(e.message); setStarting(null); }
  };

  const onDragStart = (e: DragStartEvent) => setDragging(rows.find((c) => c.id === e.active.id) ?? null);
  const onDragEnd = (e: DragEndEvent) => {
    setDragging(null);
    const c = rows.find((x) => x.id === e.active.id);
    const to = e.over?.id as Col | undefined;
    if (!c || !to || columnOf(c) === to) return;
    setMove({ claim: c, to });
  };

  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader title="Adjuster command center · Intelligent claims, transparent decisions"
        description={READ_ONLY ? "Every claim below was investigated by the real agent; this hosted demo replays that recorded run. Open any card to see the evidence, the agent trace and the explanation." : "The agent investigates every claim and places it on the board. To reroute a claim, drag its card. The move only happens after you give a reason and the backend accepts it."}
        actions={<Link href="/claims/new"><Button>New claim</Button></Link>} />

      {claims.error && !claims.data && <div className="mb-4"><ErrorState title="Backend unavailable" message={claims.error} onRetry={claims.reload} /></div>}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {claims.loading && !claims.data ? Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[84px] rounded-xl" />) : <>
          <Metric label="Total claims" value={rows.length} hint="synthetic demo book" />
          <Metric label="Active investigations" value={rows.filter((c) => c.status === "triaging").length} tone="info" />
          <Metric label="Awaiting human review" value={rows.filter((c) => c.status === "awaiting_review").length} tone="missing" />
          <Metric label="High-risk claims" value={rows.filter((c) => (c.fraud_score ?? 0) >= 60).length} tone="risk" hint="fraud indicator ≥ 60" />
          <Metric label="Missing documents" value={rows.filter((c) => c.missing_documents.length > 0).length} tone="missing" />
          <Metric label="Avg time to decision" value={times.length ? `${(times.reduce((a, b) => a + b, 0) / times.length / 1000).toFixed(1)}s` : "—"} hint={`across ${times.length} investigations`} />
        </>}
      </div>

      {intake.length > 0 && (
        <section className="mt-6">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-[12px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Intake · not yet investigated</h2>
            <span className="text-[11px] text-zinc-500">Run a claim to watch the agent work live</span>
          </div>
          <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
            {intake.map((c) => {
              const s = scen.data?.find((x) => x.id === c.id);
              return (
                <div key={c.id} className="flex items-center justify-between gap-3 rounded-lg border bg-card px-3.5 py-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2"><span className="whitespace-nowrap font-mono text-[11.5px] text-zinc-400">{c.id}</span>{s && <Tag>{s.tag}</Tag>}</div>
                    <div className="truncate text-[13px] font-medium">{s?.title ?? `${titleCase(c.claim_type)} · ${c.city}`}</div>
                  </div>
                  {c.status === "triaging" ? (
                    <Link href={`/investigations/${c.id}`}><Button size="sm" variant="outline"><Radar size={13} className="cp-pulse" /> Watch</Button></Link>
                  ) : (
                    <Button size="sm" onClick={() => start(c.id)} disabled={starting === c.id || READ_ONLY}>
                      {starting === c.id ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />} Investigate
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      <section className="mt-6">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="mr-auto text-[12px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Claims board</h2>
          <Input aria-label="Filter claims" placeholder="Filter by ID, city, type" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} className="h-8 w-48 text-[12.5px]" />
          <Select value={filters.risk} onValueChange={(v) => setFilters({ ...filters, risk: v })}>
            <SelectTrigger className="h-8 w-36 text-[12.5px]" aria-label="Risk filter"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="all">All risk</SelectItem><SelectItem value="high">High (≥60)</SelectItem><SelectItem value="elevated">Elevated (30–59)</SelectItem><SelectItem value="low">Low (&lt;30)</SelectItem></SelectContent>
          </Select>
          <Select value={filters.type} onValueChange={(v) => setFilters({ ...filters, type: v })}>
            <SelectTrigger className="h-8 w-32 text-[12.5px]" aria-label="Line filter"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="all">All lines</SelectItem><SelectItem value="motor">Motor</SelectItem><SelectItem value="health">Health</SelectItem></SelectContent>
          </Select>
        </div>
        <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd}>
          <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-4">
            {COLUMNS.map((col) => <Column key={col.key} col={col} claims={filtered.filter((c) => columnOf(c) === col.key)} loading={claims.loading && !claims.data} dragging={dragging} />)}
          </div>
          <DragOverlay>{dragging ? <div className="w-80 rotate-1"><ClaimCard c={dragging} /></div> : null}</DragOverlay>
        </DndContext>
      </section>

      <MoveDialog move={move} onClose={() => setMove(null)} onDone={() => { setMove(null); claims.reload(); }} />
    </div>
  );
}

function Column({ col, claims, loading, dragging }: { col: (typeof COLUMNS)[number]; claims: ClaimRow[]; loading: boolean; dragging: ClaimRow | null }) {
  const { setNodeRef, isOver } = useDroppable({ id: col.key });
  return (
    <div ref={setNodeRef} className={cn("flex min-h-[320px] flex-col rounded-xl border bg-card/70 transition-colors", isOver && "border-indigo-400/60 bg-indigo-500/[0.06]")}>
      <div className="border-b px-3.5 py-2.5">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-2 text-[13px] font-semibold"><i className={cn("h-2 w-2 rounded-full", col.dot)} />{col.title}</span>
          <span className="rounded bg-white/5 px-1.5 font-mono text-[11px] text-zinc-400">{claims.length}</span>
        </div>
        <div className="mt-0.5 text-[11px] text-zinc-500">{col.hint}</div>
      </div>
      <div className="flex-1 space-y-2.5 p-2.5">
        {loading ? <><Skeleton className="h-36 rounded-lg" /><Skeleton className="h-36 rounded-lg" /></> :
          claims.length === 0 ? <EmptyState title="No claims" body={dragging ? "Drop here to reroute" : "Investigated claims routed here appear on this column."} /> :
            claims.map((c) => <DraggableCard key={c.id} c={c} />)}
      </div>
    </div>
  );
}

function DraggableCard({ c }: { c: ClaimRow }) {
  const movable = ["assigned", "approved", "awaiting_review"].includes(c.status) && !READ_ONLY;
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: c.id, disabled: !movable });
  return (
    <div ref={setNodeRef}>
      <ClaimCard c={c} dragging={isDragging} dragHandle={movable ? <DragGrip {...attributes} {...listeners} /> : undefined} />
    </div>
  );
}

function MoveDialog({ move, onClose, onDone }: { move: { claim: ClaimRow; to: Col } | null; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [docs, setDocs] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!move) return null;
  const toDocs = move.to === "documents";
  const target = COLUMNS.find((c) => c.key === move.to)!;
  const submit = async () => {
    if (toDocs ? docs.trim().length < 2 : reason.trim().length < 5) { setErr(toDocs ? "List at least one document" : "Give a reason of at least 5 characters"); return; }
    setBusy(true); setErr(null);
    const body = toDocs ? { decision: "request_documents", documents: docs.split(",").map((d) => d.trim()).filter(Boolean) }
      : move.to === "siu" ? { decision: "further_investigation", reason } : { decision: "override", queue: move.to, reason };
    try {
      await postJSON(`/api/claims/${move.claim.id}/decision`, { reviewer: REVIEWER, ...body });
      toast.success(`${move.claim.id}: ${toDocs ? "documents requested" : `rerouted to ${target.title}`}`);
      setReason(""); setDocs(""); onDone();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{toDocs ? "Request documents" : `Reroute to ${target.title}`}</DialogTitle>
          <DialogDescription>{move.claim.id} · currently {move.claim.queue_label ?? "unrouted"}. This is recorded as a human override next to the agent&apos;s recommendation.</DialogDescription>
        </DialogHeader>
        {toDocs ? (
          <div className="space-y-1.5"><Label htmlFor="docs">Documents (comma-separated)</Label>
            <Input id="docs" value={docs} onChange={(e) => setDocs(e.target.value)} placeholder="Police FIR, Repair invoice" /></div>
        ) : (
          <div className="space-y-1.5"><Label htmlFor="mreason">Reason for override <span className="text-risk">*</span></Label>
            <Textarea id="mreason" value={reason} onChange={(e) => setReason(e.target.value)} className="min-h-20" /></div>
        )}
        {err && <p className="text-[12px] text-risk">{err}</p>}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}><RotateCcw size={13} /> Cancel</Button>
          <Button onClick={submit} disabled={busy}>{busy && <Loader2 size={13} className="animate-spin" />} Confirm</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
