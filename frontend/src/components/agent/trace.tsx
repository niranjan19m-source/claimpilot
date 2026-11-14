"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight, Radio, WifiOff } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { JsonViewer, Tag } from "@/components/common";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { StreamState } from "@/hooks/use-claim-stream";
import type { AgentEvent } from "@/lib/api";
import { dateTime, timeOf } from "@/lib/api";
import { Actor, TOOL_SOURCE, describe, toolPairs } from "@/lib/agent-events";
import { cn } from "@/lib/utils";

const ACTOR_CLS: Record<Actor, string> = {
  SYSTEM: "text-zinc-400", PLANNER: "text-indigo-300", TOOL: "text-sky-300", RESULT: "text-teal-300",
  AGENT: "text-violet-300", VERIFIER: "text-amber-300", SCORER: "text-indigo-300", ROUTER: "text-fuchsia-300",
  REPORTER: "text-zinc-300", HUMAN: "text-emerald-300", ACTION: "text-emerald-300", CLAIMANT: "text-sky-300", ERROR: "text-rose-400",
};
const TONE_LINE: Record<string, string> = {
  neutral: "text-zinc-300", info: "text-zinc-200", ok: "text-zinc-200", risk: "text-rose-200", warn: "text-amber-200",
};

const HIDDEN = new Set(["node", "paused"]);

/** Terminal-style live execution trace. Every line is a real backend event; tool lines are clickable. */
export function TraceTerminal({ events, stream, claimId, running, onOpenEvidence, height = 520 }: {
  events: AgentEvent[]; stream: StreamState; claimId: string; running: boolean;
  onOpenEvidence?: (id: string) => void; height?: number;
}) {
  const [selected, setSelected] = useState<AgentEvent | null>(null);
  const [follow, setFollow] = useState(true);
  const box = useRef<HTMLDivElement>(null);
  const rows = useMemo(() => events.filter((e) => !HIDDEN.has(e.type)), [events]);
  const pairs = useMemo(() => toolPairs(events), [events]);

  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [rows.length, follow]);

  return (
    <div className="overflow-hidden rounded-xl border bg-sunken">
      <div className="flex items-center justify-between gap-3 border-b bg-card/60 px-3.5 py-2">
        <div className="flex items-center gap-2 font-mono text-[11px] text-zinc-400">
          <span className="flex gap-1"><i className="h-2 w-2 rounded-full bg-zinc-700" /><i className="h-2 w-2 rounded-full bg-zinc-700" /><i className="h-2 w-2 rounded-full bg-zinc-700" /></span>
          agent-trace · {claimId}
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          {stream === "live" ? (
            <span className="flex items-center gap-1.5 text-emerald-300"><Radio size={12} className={running ? "cp-pulse" : ""} />{running ? "Streaming" : "Connected"}</span>
          ) : (
            <span className="flex items-center gap-1.5 text-amber-300"><WifiOff size={12} />{stream === "connecting" ? "Connecting…" : "Reconnecting…"}</span>
          )}
          <span className="text-zinc-600">·</span>
          <span className="font-mono text-zinc-500">{rows.length} events</span>
        </div>
      </div>
      <div ref={box} role="log" aria-live="polite" aria-label="Live agent execution trace"
        onScroll={(e) => { const el = e.currentTarget; setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 40); }}
        className="scroll-thin overflow-y-auto px-2 py-2 font-mono text-[12px] leading-[1.65]" style={{ height }}>
        {rows.length === 0 && <div className="px-2 py-6 text-zinc-500">$ waiting for agent events…</div>}
        <AnimatePresence initial={false}>
          {rows.map((e) => {
            const d = describe(e);
            const clickable = e.type !== "thought";
            const pending = e.type === "tool_call" && !pairs.get(e.payload.evidence_id)?.result;
            if (e.type === "tool_call" && !pending) return null; // collapsed into its RESULT line
            return (
              <motion.button key={e.id} type="button" disabled={!clickable} onClick={() => setSelected(e)}
                initial={{ opacity: 0, y: 3 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18 }}
                className={cn("group flex w-full items-start gap-2 rounded px-2 py-0.5 text-left", clickable && "hover:bg-white/[0.04] focus-visible:bg-white/[0.06]")}>
                <span className="shrink-0 text-zinc-600">[{timeOf(e.ts)}]</span>
                <span className={cn("w-[74px] shrink-0 font-semibold", ACTOR_CLS[d.actor])}>{d.actor}</span>
                <span className={cn("min-w-0 flex-1 break-words", TONE_LINE[d.tone], e.type === "thought" && "italic text-zinc-400")}>
                  {pending && <span className="cp-pulse mr-1 text-sky-300">▸</span>}
                  {d.text}
                  {e.type === "tool_result" && <span className="ml-1.5 text-zinc-600">({e.payload.evidence_id} · {e.payload.ms}ms)</span>}
                </span>
                {clickable && <ChevronRight size={13} className="mt-1 shrink-0 text-zinc-700 group-hover:text-zinc-400" />}
              </motion.button>
            );
          })}
        </AnimatePresence>
        {running && rows.length > 0 && <div className="px-2 text-zinc-600"><span className="cp-pulse">█</span></div>}
      </div>
      <EventDetailSheet event={selected} pairs={pairs} claimId={claimId} onClose={() => setSelected(null)} onOpenEvidence={onOpenEvidence} />
    </div>
  );
}

