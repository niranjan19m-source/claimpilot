"use client";

import Link from "next/link";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { EmptyState, ErrorState, Metric, PageHeader, Panel, SkeletonRows, Tag } from "@/components/common";
import { useApi } from "@/hooks/use-api";
import { QUEUE_LABEL, Queue, titleCase } from "@/lib/api";

type Analytics = {
  scope: { live_claims: number; triaged: number; note: string };
  routes: { queue: string; label: string; count: number }[];
  risk_bands: { band: string; count: number }[];
  severity: { level: string; count: number }[];
  triage_times: { claim_id: string; seconds: number; tools: number }[];
  missing_documents: { document: string; count: number }[];
  discrepancies: { signal: string; count: number }[];
  human_decisions: Record<string, number> & { total: number };
  history_outcomes: { outcome: string; count: number }[];
};

const AXIS = { stroke: "#52525b", fontSize: 11, tickLine: false, axisLine: false } as const;
const GRID = <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />;
const TIP = { contentStyle: { background: "#141417", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 12 }, cursor: { fill: "rgba(255,255,255,0.03)" }, labelStyle: { color: "#e4e4e7" } };
const BAND_COLOR: Record<string, string> = { low: "#34d399", medium: "#fbbf24", high: "#fb7185" };
const SEV_COLOR: Record<string, string> = { low: "#34d399", medium: "#fbbf24", high: "#fb923c", critical: "#fb7185" };
const ROUTE_COLOR: Record<string, string> = { fast_track: "#34d399", standard: "#818cf8", senior: "#a78bfa", medical: "#38bdf8", siu: "#fb7185", coverage_review: "#fbbf24" };

function ChartPanel({ title, empty, children, height = 220 }: { title: string; empty: boolean; children: React.ReactElement; height?: number }) {
  return (
    <Panel title={title}>
      {empty ? <EmptyState title="No data yet" body="Run investigations to populate this chart." /> :
        <div style={{ height }}><ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer></div>}
    </Panel>
  );
}

