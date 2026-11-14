"use client";

import { EvidenceChip, Panel, ScoreTile, Tag, Tone, coverageTone, fraudLabel, fraudTone, severityTone } from "@/components/common";
import { ClaimDetail, ToolResult, dateTime, inr, maskPolicy, titleCase } from "@/lib/api";

type FactStatus = "verified" | "discrepancy" | "declared" | "not_checked" | "degraded";
const STATUS_META: Record<FactStatus, { label: string; tone: Tone }> = {
  verified: { label: "Verified", tone: "verified" },
  discrepancy: { label: "Discrepancy", tone: "risk" },
  declared: { label: "Declared, unverified", tone: "neutral" },
  not_checked: { label: "Not checked", tone: "neutral" },
  degraded: { label: "Check failed", tone: "missing" },
};
type Fact = { label: string; value: string; source: string; status: FactStatus; evidence?: string };

/** Builds the extracted-facts table from the evidence ledger. Each fact names its
 *  source and whether a tool confirmed it; nothing here is inferred by the UI. */
function deriveFacts(d: ClaimDetail): Fact[] {
  const c = d.claim, t = c.triage ?? {};
  const led = t.ledger ?? [];
  const last = (tool: string) => [...led].reverse().find((e) => e.tool === tool);
  const has = (e: ToolResult | undefined, code: string) => !!e?.signals.some((s) => s.code === code);
  const docs = last("review_documents"), pol = last("lookup_policy"), wx = last("check_weather"), geo = last("geocode_location");
  const reg = last("vehicle_registry"), cov = last("check_coverage"), photos = last("photo_forensics"), net = last("network_analysis");
  const facts: Fact[] = [];
  const dateIssue = has(docs, "FIR_DATE_MISMATCH") || has(docs, "ADMISSION_DATE_MISMATCH") || has(photos, "EXIF_PREDATES_LOSS");
  facts.push({ label: "Incident date", value: c.incident_date + (c.incident_time ? ` ${c.incident_time}` : ""), source: "Claim form",
    status: dateIssue ? "discrepancy" : docs || photos ? "verified" : "declared", evidence: (dateIssue ? (has(photos, "EXIF_PREDATES_LOSS") ? photos : docs) : docs)?.id });
  facts.push({ label: "Reported location", value: `${c.location}, ${c.city}`, source: geo ? `Geocoded: ${geo.data?.matched ?? ""}` : "Claim form",
    status: !geo ? "declared" : geo.ok ? "verified" : "degraded", evidence: geo?.id });
  if (wx) facts.push({ label: "Weather conditions", value: wx.ok ? `${wx.data.rain_72h_mm} mm rain in 72h before loss` : "Unavailable",
    source: `Open-Meteo archive (${wx.data?.source ?? "—"})`, status: !wx.ok ? "degraded" : wx.data.consistent ? "verified" : "discrepancy", evidence: wx.id });
  const est = docs?.data?.extracted?.repair_estimate ?? docs?.data?.extracted?.hospital_bill;
  facts.push({ label: c.line === "health" ? "Hospital bill" : "Estimated damage", value: est?.total ? inr(est.total) : inr(c.amount_claimed),
    source: est?.total ? (c.line === "health" ? "Itemised hospital bill" : "Repair estimate") : "Claim form",
    status: has(docs, "AMOUNT_MISMATCH") ? "discrepancy" : est?.total ? "verified" : "declared", evidence: docs?.id });
  if (pol) facts.push({ label: "Policy status", value: pol.ok ? `${titleCase(pol.data.status)}, ${pol.data.days_since_policy_start} days into cover` : "Not found",
    source: "Policy admin system", status: !pol.ok ? "discrepancy" : pol.data.incident_in_period && pol.data.premium_paid ? "verified" : "discrepancy", evidence: pol.id });
  if (cov) facts.push({ label: "Policy coverage", value: titleCase(cov.data.status), source: "Coverage rules engine",
    status: cov.data.status === "covered" || cov.data.status === "partially_covered" ? "verified" : cov.data.status === "needs_info" ? "declared" : "discrepancy", evidence: cov.id });
  if (reg) facts.push({ label: "Vehicle", value: reg.ok ? `${reg.data.make_model} (${reg.data.year})` : "Not found", source: "Vehicle registry (mock)",
    status: !reg.ok ? "discrepancy" : reg.signals.length ? "discrepancy" : "verified", evidence: reg.id });
  if (d.garage) facts.push({ label: "Repair garage", value: d.garage.name, source: net ? "Claim + link analysis" : "Claim form",
    status: net ? (net.signals.some((s) => s.code.startsWith("GARAGE")) ? "discrepancy" : "verified") : "not_checked", evidence: net?.id });
  if (d.hospital) facts.push({ label: "Hospital", value: d.hospital.name, source: "Claim + hospital registry",
    status: d.hospital.flagged ? "discrepancy" : "verified" });
  if (photos) facts.push({ label: "Photo metadata", value: `${photos.data.photos?.length ?? 0} photo(s), ${photos.data.photos?.filter((p: any) => p.flags?.length).length ?? 0} flagged`,
    source: "EXIF + perceptual hash", status: photos.signals.length ? "discrepancy" : "verified", evidence: photos.id });
  const missing = t.assessment?.documents.missing ?? [];
  facts.push({ label: "Document consistency", value: missing.length ? `Missing: ${missing.join(", ")}` : "Checklist complete",
    source: "Document review", status: missing.length ? "discrepancy" : docs ? "verified" : "not_checked", evidence: docs?.id });
  return facts;
}

