"use client";

import { motion } from "framer-motion";
import { FileWarning, GripVertical, ShieldAlert, UserRoundCheck } from "lucide-react";
import Link from "next/link";
import { Tag, fraudLabel, fraudTone } from "@/components/common";
import { ClaimRow, QUEUE_LABEL, STATUS_LABEL, inr, titleCase } from "@/lib/api";
import { cn } from "@/lib/utils";

export function ClaimCard({ c, dragHandle, dragging }: { c: ClaimRow; dragHandle?: React.ReactNode; dragging?: boolean }) {
  return (
    <motion.article layout layoutId={`card-${c.id}`} transition={{ type: "spring", stiffness: 420, damping: 36 }}
      className={cn("group rounded-lg border bg-raised p-3 transition-colors hover:border-border-strong", dragging && "opacity-40")}>
      <div className="flex items-start justify-between gap-2">
        <Link href={`/claims/${c.id}`} className="min-w-0 focus-visible:outline-none">
          <div className="font-mono text-[11.5px] text-zinc-400 group-hover:text-indigo-300">{c.id}</div>
          <div className="mt-0.5 text-[15px] font-semibold tabular">{inr(c.amount_claimed)}</div>
        </Link>
        <div className="flex items-center gap-1">
          {c.priority && <Tag tone={c.priority === "P1" || c.priority === "P2" ? "risk" : "neutral"}>{c.priority}</Tag>}
          {dragHandle}
        </div>
      </div>
      <div className="mt-0.5 text-[12px] text-zinc-400">{titleCase(c.claim_type)} · {c.claimant} · {c.incident_date}</div>
      <div className="mt-2 flex items-center gap-3 text-[11.5px]">
        <span className="text-zinc-500">Risk <b className={cn("font-semibold", { verified: "text-verified", risk: "text-risk", missing: "text-missing", info: "text-info", neutral: "text-zinc-300" }[fraudTone(c.fraud_score)])}>
          {fraudLabel(c.fraud_score)}{c.fraud_score != null ? ` · ${Math.round(c.fraud_score)}` : ""}</b></span>
        {c.confidence != null && <span className="text-zinc-500">Confidence <b className="font-semibold text-zinc-300">{Math.round(c.confidence * 100)}%</b></span>}
      </div>
      {c.summary && <p className="mt-2 line-clamp-2 text-[11.5px] leading-relaxed text-zinc-400">{c.summary}</p>}
      <div className="mt-2 flex flex-wrap gap-1">
        {c.requires_human && <Tag tone="missing" icon={<UserRoundCheck size={10} />}>Human review required</Tag>}
        {c.flags.slice(0, 2).map((f) => <Tag key={f} tone="risk" icon={<ShieldAlert size={10} />}>{f}</Tag>)}
        {c.coverage_flags.length > 0 && <Tag tone="risk">Coverage issue</Tag>}
        {c.status === "awaiting_documents" && c.missing_documents.slice(0, 2).map((m) => <Tag key={m} tone="missing" icon={<FileWarning size={10} />}>{m}</Tag>)}
        {c.route && !["fast_track", "standard", "siu"].includes(c.route) && <Tag tone="info">{QUEUE_LABEL[c.route]}</Tag>}
        {c.status === "approved" && <Tag tone="verified">Auto-approved</Tag>}
        {c.status === "triaging" && <Tag tone="info">{STATUS_LABEL.triaging}</Tag>}
      </div>
    </motion.article>
  );
}

export const DragGrip = (props: React.HTMLAttributes<HTMLButtonElement>) => (
  <button type="button" aria-label="Drag to reroute" {...props}
    className="grid h-6 w-5 cursor-grab place-items-center rounded text-zinc-600 hover:bg-white/5 hover:text-zinc-300 active:cursor-grabbing">
    <GripVertical size={13} />
  </button>
);
