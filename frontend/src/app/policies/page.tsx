"use client";

import { FileUp, Loader2, Search } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { EmptyState, ErrorState, PageHeader, Panel, SkeletonRows, Tag, Tone } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApi } from "@/hooks/use-api";
import { API, Evidence, dateTime, titleCase } from "@/lib/api";

type Clause = { product: string; id: string; title: string; text: string; kind: string; source: string; score?: number };
type Library = { products: { code: string; file: string }[]; clauses: Clause[]; uploads: { id: number; name: string; filename: string; status: string; created_at: string; clauses: { id: string; title: string }[] }[] };
const KIND_TONE: Record<string, Tone> = { exclusion: "risk", condition: "missing", waiting_period: "missing", limit: "info", coverage: "verified" };

export default function PolicyLibrary() {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [product, setProduct] = useState("all");
  const [kind, setKind] = useState("all");
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const qs = new URLSearchParams({ ...(query ? { q: query } : {}), ...(product !== "all" ? { product } : {}), ...(kind !== "all" ? { kind } : {}) }).toString();
  const lib = useApi<Library>(`/api/policy-library${qs ? `?${qs}` : ""}`);
  const ev = useApi<Evidence[]>("/api/evidence?category=policy");

  // Where the coverage engine applied each clause on investigated claims (the agent's interpretation).
  const applied = useMemo(() => {
    const m = new Map<string, { claim: string; outcome: string; note: string }[]>();
    for (const e of ev.data ?? []) {
      if (e.tool !== "check_coverage") continue;
      for (const b of e.data?.basis ?? []) m.set(b.clause_id, [...(m.get(b.clause_id) ?? []), { claim: e.claim_id, outcome: b.outcome, note: b.note }]);
    }
    return m;
  }, [ev.data]);

  const upload = async (f: File) => {
    setBusy(true);
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await fetch(`${API}/api/policy-library`, { method: "POST", body: fd });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail);
      toast.success(`Uploaded: ${j.status}`); lib.reload();
    } catch (e: any) { toast.error(e.message); } finally { setBusy(false); if (input.current) input.current.value = ""; }
  };

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Policy library" description="Policy wording as written, clause by clause. Each card keeps the extracted text, how the coverage engine applied it, and the human determination separate."
        actions={<><input ref={input} type="file" accept=".pdf,.md,.txt" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          <Button variant="outline" onClick={() => input.current?.click()} disabled={busy}>{busy ? <Loader2 size={14} className="animate-spin" /> : <FileUp size={14} />} Upload policy</Button></>} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <form onSubmit={(e) => { e.preventDefault(); setQuery(q); }} className="flex gap-2">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search wording, e.g. flood engine damage" className="h-8 w-80 text-[12.5px]" aria-label="Search policy text" />
          <Button size="sm" type="submit" variant="secondary"><Search size={13} /> Search</Button>
          {query && <Button size="sm" variant="ghost" onClick={() => { setQ(""); setQuery(""); }}>Clear</Button>}
        </form>
        <Tabs value={product} onValueChange={setProduct}><TabsList><TabsTrigger value="all">All</TabsTrigger><TabsTrigger value="MOTOR-PKG">Motor</TabsTrigger><TabsTrigger value="HEALTH-FLT">Health</TabsTrigger></TabsList></Tabs>
        <Tabs value={kind} onValueChange={setKind}><TabsList>{["all", "coverage", "exclusion", "condition", "waiting_period", "limit"].map((k) => <TabsTrigger key={k} value={k}>{titleCase(k)}</TabsTrigger>)}</TabsList></Tabs>
      </div>
      {lib.error ? <ErrorState message={lib.error} onRetry={lib.reload} /> : lib.loading && !lib.data ? <SkeletonRows rows={8} /> : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-2.5">
            {lib.data!.clauses.length === 0 ? <EmptyState title="No clauses match" /> : lib.data!.clauses.map((c) => {
              const uses = applied.get(c.id) ?? [];
              return (
                <article key={c.id} className="rounded-xl border bg-card p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[12px] text-zinc-400">{c.id}</span>
                    <h3 className="text-[14px] font-semibold">{c.title}</h3>
                    <Tag tone={KIND_TONE[c.kind] ?? "neutral"}>{titleCase(c.kind)}</Tag>
                    {c.score !== undefined && <span className="ml-auto font-mono text-[11px] text-zinc-500">relevance {c.score.toFixed(2)}</span>}
                  </div>
                  <div className="mt-2 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-zinc-500">Extracted policy text · {c.source}</div>
                  <blockquote className="mt-1 border-l-2 border-white/15 pl-3 text-[13px] leading-relaxed text-zinc-300">{c.text}</blockquote>
                  {uses.length > 0 && (
                    <details className="mt-3">
                      <summary className="cursor-pointer text-[12px] text-info">Agent interpretation · applied on {uses.length} claim(s)</summary>
                      <ul className="mt-2 space-y-1">{uses.map((u, i) => (
                        <li key={i} className="flex flex-wrap items-center gap-2 text-[12px]">
                          <a href={`/claims/${u.claim}`} className="font-mono text-info hover:underline">{u.claim}</a>
                          <Tag tone={u.outcome === "fail" ? "risk" : u.outcome === "applied" ? "info" : u.outcome === "pass" ? "verified" : "missing"}>{u.outcome.replace("_", " ")}</Tag>
                          <span className="text-zinc-400">{u.note}</span>
                        </li>))}</ul>
                      <p className="mt-1.5 text-[11px] text-zinc-500">The final coverage determination is made by the adjuster in each claim&apos;s decision center.</p>
                    </details>
                  )}
                </article>
              );
            })}
          </div>
          <div className="space-y-4">
            <Panel title="Wording documents">
              <ul className="space-y-2 text-[12.5px]">{lib.data!.products.map((p) => (
                <li key={p.code} className="flex items-center justify-between gap-2"><span>{p.code === "MOTOR-PKG" ? "Private car package" : "Family floater health"}</span><span className="font-mono text-[11px] text-zinc-500">{p.file}</span></li>))}</ul>
              <p className="mt-3 text-[11px] text-zinc-500">Synthetic wordings modelled on Indian policies. They are not any insurer&apos;s real wording.</p>
            </Panel>
            <Panel title="Uploaded policies">
              {lib.data!.uploads.length === 0 ? <p className="text-[12.5px] text-zinc-500">None yet. Upload PDF, Markdown or text wording. Numbered clauses are detected automatically.</p> : (
                <ul className="space-y-2.5">{lib.data!.uploads.map((u) => (
                  <li key={u.id} className="rounded-lg border bg-raised p-2.5 text-[12px]">
                    <div className="font-medium">{u.filename}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-zinc-500"><Tag tone={u.clauses.length ? "verified" : "missing"}>{u.status}</Tag>{dateTime(u.created_at)}</div>
                    {u.clauses.length > 0 && <ul className="mt-1.5 space-y-0.5 text-zinc-400">{u.clauses.slice(0, 5).map((c) => <li key={c.id}><span className="font-mono">{c.id}</span> {c.title}</li>)}</ul>}
                  </li>))}</ul>
              )}
              <p className="mt-2 text-[11px] text-zinc-500">Uploaded wordings are indexed for reference. Coverage rules run only on the two configured products.</p>
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}
