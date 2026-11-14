"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { EmptyState, ErrorState, PageHeader, Panel, SkeletonRows, Tag, fraudTone } from "@/components/common";
import { ImageForensicsPanel } from "@/components/fraud/forensics";
import { RelationshipGraph } from "@/components/fraud/relationship-graph";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApi } from "@/hooks/use-api";
import { ClaimDetail, ClaimRow, ToolResult, titleCase } from "@/lib/api";

function FraudIntel() {
  const router = useRouter();
  const params = useSearchParams();
  const claims = useApi<ClaimRow[]>("/api/claims", 10000);
  const investigated = (claims.data ?? []).filter((c) => c.route).sort((a, b) => (b.fraud_score ?? 0) - (a.fraud_score ?? 0));
  const id = params.get("claim") ?? investigated[0]?.id ?? null;
  useEffect(() => { if (!params.get("claim") && investigated[0]) router.replace(`/fraud?claim=${investigated[0].id}`); }, [params, investigated, router]);
  const f = useApi<{ photo_forensics: ToolResult | null; network: ToolResult | null; history: ToolResult | null }>(id ? `/api/claims/${id}/forensics` : null);
  const detail = useApi<ClaimDetail>(id ? `/api/claims/${id}` : null);
  const row = investigated.find((c) => c.id === id);

  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader title="Fraud intelligence" description="Digital forensics and relationship mapping for investigated claims. Every flag shows its evidence. Treat flags as leads to check, not conclusions."
        actions={
          <Select value={id ?? undefined} onValueChange={(v) => router.push(`/fraud?claim=${v}`)}>
            <SelectTrigger className="h-9 w-72 text-[12.5px]" aria-label="Claim"><SelectValue placeholder="Choose an investigated claim" /></SelectTrigger>
            <SelectContent>{investigated.map((c) => <SelectItem key={c.id} value={c.id}>{c.id} · {titleCase(c.claim_type)} · risk {Math.round(c.fraud_score ?? 0)}</SelectItem>)}</SelectContent>
          </Select>
        } />
      {claims.error && !claims.data ? <ErrorState message={claims.error} onRetry={claims.reload} /> : claims.loading && !claims.data ? <SkeletonRows rows={6} /> :
        investigated.length === 0 ? <EmptyState title="No investigated claims yet" body="Run an investigation from the Overview, e.g. the basement-flood scenario." /> : (
          <>
            {row && (
              <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border bg-card px-4 py-3 text-[12.5px]">
                <span className="font-mono">{row.id}</span><Tag tone={fraudTone(row.fraud_score)}>Risk indicator {Math.round(row.fraud_score ?? 0)}</Tag>
                {row.flags.map((x) => <Tag key={x} tone="risk">{x}</Tag>)}
                {!row.flags.length && <span className="text-zinc-500">No fraud indicators were raised for this claim.</span>}
              </div>
            )}
            <Tabs defaultValue="graph">
              <TabsList className="mb-3"><TabsTrigger value="graph">Claim relationship graph</TabsTrigger><TabsTrigger value="images">Image forensics</TabsTrigger><TabsTrigger value="history">Claims history</TabsTrigger></TabsList>
              <TabsContent value="graph">{f.loading ? <SkeletonRows rows={6} /> : <RelationshipGraph entry={f.data?.network} />}</TabsContent>
              <TabsContent value="images">{f.loading ? <SkeletonRows rows={6} /> :
                <ImageForensicsPanel entry={f.data?.photo_forensics} incidentDate={detail.data?.claim.incident_date} policyStart={detail.data?.policy?.start_date} />}</TabsContent>
              <TabsContent value="history">
                <Panel title="Prior claims by this claimant">
                  {!f.data?.history ? <EmptyState title="Claims history not run" /> : (
                    <>
                      <p className="mb-3 text-[13px] text-zinc-300">{f.data.history.summary}</p>
                      {(f.data.history.data.prior_claims ?? []).length === 0 ? <p className="text-[12.5px] text-zinc-500">No prior claims on record.</p> : (
                        <table className="w-full text-[12.5px]"><thead><tr className="text-left text-[11px] text-zinc-500"><th className="py-1.5">Claim</th><th>Type</th><th>Date</th><th>Outcome</th></tr></thead>
                          <tbody>{f.data.history.data.prior_claims.map((p: any) => (
                            <tr key={p.id} className="border-t"><td className="py-1.5 font-mono">{p.id}</td><td>{titleCase(p.claim_type)}</td><td>{p.incident_date}</td>
                              <td><Tag tone={p.outcome?.includes("fraud") ? "risk" : "neutral"}>{titleCase(p.outcome ?? p.status)}</Tag></td></tr>))}</tbody></table>
                      )}
                    </>
                  )}
                </Panel>
              </TabsContent>
            </Tabs>
          </>
        )}
    </div>
  );
}

export default function Page() { return <Suspense><FraudIntel /></Suspense>; }
