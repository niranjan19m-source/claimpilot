"use client";

import Link from "next/link";
import { JsonViewer, Tag } from "@/components/common";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { ToolResult } from "@/lib/api";
import { TOOL_SOURCE } from "@/lib/agent-events";

/** Full detail for one evidence-ledger entry: what was asked, what came back, and where from. */
export function EvidenceSheet({ entry, claimId, onClose }: { entry: ToolResult | null; claimId: string; onClose: () => void }) {
  return (
    <Sheet open={!!entry} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        {entry && (
          <>
            <SheetHeader>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[12px] text-info">{entry.id}</span>
                <Tag tone={!entry.ok ? "missing" : entry.signals.length ? "risk" : "verified"}>
                  {!entry.ok ? "Unverified / degraded" : entry.signals.length ? "Contradictory evidence" : "Verified"}
                </Tag>
              </div>
              <SheetTitle>{entry.label}</SheetTitle>
              <SheetDescription>{TOOL_SOURCE[entry.tool] ?? entry.tool} · {entry.ms} ms · claim {claimId}</SheetDescription>
            </SheetHeader>
            <div className="space-y-4 px-4 pb-6">
              <p className="text-[13px] leading-relaxed text-zinc-300">{entry.summary}</p>
              {entry.signals.map((s) => (
                <div key={s.code} className="rounded-md border border-risk-line bg-risk-bg px-3 py-2 text-[12px]">
                  <div className="font-medium text-risk">{s.label}{s.weight > 0 && <span className="ml-1 font-mono">+{s.weight}</span>}</div>
                  <div className="text-zinc-300">{s.detail}</div>
                </div>
              ))}
              <div><h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Input</h4><JsonViewer value={entry.input} maxHeight={120} /></div>
              <div><h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Output</h4><JsonViewer value={entry.data} maxHeight={460} /></div>
              <div className="flex gap-3 text-[12px]">
                <Link href={`/investigations/${claimId}`} className="text-info hover:underline">Open in live investigation →</Link>
                <Link href={`/evidence?claim=${claimId}`} className="text-info hover:underline">All evidence for this claim →</Link>
              </div>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
