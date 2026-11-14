"use client";

import { ArrowUpRight, CheckCheck, FilePlus2, Loader2, Scale, ShieldAlert, Shuffle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import { EvidenceChip, Panel, Tag } from "@/components/common";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useApi } from "@/hooks/use-api";
import { ClaimDetail, HumanDecision, QUEUE_LABEL, Queue, READ_ONLY, READ_ONLY_MSG, dateTime, postJSON } from "@/lib/api";
import { REVIEWER } from "@/lib/user";

type Kind = "approve" | "override" | "escalate_senior" | "further_investigation" | "request_documents";

const overrideSchema = z.object({
  queue: z.enum(["fast_track", "standard", "senior", "medical", "siu", "coverage_review"], { message: "Choose a routing destination" }),
  reason: z.string().trim().min(5, "Give a reason of at least 5 characters"),
  note: z.string().optional(),
});
const reasonSchema = z.object({ reason: z.string().trim().min(5, "Give a reason of at least 5 characters") });
const docsSchema = z.object({ documents: z.array(z.string().trim().min(2)).min(1, "List at least one document") });

const DOC_SUGGESTIONS = ["Police FIR", "Repair invoice", "Original repair estimate from an authorised garage",
  "Vehicle photographs taken at the scene", "Driving licence", "Hospital discharge summary", "Prior medical records"];