export default function AnalyticsPage() {
  const { data, error, loading, reload } = useApi<Analytics>("/api/analytics", 10000);
  if (error && !data) return <ErrorState title="Analytics unavailable" message={error} onRetry={reload} />;
  if (loading || !data) return <SkeletonRows rows={8} />;
  const d = data;
  const hd = d.human_decisions;
  const overrides = (hd.override ?? 0) + (hd.escalate_senior ?? 0) + (hd.further_investigation ?? 0);
  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader title="Analytics" description={<>Operational metrics computed live from the database. <Tag tone="missing">Synthetic demo book</Tag> {d.scope.triaged} of {d.scope.live_claims} open claims investigated.</>}
        actions={<Link href="/evals" className="text-[13px] text-info hover:underline">Accuracy evaluation →</Link>} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric label="Investigated" value={d.scope.triaged} />
        <Metric label="Median time to decision" value={d.triage_times.length ? `${[...d.triage_times].sort((a, b) => a.seconds - b.seconds)[Math.floor(d.triage_times.length / 2)].seconds}s` : "—"} />
        <Metric label="Human decisions" value={hd.total} />
        <Metric label="Human override rate" value={hd.total ? `${Math.round((100 * overrides) / hd.total)}%` : "—"} hint={`${overrides} reroutes of ${hd.total} decisions`} tone={overrides ? "missing" : undefined} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
        <ChartPanel title="Claims by routing category" empty={!d.routes.length}>
          <BarChart data={d.routes.map((r) => ({ ...r, short: QUEUE_LABEL[r.queue as Queue] ?? r.label }))}>{GRID}<XAxis dataKey="short" {...AXIS} interval={0} tick={{ fontSize: 10.5 }} /><YAxis {...AXIS} allowDecimals={false} width={24} /><Tooltip {...TIP} />
            <Bar dataKey="count" name="Claims" radius={[4, 4, 0, 0]}>{d.routes.map((r) => <Cell key={r.queue} fill={ROUTE_COLOR[r.queue] ?? "#818cf8"} />)}</Bar></BarChart>
        </ChartPanel>
        <ChartPanel title="Fraud risk distribution" empty={!d.risk_bands.some((b) => b.count)}>
          <BarChart data={d.risk_bands.map((b) => ({ ...b, label: b.band === "medium" ? "Elevated (30–59)" : b.band === "high" ? "High (≥60)" : "Low (<30)" }))}>{GRID}
            <XAxis dataKey="label" {...AXIS} /><YAxis {...AXIS} allowDecimals={false} width={24} /><Tooltip {...TIP} />
            <Bar dataKey="count" name="Claims" radius={[4, 4, 0, 0]}>{d.risk_bands.map((b) => <Cell key={b.band} fill={BAND_COLOR[b.band]} />)}</Bar></BarChart>
        </ChartPanel>
        <ChartPanel title="Severity mix" empty={!d.severity.some((s) => s.count)}>
          <BarChart data={d.severity.map((s) => ({ ...s, label: titleCase(s.level) }))}>{GRID}<XAxis dataKey="label" {...AXIS} /><YAxis {...AXIS} allowDecimals={false} width={24} /><Tooltip {...TIP} />
            <Bar dataKey="count" name="Claims" radius={[4, 4, 0, 0]}>{d.severity.map((s) => <Cell key={s.level} fill={SEV_COLOR[s.level]} />)}</Bar></BarChart>
        </ChartPanel>
        <ChartPanel title="Investigation time to decision (seconds)" empty={!d.triage_times.length}>
          <BarChart data={d.triage_times}>{GRID}<XAxis dataKey="claim_id" {...AXIS} tick={{ fontSize: 10 }} tickFormatter={(v) => v.slice(-4)} /><YAxis {...AXIS} width={28} /><Tooltip {...TIP} />
            <Bar dataKey="seconds" name="Seconds" fill="#818cf8" radius={[4, 4, 0, 0]} /></BarChart>
        </ChartPanel>
        <ChartPanel title="Most common discrepancy categories" empty={!d.discrepancies.length} height={Math.max(180, d.discrepancies.length * 30)}>
          <BarChart data={d.discrepancies} layout="vertical" margin={{ left: 8 }}>
            <XAxis type="number" {...AXIS} allowDecimals={false} /><YAxis type="category" dataKey="signal" {...AXIS} width={190} tick={{ fontSize: 10.5 }} /><Tooltip {...TIP} />
            <Bar dataKey="count" name="Claims" fill="#fb7185" radius={[0, 4, 4, 0]} barSize={14} /></BarChart>
        </ChartPanel>
        <ChartPanel title="Missing-document frequency" empty={!d.missing_documents.length} height={Math.max(120, d.missing_documents.length * 44 + 40)}>
          <BarChart data={d.missing_documents} layout="vertical">
            <XAxis type="number" {...AXIS} allowDecimals={false} /><YAxis type="category" dataKey="document" {...AXIS} width={150} tick={{ fontSize: 10.5 }} /><Tooltip {...TIP} />
            <Bar dataKey="count" name="Claims" fill="#fbbf24" radius={[0, 4, 4, 0]} barSize={18} /></BarChart>
        </ChartPanel>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel title="Human decisions by type">
          {hd.total === 0 ? <p className="text-[12.5px] text-zinc-500">No human decisions recorded yet.</p> : (
            <ul className="space-y-1.5 text-[12.5px]">{Object.entries(hd).filter(([k]) => k !== "total").map(([k, v]) => (
              <li key={k} className="flex justify-between"><span className="text-zinc-400">{titleCase(k)}</span><span className="tabular">{v}</span></li>))}</ul>
          )}
        </Panel>
        <Panel title="Historical book outcomes (339 past claims)">
          <ul className="space-y-1.5 text-[12.5px]">{d.history_outcomes.map((h) => (
            <li key={h.outcome} className="flex justify-between"><span className="text-zinc-400">{titleCase(h.outcome)}</span><span className="tabular">{h.count}</span></li>))}</ul>
        </Panel>
      </div>
    </div>
  );
}
