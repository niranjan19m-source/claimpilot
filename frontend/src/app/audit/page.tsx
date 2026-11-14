"use client";

import Link from "next/link";
import { useState } from "react";
import { EmptyState, ErrorState, PageHeader, SkeletonRows, Tag, Tone } from "@/components/common";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/hooks/use-api";
import { AuditEvent, dateTime, titleCase } from "@/lib/api";

const CAT_TONE: Record<string, Tone> = { agent: "info", tool: "neutral", evidence: "risk", verification: "missing", routing: "info", human: "verified", action: "verified", document: "neutral", error: "risk" };

export default function AuditTrail() {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("all");
  const qs = new URLSearchParams({ ...(q ? { q } : {}), ...(cat !== "all" ? { category: cat } : {}) }).toString();
  const { data, error, loading, reload } = useApi<AuditEvent[]>(`/api/audit${qs ? `?${qs}` : ""}`, 8000);
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Audit trail" description="Immutable, chronological record of intake, agent execution, tool calls, evidence, verification, routing, and every human decision. Phone numbers, PAN and names are not shown here." />
      <div className="mb-3 flex flex-wrap gap-2">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search claim ID, actor, text…" className="h-8 w-72 text-[12.5px]" aria-label="Search audit log" />
        <Select value={cat} onValueChange={setCat}>
          <SelectTrigger className="h-8 w-44 text-[12.5px]" aria-label="Category"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">All categories</SelectItem>{Object.keys(CAT_TONE).map((c) => <SelectItem key={c} value={c}>{titleCase(c)}</SelectItem>)}</SelectContent>
        </Select>
        <span className="ml-auto self-center text-[12px] text-zinc-500">{data?.length ?? 0} records</span>
      </div>
      {error && !data ? <ErrorState message={error} onRetry={reload} /> : loading && !data ? <SkeletonRows rows={12} /> :
        !data?.length ? <EmptyState title="No audit records" body="Records appear when claims are investigated or decided." /> : (
          <div className="overflow-hidden rounded-xl border bg-card">
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">{["Timestamp", "Claim", "Category", "Actor", "Record"].map((h) => <TableHead key={h} className="text-[11.5px] text-zinc-500">{h}</TableHead>)}</TableRow></TableHeader>
              <TableBody>{data.map((a) => (
                <TableRow key={a.id} className="text-[12.5px]">
                  <TableCell className="whitespace-nowrap font-mono text-[11.5px] text-zinc-500">{dateTime(a.ts)}</TableCell>
                  <TableCell><Link href={`/claims/${a.claim_id}`} className="font-mono text-[11.5px] text-info hover:underline">{a.claim_id}</Link></TableCell>
                  <TableCell><Tag tone={CAT_TONE[a.category] ?? "neutral"}>{titleCase(a.category)}</Tag></TableCell>
                  <TableCell className="whitespace-nowrap text-zinc-300">{a.actor}</TableCell>
                  <TableCell className="text-zinc-300">{a.text}</TableCell>
                </TableRow>))}</TableBody>
            </Table>
          </div>
        )}
    </div>
  );
}
