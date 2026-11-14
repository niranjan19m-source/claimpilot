"use client";

import { AlertTriangle, Check, Copy, Inbox, RefreshCw } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Button } from "@/components/ui/button";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { Skeleton } from "@/components/ui/skeleton";
import type { ToolResult } from "@/lib/api";
import { TOOL_SOURCE } from "@/lib/agent-events";
import { cn } from "@/lib/utils";

// ------------------------------------------------------------------ semantic tones
export type Tone = "verified" | "risk" | "missing" | "info" | "neutral";
const TONE: Record<Tone, string> = {
  verified: "bg-verified-bg text-verified ring-verified-line",
  risk: "bg-risk-bg text-risk ring-risk-line",
  missing: "bg-missing-bg text-missing ring-missing-line",
  info: "bg-info-bg text-info ring-info-line",
  neutral: "bg-neutral-bg text-neutral ring-neutral-line",
};
export const toneText: Record<Tone, string> = {
  verified: "text-verified", risk: "text-risk", missing: "text-missing", info: "text-info", neutral: "text-muted-foreground",
};

export function Tag({ tone = "neutral", children, className, icon }: { tone?: Tone; children: ReactNode; className?: string; icon?: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset", TONE[tone], className)}>
      {icon}{children}
    </span>
  );
}

export const fraudTone = (s?: number | null): Tone => (s == null ? "neutral" : s >= 60 ? "risk" : s >= 30 ? "missing" : "verified");
export const fraudLabel = (s?: number | null) => (s == null ? "Not assessed" : s >= 60 ? "High" : s >= 30 ? "Elevated" : "Low");
export const severityTone = (s?: string | null): Tone => (s === "critical" || s === "high" ? "risk" : s === "medium" ? "missing" : s === "low" ? "verified" : "neutral");
export const coverageTone = (s?: string | null): Tone => (s === "covered" ? "verified" : s === "partially_covered" ? "info" : s === "not_covered" ? "risk" : s ? "missing" : "neutral");
export const statusTone = (s?: string | null): Tone =>
  s === "approved" || s === "assigned" ? "verified" : s === "awaiting_review" || s === "awaiting_documents" ? "missing"
    : s === "triaging" ? "info" : s === "error" || s === "interrupted" ? "risk" : "neutral";