/** CENTER PANE — structured synthesis produced by the agent. */
export function SynthesisPane({ detail, openEvidence }: { detail: ClaimDetail; openEvidence: (id: string) => void }) {
  const c = detail.claim, t = c.triage ?? {}, a = t.assessment;
  const ledger = Object.fromEntries((t.ledger ?? []).map((e) => [e.id, e]));
  const vehicle = detail.policy?.details?.vehicle;
  const docsReq = (t.ledger ?? []).find((e) => e.tool === "review_documents")?.data;
  const completeness = docsReq?.required?.length ? Math.round(100 * (docsReq.required.length - docsReq.missing.length) / docsReq.required.length) : null;
  const facts = deriveFacts(detail);

  return (
    <div className="space-y-4">
      <Panel title="Claim">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2.5 text-[12.5px] md:grid-cols-4">
          {[
            ["Claim ID", <span key="i" className="font-mono">{c.id}</span>],
            ["Claimant", detail.customer?.name ?? "—"],
            ["Policy", <span key="p" className="font-mono">{maskPolicy(c.policy_no)}</span>],
            ["Category", `${titleCase(c.line)} · ${titleCase(c.claim_type)}`],
            ["Incident date", c.incident_date],
            ["Reported", c.reported_date],
            ["Location", `${c.location}, ${c.city}`],
            ["Amount claimed", <span key="a" className="tabular font-semibold">{inr(c.amount_claimed)}</span>],
            ...(vehicle ? [["Vehicle", `${vehicle.make_model} (${vehicle.year})`], ["Registration", <span key="r" className="font-mono">{vehicle.reg}</span>]] : []),
            ...(c.insured_member ? [["Patient", c.insured_member]] : []),
          ].map(([k, v]) => (
            <div key={String(k)} className="min-w-0"><dt className="text-zinc-500">{k}</dt><dd className="truncate text-zinc-200">{v}</dd></div>
          ))}
        </dl>
        <p className="mt-3 border-t pt-3 text-[12.5px] leading-relaxed text-zinc-400"><span className="text-zinc-500">Claimant&apos;s account (unverified): </span>{c.description}</p>
      </Panel>

      {a ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <ScoreTile label="Fraud risk" value={a.fraud.score} verdict={fraudLabel(a.fraud.score)} tone={fraudTone(a.fraud.score)} meter={a.fraud.score}
            explanation={`Rule-based indicator from ${a.fraud.signals.length} flag(s). Not a probability; it says how much to investigate.`} />
          <ScoreTile label="Claim severity" value={titleCase(a.severity.level)} verdict={`${a.severity.points} pts`} tone={severityTone(a.severity.level)}
            explanation={a.severity.reasons.slice(0, 2).join("; ")} />
          <ScoreTile label="Evidence completeness" value={completeness == null ? "—" : `${completeness}%`} meter={completeness ?? 0}
            verdict={completeness === 100 ? "Complete" : completeness == null ? "Unknown" : "Incomplete"} tone={completeness === 100 ? "verified" : "missing"}
            explanation={docsReq ? `${docsReq.required.length - docsReq.missing.length} of ${docsReq.required.length} required documents on file.` : "Document review not run."} />
          <ScoreTile label="Agent confidence" value={`${Math.round(a.confidence * 100)}%`} meter={a.confidence * 100}
            verdict={a.confidence >= 0.85 ? "High" : a.confidence >= 0.6 ? "Moderate" : "Low"} tone={a.confidence >= 0.85 ? "verified" : a.confidence >= 0.6 ? "missing" : "risk"}
            explanation="From the verifier: falls when required checks fail or evidence is unavailable." />
        </div>
      ) : null}

      <Panel title="Extracted facts" action={<span className="text-[11px] text-zinc-500">source and verification for each field</span>} bodyClass="p-0">
        <table className="w-full text-[12.5px]">
          <thead><tr className="border-b text-left text-[11px] text-zinc-500">
            <th className="px-4 py-2 font-medium">Field</th><th className="px-4 py-2 font-medium">Value</th>
            <th className="hidden px-4 py-2 font-medium md:table-cell">Source</th><th className="px-4 py-2 font-medium">Status</th></tr></thead>
          <tbody>
            {facts.map((f) => (
              <tr key={f.label} className="border-b last:border-0">
                <td className="px-4 py-2 text-zinc-400">{f.label}</td>
                <td className="px-4 py-2 text-zinc-200">{f.value}</td>
                <td className="hidden px-4 py-2 text-[11.5px] text-zinc-500 md:table-cell">{f.source}</td>
                <td className="px-4 py-2"><span className="flex items-center gap-1.5"><Tag tone={STATUS_META[f.status].tone}>{STATUS_META[f.status].label}</Tag>
                  {f.evidence && <EvidenceChip id={f.evidence} entry={ledger[f.evidence]} onOpen={openEvidence} />}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      {a && (
        <Panel title="Coverage & payable estimate" action={<Tag tone={coverageTone(a.coverage.status)}>{titleCase(a.coverage.status)}</Tag>}>
          <table className="w-full text-[12.5px]"><tbody>
            {a.coverage.payable.lines.map((l, i) => (
              <tr key={i} className="border-b last:border-0"><td className="py-1.5 pr-3 text-zinc-400">{l.label}</td>
                <td className={`py-1.5 text-right tabular ${l.amount < 0 ? "text-risk" : "text-zinc-200"}`}>{inr(l.amount)}</td></tr>
            ))}
            <tr><td className="pt-2.5 font-medium">Estimated payable (agent estimate, subject to adjuster)</td><td className="pt-2.5 text-right text-[15px] font-semibold tabular">{inr(a.coverage.payable.net)}</td></tr>
          </tbody></table>
          {t.decision_ms ? <p className="mt-2 text-[11px] text-zinc-500">Decision reached {(t.decision_ms / 1000).toFixed(1)}s after intake · {dateTime(c.created_at)}</p> : null}
        </Panel>
      )}
    </div>
  );
}
