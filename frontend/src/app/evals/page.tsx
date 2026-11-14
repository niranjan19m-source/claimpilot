"use client";

import clsx from "clsx";
import { useEffect, useState } from "react";
import { Badge, Card, Empty, SectionTitle, Stat } from "@/components/legacy";
import { QUEUE_LABEL, api, titleCase } from "@/lib/api";

type Res = {
  available: boolean; mode: string; generated_at: string; n: number;
  metrics: Record<string, number | null>;
  per_archetype: Record<string, { n: number; route_ok: number; coverage_ok: number }>;
  confusion: { expected: string; got: string; n: number }[];
  cases: any[];
};
const pct = (v?: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

export default function Evals() {
  const [r, setR] = useState<Res | null>(null);
  useEffect(() => { api<Res>("/api/evals").then(setR).catch(() => {}); }, []);
  if (!r) return null;
  if (!r.available) return <Empty>No results yet. Run <code className="font-mono">python -m evals.run_eval</code> in the backend.</Empty>;
  const m = r.metrics;
  const queues = Array.from(new Set(r.confusion.flatMap((c) => [c.expected, c.got]))).filter(Boolean);
  const cell = (e: string, g: string) => r.confusion.find((c) => c.expected === e && c.got === g)?.n ?? 0;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Evaluation</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          {r.n} labelled synthetic claims across {Object.keys(r.per_archetype).length} archetypes, run end-to-end through the agent graph
          ({r.mode} mode). Labels encode the intended real-world outcome. SIU referral rules were calibrated on this set, so the held-out
          archetype is the honest generalisation check.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Routing accuracy" value={pct(m.routing_accuracy)} />
        <Stat label="Coverage decision accuracy" value={pct(m.coverage_accuracy)} />
        <Stat label="Fraud precision" value={pct(m.fraud_precision)} sub="SIU referrals that were fraud" />
        <Stat label="Fraud recall" value={pct(m.fraud_recall)} sub="fraud cases referred to SIU" />
        <Stat label="False SIU rate (genuine)" value={pct(m.false_positive_rate_genuine)} tone={m.false_positive_rate_genuine ? "bad" : "ok"} />
        <Stat label="Held-out accuracy" value={pct(m.heldout_accuracy)} sub={`avg ${m.avg_tools} tools · ${m.avg_ms} ms / claim`} />
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <SectionTitle>Routing confusion matrix</SectionTitle>
          <div className="overflow-x-auto">
            <table className="text-[12px]">
              <thead><tr><th className="p-2 text-left text-muted-foreground">expected ↓ / got →</th>{queues.map((q) => <th key={q} className="p-2 font-medium text-muted-foreground">{(QUEUE_LABEL as Record<string, string>)[q] ?? q}</th>)}</tr></thead>
              <tbody>{queues.map((e) => (
                <tr key={e}><td className="p-2 font-medium">{(QUEUE_LABEL as Record<string, string>)[e] ?? e}</td>
                  {queues.map((g) => { const n = cell(e, g); return (
                    <td key={g} className={clsx("p-2 text-center tabular", n && e === g && "bg-verified-bg font-semibold text-verified", n && e !== g && "bg-risk-bg font-semibold text-risk", !n && "text-zinc-600")}>{n || "·"}</td>); })}
                </tr>))}</tbody>
            </table>
          </div>
        </Card>
        <Card>
          <SectionTitle>Per archetype</SectionTitle>
          <table className="w-full text-[13px]">
            <thead><tr className="text-left text-xs text-muted-foreground"><th className="pb-2 font-medium">Archetype</th><th className="pb-2 text-right font-medium">Cases</th><th className="pb-2 text-right font-medium">Route</th><th className="pb-2 text-right font-medium">Coverage</th></tr></thead>
            <tbody>{Object.entries(r.per_archetype).map(([k, v]) => (
              <tr key={k} className="border-t border-border"><td className="py-1.5">{titleCase(k)}{k.startsWith("heldout") && <Badge tone="accent" className="ml-2">held-out</Badge>}</td>
                <td className="text-right tabular">{v.n}</td>
                <td className={clsx("text-right tabular", v.route_ok < v.n && "text-risk")}>{v.route_ok}/{v.n}</td>
                <td className={clsx("text-right tabular", v.coverage_ok < v.n && "text-risk")}>{v.coverage_ok}/{v.n}</td></tr>))}</tbody>
          </table>
        </Card>
      </div>
      <p className="text-xs text-muted-foreground">Generated {new Date(r.generated_at).toLocaleString("en-IN")}. Reproduce with <code className="font-mono">python -m evals.run_eval</code> (add <code className="font-mono">--llm</code> for the full LLM agent).</p>
    </div>
  );
}
