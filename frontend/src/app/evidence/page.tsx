"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { EmptyState, ErrorState, JsonViewer, PageHeader, SkeletonRows, Tag, Tone } from "@/components/common";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/hooks/use-api";
import { Evidence, titleCase } from "@/lib/api";
import { TOOL_SOURCE } from "@/lib/agent-events";

const STATUS: Record<Evidence["status"], { label: string; tone: Tone }> = {
  verified: { label: "Verified", tone: "verified" }, contradictory: { label: "Contradictory", tone: "risk" },
  unverified: { label: "Unverified", tone: "missing" }, interpretation: { label: "Agent interpretation", tone: "info" },
};
const CATEGORIES = ["policy", "weather", "documents", "image_forensics", "claim_history", "location", "registry", "analytics", "agent_finding"];

function EvidenceExplorer() {
  const params = useSearchParams();
  const [claim, setClaim] = useState(params.get("claim") ?? "");
  const [status, setStatus] = useState("all");
  const [category, setCategory] = useState("all");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<Evidence | null>(null);
  const { data, error, loading, reload } = useApi<Evidence[]>("/api/evidence", 8000);
  const rows = useMemo(() => (data ?? []).filter((e) =>
    (!claim || e.claim_id === claim) && (status === "all" || e.status === status) && (category === "all" || e.category === category)
    && (!q || `${e.summary} ${e.label} ${e.claim_id}`.toLowerCase().includes(q.toLowerCase()))), [data, claim, status, category, q]);
  const claims = [...new Set((data ?? []).map((e) => e.claim_id))];

  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader title="Evidence explorer" description="Every tool result and agent finding across investigations. Each item links back to its claim and investigation." />
      <div className="mb-3 flex flex-wrap gap-2">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search evidence…" className="h-8 w-64 text-[12.5px]" aria-label="Search evidence" />
        <Select value={claim || "all"} onValueChange={(v) => setClaim(v === "all" ? "" : v)}>
          <SelectTrigger className="h-8 w-44 text-[12.5px]" aria-label="Claim"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">All claims</SelectItem>{claims.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="h-8 w-48 text-[12.5px]" aria-label="Status"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">All statuses</SelectItem>{Object.entries(STATUS).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={category} onValueChange={setCategory}>
          <SelectTrigger className="h-8 w-44 text-[12.5px]" aria-label="Category"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">All categories</SelectItem>{CATEGORIES.map((c) => <SelectItem key={c} value={c}>{titleCase(c)}</SelectItem>)}</SelectContent>
        </Select>
        <span className="ml-auto self-center text-[12px] text-zinc-500">{rows.length} items</span>
      </div>
      {error && !data ? <ErrorState message={error} onRetry={reload} /> : loading && !data ? <SkeletonRows rows={10} /> :
        rows.length === 0 ? <EmptyState title="No evidence found" body={data?.length ? "Adjust the filters." : "Run an investigation from the Overview to collect evidence."} /> : (
          <div className="overflow-hidden rounded-xl border bg-card">
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">{["ID", "Claim", "Category", "Evidence", "Source", "Stage", "Status"].map((h) => <TableHead key={h} className="text-[11.5px] text-zinc-500">{h}</TableHead>)}</TableRow></TableHeader>
              <TableBody>
                {rows.map((e) => (
                  <TableRow key={e.key} tabIndex={0} onClick={() => setSel(e)} onKeyDown={(k) => k.key === "Enter" && setSel(e)} className="cursor-pointer text-[12.5px]">
                    <TableCell className="font-mono text-info">{e.evidence_id}</TableCell>
                    <TableCell className="font-mono text-[11.5px]">{e.claim_id}</TableCell>
                    <TableCell>{titleCase(e.category)}</TableCell>
                    <TableCell className="max-w-[520px]"><div className="font-medium">{e.label}</div><div className="truncate text-zinc-400">{e.summary}</div></TableCell>
                    <TableCell className="max-w-[220px] truncate text-[11.5px] text-zinc-500">{e.tool === "agent_finding" ? "Agent (cites evidence)" : TOOL_SOURCE[e.tool]}</TableCell>
                    <TableCell className="whitespace-nowrap text-zinc-400">{e.stage}</TableCell>
                    <TableCell><Tag tone={STATUS[e.status].tone}>{STATUS[e.status].label}</Tag></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      <Sheet open={!!sel} onOpenChange={(o) => !o && setSel(null)}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          {sel && <>
            <SheetHeader>
              <div className="flex items-center gap-2"><span className="font-mono text-[12px] text-info">{sel.evidence_id}</span><Tag tone={STATUS[sel.status].tone}>{STATUS[sel.status].label}</Tag></div>
              <SheetTitle>{sel.label}</SheetTitle>
              <SheetDescription>{sel.claim_id} · {sel.stage} · {sel.tool === "agent_finding" ? "Agent finding" : TOOL_SOURCE[sel.tool]}</SheetDescription>
            </SheetHeader>
            <div className="space-y-4 px-4 pb-6">
              <p className="text-[13px] leading-relaxed text-zinc-300">{sel.summary}</p>
              {sel.signals.map((s) => <div key={s.code} className="rounded-md border border-risk-line bg-risk-bg px-3 py-2 text-[12px]"><div className="font-medium text-risk">{s.label}</div><div className="text-zinc-300">{s.detail}</div></div>)}
              <div className="flex gap-4 text-[12px]">
                <Link href={`/claims/${sel.claim_id}`} className="text-info hover:underline">Open claim →</Link>
                <Link href={`/investigations/${sel.claim_id}`} className="text-info hover:underline">Open investigation event →</Link>
              </div>
              <div><h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Source context</h4><JsonViewer value={sel.data} maxHeight={480} /></div>
            </div>
          </>}
        </SheetContent>
      </Sheet>
    </div>
  );
}

export default function Page() { return <Suspense><EvidenceExplorer /></Suspense>; }