// ------------------------------------------------------------------ layout
export function Panel({ title, action, children, className, bodyClass, id }: {
  title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; bodyClass?: string; id?: string;
}) {
  return (
    <section id={id} className={cn("rounded-xl border bg-card", className)}>
      {title && (
        <header className="flex min-h-11 items-center justify-between gap-3 border-b px-4 py-2.5">
          <h2 className="text-[12px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{title}</h2>
          {action}
        </header>
      )}
      <div className={cn("p-4", bodyClass)}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Metric({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: Tone }) {
  return (
    <div className="rounded-xl border bg-card px-4 py-3.5">
      <div className="text-[12px] text-muted-foreground">{label}</div>
      <div className={cn("mt-1 text-2xl font-semibold tracking-tight tabular", tone && toneText[tone])}>{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-subtle-foreground">{hint}</div>}
    </div>
  );
}

/** A score with its label and plain-language explanation; never colour alone. */
export function ScoreTile({ label, value, verdict, tone, explanation, meter }: {
  label: string; value: ReactNode; verdict: string; tone: Tone; explanation: ReactNode; meter?: number;
}) {
  return (
    <div className="rounded-lg border bg-raised p-3.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[12px] text-muted-foreground">{label}</span>
        <Tag tone={tone}>{verdict}</Tag>
      </div>
      <div className={cn("mt-1.5 text-xl font-semibold tabular", toneText[tone])}>{value}</div>
      {meter !== undefined && (
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/5" role="meter" aria-valuenow={meter} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
          <div className={cn("h-full rounded-full", { verified: "bg-verified", risk: "bg-risk", missing: "bg-missing", info: "bg-info", neutral: "bg-neutral" }[tone])}
            style={{ width: `${Math.max(2, Math.min(100, meter))}%` }} />
        </div>
      )}
      <p className="mt-2 text-[11px] leading-relaxed text-subtle-foreground">{explanation}</p>
    </div>
  );
}

// ------------------------------------------------------------------ states
export function EmptyState({ icon, title, body, action }: { icon?: ReactNode; title: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed px-6 py-10 text-center">
      <div className="mb-2 text-subtle-foreground">{icon ?? <Inbox size={20} />}</div>
      <div className="text-sm font-medium">{title}</div>
      {body && <div className="mt-1 max-w-sm text-[13px] text-muted-foreground">{body}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ title = "Something went wrong", message, onRetry }: { title?: string; message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-risk-line bg-risk-bg px-4 py-3">
      <AlertTriangle size={16} className="mt-0.5 shrink-0 text-risk" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-risk">{title}</div>
        <div className="mt-0.5 text-[13px] text-foreground/80">{message}</div>
      </div>
      {onRetry && <Button size="sm" variant="outline" onClick={onRetry}><RefreshCw size={13} /> Retry</Button>}
    </div>
  );
}

export function SkeletonRows({ rows = 4, className }: { rows?: number; className?: string }) {
  return <div className={cn("space-y-2", className)}>{Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>;
}

// ------------------------------------------------------------------ code
export function JsonViewer({ value, className, maxHeight = 360 }: { value: unknown; className?: string; maxHeight?: number }) {
  const [copied, setCopied] = useState(false);
  const text = JSON.stringify(value, null, 2);
  return (
    <div className={cn("relative rounded-lg border bg-sunken", className)}>
      <Button size="sm" variant="ghost" className="absolute right-1.5 top-1.5 h-7 px-2 text-[11px]"
        onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1200); }}
        aria-label="Copy JSON">
        {copied ? <Check size={12} /> : <Copy size={12} />} {copied ? "Copied" : "Copy"}
      </Button>
      <pre className="scroll-thin overflow-auto p-3 pr-20 font-mono text-[11.5px] leading-relaxed text-zinc-300" style={{ maxHeight }}>
        {highlight(text)}
      </pre>
    </div>
  );
}

function highlight(json: string) {
  // Minimal syntax colouring: keys, strings, numbers, booleans/null.
  const parts = json.split(/("(?:\\.|[^"\\])*"\s*:?|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)/g);
  return parts.map((p, i) => {
    if (!p) return null;
    if (/^".*":$/.test(p.trim())) return <span key={i} className="text-indigo-300">{p}</span>;
    if (p.startsWith('"')) return <span key={i} className="text-emerald-300/90">{p}</span>;
    if (/^(true|false|null)$/.test(p)) return <span key={i} className="text-amber-300">{p}</span>;
    if (/^-?\d/.test(p)) return <span key={i} className="text-sky-300">{p}</span>;
    return <span key={i}>{p}</span>;
  });
}

// ------------------------------------------------------------------ evidence citation
/** Inline evidence reference ([E4]) with a hover card showing what the tool actually returned. */
export function EvidenceChip({ id, entry, onOpen }: { id: string; entry?: ToolResult; onOpen?: (id: string) => void }) {
  const chip = (
    <button type="button" onClick={() => onOpen?.(id)}
      className="rounded bg-info-bg px-1.5 py-px font-mono text-[10.5px] font-medium text-info ring-1 ring-inset ring-info-line hover:bg-indigo-500/25">
      {id}
    </button>
  );
  if (!entry) return chip;
  return (
    <HoverCard openDelay={150}>
      <HoverCardTrigger asChild>{chip}</HoverCardTrigger>
      <HoverCardContent className="w-80 text-[12px]">
        <div className="flex items-center justify-between gap-2">
          <span className="font-semibold">{entry.label}</span>
          <Tag tone={!entry.ok ? "missing" : entry.signals.length ? "risk" : "verified"}>
            {!entry.ok ? "Degraded" : entry.signals.length ? `${entry.signals.length} flag(s)` : "Verified"}
          </Tag>
        </div>
        <p className="mt-1.5 leading-relaxed text-muted-foreground">{entry.summary}</p>
        <div className="mt-2 border-t pt-2 text-[11px] text-subtle-foreground">Source: {TOOL_SOURCE[entry.tool] ?? entry.tool} · {entry.ms} ms</div>
      </HoverCardContent>
    </HoverCard>
  );
}
