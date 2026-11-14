"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge, Card, SectionTitle } from "@/components/legacy";
import { api, inrShort, titleCase } from "@/lib/api";

type Handler = { id: string; name: string; role: string; lines: string[]; authority_limit: number; open_cases: number; region: string;
  assigned_live: { claim_id: string; priority: string; sla_due: string; queue: string; status: string }[] };

const ROLE_ORDER = ["fast_track", "adjuster", "senior_adjuster", "medical_reviewer", "siu"];

export default function Handlers() {
  const [rows, setRows] = useState<Handler[]>([]);
  useEffect(() => { const l = () => api<Handler[]>("/api/handlers").then(setRows).catch(() => {}); l(); const t = setInterval(l, 5000); return () => clearInterval(t); }, []);
  const max = Math.max(1, ...rows.map((r) => r.open_cases));
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Handlers &amp; workload</h1>
        <p className="mt-1 text-sm text-muted-foreground">The router picks a handler by role, line of business, authority limit, region, then lightest caseload.</p>
      </div>
      {ROLE_ORDER.map((role) => {
        const group = rows.filter((r) => r.role === role);
        if (!group.length) return null;
        return (
          <section key={role}>
            <SectionTitle>{titleCase(role)}</SectionTitle>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {group.map((h) => (
                <Card key={h.id}>
                  <div className="flex items-start justify-between gap-2">
                    <div><div className="font-semibold">{h.name}</div>
                      <div className="mt-0.5 text-xs text-muted-foreground">{h.lines.map(titleCase).join(" · ")} · {h.region} · authority {inrShort(h.authority_limit)}</div></div>
                    <span className="text-2xl font-semibold tabular">{h.open_cases}</span>
                  </div>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/5"><div className="h-full bg-indigo-500" style={{ width: `${(h.open_cases / max) * 100}%` }} /></div>
                  {h.assigned_live.length > 0 && (
                    <ul className="mt-3 space-y-1 border-t border-border pt-3">
                      {h.assigned_live.map((t) => (
                        <li key={t.claim_id} className="flex items-center justify-between text-[13px]">
                          <Link href={`/claims/${t.claim_id}`} className="font-mono text-xs text-info hover:underline">{t.claim_id}</Link>
                          <span className="flex items-center gap-2"><Badge tone={t.priority === "P1" ? "crit" : t.priority === "P2" ? "bad" : "neutral"}>{t.priority}</Badge>
                            <span className="text-xs text-muted-foreground">{t.status === "auto_approved" ? "auto-approved" : `SLA ${new Date(t.sla_due).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}`}</span></span>
                        </li>))}
                    </ul>)}
                </Card>))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
