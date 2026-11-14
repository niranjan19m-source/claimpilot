"use client";

import { Play, Radar } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { EmptyState, ErrorState, PageHeader, SkeletonRows, Tag, fraudTone, statusTone } from "@/components/common";
import { Button } from "@/components/ui/button";
import { useApi } from "@/hooks/use-api";
import { ClaimRow, READ_ONLY, STATUS_LABEL, Scenario, inr, postJSON, titleCase } from "@/lib/api";

export default function Investigations() {
  const router = useRouter();
  const claims = useApi<ClaimRow[]>("/api/claims", 3000);
  const scen = useApi<Scenario[]>("/api/scenarios");
  const rows = claims.data ?? [];
  const active = rows.filter((c) => c.status === "triaging");
  const paused = rows.filter((c) => c.status === "awaiting_review" || c.status === "awaiting_documents");
  const done = rows.filter((c) => ["assigned", "approved"].includes(c.status));
  const fresh = rows.filter((c) => c.status === "submitted");
  const run = async (id: string) => {
    try { await postJSON(`/api/claims/${id}/run`); router.push(`/investigations/${id}`); } catch (e: any) { toast.error(e.message); }
  };

  const Row = ({ c, action }: { c: ClaimRow; action?: React.ReactNode }) => {
    const s = scen.data?.find((x) => x.id === c.id);
    return (
      <div className="flex items-center justify-between gap-3 border-b px-4 py-3 last:border-0">
        <Link href={`/investigations/${c.id}`} className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[12px] text-zinc-400">{c.id}</span>
            <Tag tone={statusTone(c.status)}>{STATUS_LABEL[c.status]}</Tag>
            {c.fraud_score != null && <Tag tone={fraudTone(c.fraud_score)}>risk {Math.round(c.fraud_score)}</Tag>}
          </div>
          <div className="mt-0.5 truncate text-[13px]">{s?.title ?? `${titleCase(c.claim_type)} · ${c.city}`} · {inr(c.amount_claimed)}</div>
        </Link>
        {action}
      </div>
    );
  };

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Live investigations" description="Open an investigation to watch the agent plan, call tools and verify evidence in real time. Every event comes from the backend stream." />
      {claims.error && !claims.data && <ErrorState title="Backend unavailable" message={claims.error} onRetry={claims.reload} />}
      {claims.loading && !claims.data ? <SkeletonRows rows={6} /> : (
        <div className="space-y-6">
          <section>
            <h2 className="mb-2 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.08em] text-muted-foreground"><Radar size={13} className={active.length ? "cp-pulse text-info" : ""} />Running now ({active.length})</h2>
            <div className="rounded-xl border bg-card">{active.length ? active.map((c) => <Row key={c.id} c={c} action={<Link href={`/investigations/${c.id}`}><Button size="sm">Watch live</Button></Link>} />)
              : <div className="p-4"><EmptyState title="No active investigations" body="Start one from the list below." /></div>}</div>
          </section>
          {paused.length > 0 && <section>
            <h2 className="mb-2 text-[12px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Paused for a person ({paused.length})</h2>
            <div className="rounded-xl border bg-card">{paused.map((c) => <Row key={c.id} c={c} action={<Link href={`/claims/${c.id}`}><Button size="sm" variant="outline">Decide</Button></Link>} />)}</div>
          </section>}
          {fresh.length > 0 && <section>
            <h2 className="mb-2 text-[12px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Ready to investigate ({fresh.length})</h2>
            <div className="rounded-xl border bg-card">{fresh.map((c) => <Row key={c.id} c={c} action={<Button size="sm" onClick={() => run(c.id)} disabled={READ_ONLY}><Play size={13} /> Start</Button>} />)}</div>
          </section>}
          <section>
            <h2 className="mb-2 text-[12px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Completed ({done.length})</h2>
            <div className="rounded-xl border bg-card">{done.length ? done.map((c) => <Row key={c.id} c={c} action={<Link href={`/investigations/${c.id}`}><Button size="sm" variant="ghost">Replay trace</Button></Link>} />)
              : <div className="p-4"><EmptyState title="Nothing completed yet" /></div>}</div>
          </section>
        </div>
      )}
    </div>
  );
}
