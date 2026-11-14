"use client";
// Adapters that map the original page vocabulary onto the dark design system.
import type { ReactNode } from "react";
import { Metric, Tag, type Tone } from "@/components/common";
import { cn } from "@/lib/utils";
export { Button } from "@/components/ui/button";

export function Card({ children, className, pad = true }: { children: ReactNode; className?: string; pad?: boolean }) {
  return <div className={cn("rounded-xl border bg-card", pad && "p-5", className)}>{children}</div>;
}
export function SectionTitle({ children, right, className }: { children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <div className={cn("mb-3 flex items-center justify-between gap-3", className)}>
      <h3 className="text-[12px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{children}</h3>{right}
    </div>
  );
}
const MAP: Record<string, Tone> = { neutral: "neutral", ok: "verified", warn: "missing", bad: "risk", crit: "risk", accent: "info" };
export function Badge({ children, tone = "neutral", className }: { children: ReactNode; tone?: string; className?: string; dot?: boolean }) {
  return <Tag tone={MAP[tone] ?? "neutral"} className={className}>{children}</Tag>;
}
export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "ok" | "bad" | "warn" }) {
  return <Metric label={label} value={value} hint={sub} tone={tone ? MAP[tone] : undefined} />;
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">{children}</div>;
}