/** Human-in-the-loop decision center. The agent recommends; an adjuster decides. */
export function DecisionCenter({ detail, onChanged, openEvidence }: {
  detail: ClaimDetail; onChanged: () => void; openEvidence: (id: string) => void;
}) {
  const c = detail.claim;
  const t = c.triage ?? {};
  const rt = t.routing, a = t.assessment;
  const ledger = Object.fromEntries((t.ledger ?? []).map((e) => [e.id, e]));
  const history = useApi<HumanDecision[]>(`/api/decisions?claim_id=${c.id}`, 6000);
  const [dialog, setDialog] = useState<Kind | null>(null);
  const [confirmApprove, setConfirmApprove] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!rt || !a) {
    return (
      <Panel title="Decision center">
        <p className="text-[13px] text-muted-foreground">No recommendation yet. Decisions unlock when the agent finishes its investigation.</p>
      </Panel>
    );
  }
  const actionable = ["awaiting_review", "assigned", "approved"].includes(c.status) && !detail.running && !READ_ONLY;
  const paused = c.status === "awaiting_review";
  const supporting = [...new Set(a.fraud.signals.flatMap((s) => s.evidence ?? []))];
  const unresolved = [...(t.finished?.open_questions ?? []), ...a.coverage.needs_info, ...a.documents.missing.map((m) => `Missing: ${m}`),
    ...a.coverage.conditions];

  const submit = async (body: Record<string, unknown>) => {
    setBusy(true);
    try {
      const r = await postJSON<{ mode: string }>(`/api/claims/${c.id}/decision`, { reviewer: REVIEWER, ...body });
      toast.success(r.mode === "resumed_agent" ? "Decision recorded — agent resuming" : r.mode === "rerouted" ? "Claim rerouted and new ticket created" : "Decision recorded");
      setDialog(null); setConfirmApprove(false);
      onChanged(); history.reload();
    } catch (e: any) {
      toast.error(e.message);
    } finally { setBusy(false); }
  };

  return (
    <Panel title="Decision center" action={paused ? <Tag tone="missing" icon={<ShieldAlert size={11} />}>Your decision is required</Tag> : <Tag>{c.status === "approved" ? "Auto-approved" : "Assigned"}</Tag>}>
      <div className="space-y-3.5">
        <div className="rounded-lg border bg-raised p-3.5">
          <div className="text-[11px] uppercase tracking-[0.1em] text-zinc-500">Agent recommendation</div>
          <div className="mt-1 flex items-center justify-between gap-2">
            <span className="text-[15px] font-semibold">{rt.queue_label}</span>
            <Tag tone={rt.priority === "P1" || rt.priority === "P2" ? "risk" : "neutral"}>{rt.priority}</Tag>
          </div>
          <ul className="mt-2 space-y-1 text-[12.5px] leading-relaxed text-zinc-300">{rt.rationale.map((r) => <li key={r}>{r}</li>)}</ul>
          <div className="mt-3 grid grid-cols-2 gap-2 border-t pt-3 text-[12px]">
            <div><div className="text-zinc-500">Confidence</div><div className="font-medium">{Math.round(a.confidence * 100)}% <span className="text-zinc-500">(verifier)</span></div></div>
            <div><div className="text-zinc-500">Required action</div><div className="font-medium">{paused ? (rt.queue === "siu" ? "Confirm SIU referral" : rt.queue === "coverage_review" ? "Confirm or reject denial" : "Confirm routing") : "None (optional override)"}</div></div>
          </div>
          {supporting.length > 0 && (
            <div className="mt-2.5 flex flex-wrap items-center gap-1 text-[12px] text-zinc-500">Supporting evidence:
              {supporting.map((id) => <EvidenceChip key={id} id={id} entry={ledger[id]} onOpen={openEvidence} />)}
            </div>
          )}
        </div>

        {unresolved.length > 0 && (
          <div>
            <div className="mb-1 text-[11px] uppercase tracking-[0.1em] text-zinc-500">Unresolved questions</div>
            <ul className="space-y-1 text-[12.5px] text-zinc-300">{unresolved.slice(0, 5).map((u) => <li key={u} className="flex gap-2"><span className="text-missing">?</span>{u}</li>)}</ul>
          </div>
        )}

        {!actionable && (
          <div className="rounded-md border border-missing-line bg-missing-bg px-3 py-2 text-[12px] text-missing">
            {READ_ONLY ? READ_ONLY_MSG + " Run ClaimPilot locally to make decisions." : detail.running ? "The agent is running; decisions unlock when it pauses or finishes." :
              c.status === "awaiting_documents" ? "Waiting for claimant documents. Upload them in the Ground Truth pane to resume." :
                "Decisions are unavailable in the current state."}
          </div>
        )}

        <div className="grid gap-2">
          <Button disabled={!actionable || busy} onClick={() => setConfirmApprove(true)} className="justify-start">
            <CheckCheck size={15} /> Approve routing recommendation
          </Button>
          <div className="grid grid-cols-2 gap-2">
            <Button variant="outline" disabled={!actionable || busy} onClick={() => setDialog("request_documents")} className="justify-start"><FilePlus2 size={14} /> Request docs</Button>
            <Button variant="outline" disabled={!actionable || busy || c.route === "siu"} onClick={() => setDialog("further_investigation")} className="justify-start"><ShieldAlert size={14} /> Refer to SIU</Button>
            <Button variant="outline" disabled={!actionable || busy || c.route === "senior"} onClick={() => setDialog("escalate_senior")} className="justify-start"><ArrowUpRight size={14} /> Escalate</Button>
            <Button variant="outline" disabled={!actionable || busy} onClick={() => setDialog("override")} className="justify-start"><Shuffle size={14} /> Override</Button>
          </div>
          <p className="text-[11px] leading-relaxed text-zinc-500">
            <Scale size={11} className="mr-1 inline" />ClaimPilot never issues a final denial or fraud determination. Payment is automatic only on the low-risk fast-track route.
          </p>
        </div>

        {(history.data?.length ?? 0) > 0 && (
          <div className="border-t pt-3">
            <div className="mb-1.5 text-[11px] uppercase tracking-[0.1em] text-zinc-500">Decision record</div>
            <ul className="space-y-2">
              {history.data!.map((d) => (
                <li key={d.id} className="rounded-md border bg-raised px-3 py-2 text-[12px]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{d.decision.replace(/_/g, " ")}</span>
                    <span className="font-mono text-[10.5px] text-zinc-500">{dateTime(d.created_at)}</span>
                  </div>
                  <div className="mt-0.5 text-zinc-400">Recommended <b className="text-zinc-300">{QUEUE_LABEL[d.original_queue as Queue] ?? d.original_queue}</b>
                    {d.new_queue && d.new_queue !== d.original_queue && <> → decided <b className="text-zinc-300">{QUEUE_LABEL[d.new_queue as Queue] ?? d.new_queue}</b></>}</div>
                  {d.reason && <div className="mt-0.5 text-zinc-400">Reason: {d.reason}</div>}
                  <div className="mt-0.5 text-zinc-500">{d.reviewer}</div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <AlertDialog open={confirmApprove} onOpenChange={setConfirmApprove}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Approve: {rt.queue_label}?</AlertDialogTitle>
            <AlertDialogDescription>
              {paused ? "The agent will resume, create the ticket and notify the assigned handler." : "This confirms the current routing and records your approval in the audit trail."}
              {rt.queue === "siu" && " An SIU referral starts an investigation. It is not a finding of fraud."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => submit({ decision: "approve" })} disabled={busy}>{busy && <Loader2 size={14} className="animate-spin" />} Approve</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <DecisionDialog kind={dialog} current={rt.queue} busy={busy} onClose={() => setDialog(null)} onSubmit={submit} />
    </Panel>
  );
}

function DecisionDialog({ kind, current, busy, onClose, onSubmit }: {
  kind: Kind | null; current: Queue; busy: boolean; onClose: () => void; onSubmit: (b: Record<string, unknown>) => void;
}) {
  const [queue, setQueue] = useState<string>("");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [docs, setDocs] = useState<string[]>([]);
  const [custom, setCustom] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const reset = () => { setQueue(""); setReason(""); setNote(""); setDocs([]); setCustom(""); setErrors({}); };

  const go = () => {
    let parsed;
    if (kind === "override") parsed = overrideSchema.safeParse({ queue: queue || undefined, reason, note });
    else if (kind === "request_documents") parsed = docsSchema.safeParse({ documents: [...docs, ...(custom.trim() ? [custom.trim()] : [])] });
    else parsed = reasonSchema.safeParse({ reason });
    if (!parsed.success) {
      setErrors(Object.fromEntries(parsed.error.issues.map((i) => [String(i.path[0]), i.message])));
      return;
    }
    if (kind === "override" && queue === current) { setErrors({ queue: "That is already the recommended route" }); return; }
    onSubmit({ decision: kind, ...parsed.data });
  };

  const meta = {
    override: { title: "Override recommendation", desc: "Choose a different route. Your reason is stored next to the original recommendation." },
    escalate_senior: { title: "Escalate to senior adjuster", desc: "Moves the claim to a senior adjuster with your reason recorded." },
    further_investigation: { title: "Send for further investigation", desc: "Refers the claim to the Special Investigations Unit. This opens an inquiry. It does not accuse the claimant." },
    request_documents: { title: "Request additional documents", desc: "The claimant is notified. If the agent is paused, it waits for the upload and then re-plans." },
    approve: { title: "", desc: "" },
  }[kind ?? "approve"];

  return (
    <Dialog open={!!kind && kind !== "approve"} onOpenChange={(o) => { if (!o) { reset(); onClose(); } }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>{meta.title}</DialogTitle><DialogDescription>{meta.desc}</DialogDescription></DialogHeader>
        <div className="space-y-4">
          {kind === "override" && (
            <div className="space-y-1.5">
              <Label htmlFor="dest">New routing destination</Label>
              <Select value={queue} onValueChange={setQueue}>
                <SelectTrigger id="dest" aria-invalid={!!errors.queue}><SelectValue placeholder="Select a queue" /></SelectTrigger>
                <SelectContent>{Object.entries(QUEUE_LABEL).map(([k, v]) => <SelectItem key={k} value={k} disabled={k === current}>{v}{k === current ? " (current)" : ""}</SelectItem>)}</SelectContent>
              </Select>
              {errors.queue && <p className="text-[12px] text-risk">{errors.queue}</p>}
            </div>
          )}
          {kind === "request_documents" ? (
            <div className="space-y-2">
              <Label>Documents to request</Label>
              <div className="flex flex-wrap gap-1.5">
                {DOC_SUGGESTIONS.map((d) => {
                  const on = docs.includes(d);
                  return <button key={d} type="button" onClick={() => setDocs((x) => on ? x.filter((y) => y !== d) : [...x, d])} aria-pressed={on}
                    className={on ? "rounded-md bg-indigo-500/20 px-2 py-1 text-[12px] text-indigo-200 ring-1 ring-indigo-400/50" : "rounded-md px-2 py-1 text-[12px] text-zinc-400 ring-1 ring-white/10 hover:bg-white/5"}>{d}</button>;
                })}
              </div>
              <Input value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="Other document (optional)" />
              {errors.documents && <p className="text-[12px] text-risk">{errors.documents}</p>}
            </div>
          ) : (
            <div className="space-y-1.5">
              <Label htmlFor="reason">Reason <span className="text-risk">*</span></Label>
              <Textarea id="reason" value={reason} onChange={(e) => setReason(e.target.value)} aria-invalid={!!errors.reason}
                placeholder="e.g. Rain gauge 2 km from the loss location recorded 40 mm; weather flag is likely a grid artefact." className="min-h-20" />
              {errors.reason && <p className="text-[12px] text-risk">{errors.reason}</p>}
            </div>
          )}
          {kind === "override" && (
            <div className="space-y-1.5"><Label htmlFor="note">Notes (optional)</Label>
              <Textarea id="note" value={note} onChange={(e) => setNote(e.target.value)} className="min-h-14" /></div>
          )}
          <p className="text-[11px] text-zinc-500">Recorded as {REVIEWER} with a timestamp in the audit trail.</p>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => { reset(); onClose(); }}>Cancel</Button>
          <Button onClick={go} disabled={busy}>{busy && <Loader2 size={14} className="animate-spin" />} Submit decision</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