function EventDetailSheet({ event, pairs, claimId, onClose, onOpenEvidence }: {
  event: AgentEvent | null; pairs: ReturnType<typeof toolPairs>; claimId: string; onClose: () => void; onOpenEvidence?: (id: string) => void;
}) {
  const d = event ? describe(event) : null;
  const isTool = event && (event.type === "tool_result" || event.type === "tool_call");
  const pair = isTool ? pairs.get(event!.payload.evidence_id) : undefined;
  const result = pair?.result?.payload;
  const call = pair?.call;
  return (
    <Sheet open={!!event} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        {event && d && (
          <>
            <SheetHeader>
              <div className="flex flex-wrap items-center gap-2">
                <Tag tone={d.tone === "risk" ? "risk" : d.tone === "warn" ? "missing" : d.tone === "ok" ? "verified" : "info"}>{d.actor}</Tag>
                <code className="text-[11px] text-zinc-500">{d.name}</code>
              </div>
              <SheetTitle className="text-base">{isTool ? (result?.label ?? call?.payload.label) : d.text.slice(0, 90)}</SheetTitle>
              <SheetDescription>{dateTime(event.ts)} · claim {claimId}</SheetDescription>
            </SheetHeader>
            <div className="space-y-4 px-4 pb-6">
              {isTool ? (
                <>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg border bg-raised p-3 text-[12.5px]">
                    <dt className="text-muted-foreground">Tool</dt><dd className="font-mono">{(result ?? call?.payload).tool}</dd>
                    <dt className="text-muted-foreground">Evidence id</dt>
                    <dd><button className="font-mono text-info hover:underline" onClick={() => { onOpenEvidence?.(event.payload.evidence_id); onClose(); }}>{event.payload.evidence_id}</button></dd>
                    <dt className="text-muted-foreground">Started</dt><dd className="font-mono">{call ? timeOf(call.ts) : "—"}</dd>
                    <dt className="text-muted-foreground">Status</dt>
                    <dd>{!result ? <Tag tone="info">Running</Tag> : result.ok ? <Tag tone="verified">Completed</Tag> : <Tag tone="missing">Failed / degraded</Tag>}</dd>
                    <dt className="text-muted-foreground">Duration</dt><dd className="font-mono">{result ? `${result.ms} ms` : "—"}</dd>
                    <dt className="text-muted-foreground">Invocation</dt><dd>{call?.payload.auto ? "Auto (dependency)" : "Agent"}</dd>
                    <dt className="col-span-2 text-muted-foreground">Source / API</dt>
                    <dd className="col-span-2 text-[12px]">{TOOL_SOURCE[(result ?? call?.payload).tool] ?? "—"}</dd>
                  </dl>
                  {result && <p className="text-[13px] leading-relaxed text-zinc-300">{result.summary}</p>}
                  {result?.signals?.length > 0 && (
                    <div className="space-y-1.5">
                      <h4 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Evidence generated (flags)</h4>
                      {result.signals.map((s: any) => (
                        <div key={s.code} className="rounded-md border border-risk-line bg-risk-bg px-3 py-2 text-[12px]">
                          <div className="font-medium text-risk">{s.label} {s.weight > 0 && <span className="font-mono">+{s.weight}</span>}</div>
                          <div className="text-zinc-300">{s.detail}</div>
                        </div>
                      ))}
                    </div>
                  )}
                  <div><h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Input parameters</h4>
                    <JsonViewer value={call?.payload.input ?? {}} maxHeight={140} /></div>
                  {result && <div><h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Output</h4>
                    <JsonViewer value={result.data} maxHeight={420} /></div>}
                </>
              ) : (
                <>
                  <p className="text-[13px] leading-relaxed text-zinc-300">{d.text}</p>
                  <div><h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Event payload</h4>
                    <JsonViewer value={event.payload} maxHeight={480} /></div>
                </>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
