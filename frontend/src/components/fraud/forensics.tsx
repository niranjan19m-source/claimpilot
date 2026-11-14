"use client";

import { AlertTriangle, Camera, CheckCircle2, Fingerprint, Globe2, MapPin } from "lucide-react";
import Link from "next/link";
import { EmptyState, Panel, Tag } from "@/components/common";
import { ForensicMetadata, ToolResult, bytes, fileUrl } from "@/lib/api";

function Row({ k, v, mono }: { k: string; v: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-3 py-1 text-[12px]">
      <span className="shrink-0 text-zinc-500">{k}</span>
      <span className={`min-w-0 truncate text-right text-zinc-200 ${mono ? "font-mono text-[11px]" : ""}`}>{v ?? "—"}</span>
    </div>
  );
}

const FLAG_TEXT: Record<string, string> = {
  taken_before_incident: "Captured before the reported incident date",
  taken_before_policy: "Captured before the policy started",
  gps_far_from_incident: "GPS location far from the reported location",
  edited: "Processed in editing software",
};

export function ImageForensicsPanel({ entry, incidentDate, policyStart }: { entry?: ToolResult | null; incidentDate?: string; policyStart?: string }) {
  if (!entry) return <EmptyState icon={<Camera size={20} />} title="No image forensics for this claim" body="Photo forensics runs when damage photos are submitted." />;
  const photos: ForensicMetadata[] = entry.data.photos ?? [];
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2 rounded-lg border border-info-line bg-info-bg px-3 py-2 text-[12px] text-zinc-300">
        <AlertTriangle size={14} className="mt-0.5 shrink-0 text-info" />
        Photo metadata can be missing, stripped by messaging apps, or altered. Discrepancies here are investigation leads, not proof of fraud.
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {photos.map((p) => {
          const dup = p.flags.find((f) => f.startsWith("duplicate_of:"));
          return (
            <article key={p.filename} className="overflow-hidden rounded-xl border bg-raised">
              <div className="relative aspect-[16/9] bg-sunken">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={fileUrl(p.document_id)} alt={`Damage photo ${p.filename}`} className="h-full w-full object-cover" />
                <div className="absolute left-2 top-2 flex flex-wrap gap-1">
                  {p.flags.length ? <Tag tone="risk">{p.flags.length} discrepanc{p.flags.length > 1 ? "ies" : "y"}</Tag> : <Tag tone="verified" icon={<CheckCircle2 size={10} />}>No discrepancies</Tag>}
                </div>
              </div>
              <div className="p-3.5">
                <div className="font-mono text-[12px] text-zinc-200">{p.filename}</div>
                <div className="mt-2 grid gap-x-5 sm:grid-cols-2">
                  <div className="divide-y divide-white/5">
                    <Row k="Format" v={p.format} /><Row k="Dimensions" v={p.dimensions} /><Row k="File size" v={bytes(p.bytes)} />
                    <Row k="Camera" v={p.camera ?? "Not present"} />
                  </div>
                  <div className="divide-y divide-white/5">
                    <Row k="EXIF timestamp" v={p.taken_at ?? "Not present"} mono />
                    <Row k="GPS" v={p.lat != null ? `${p.lat.toFixed(4)}, ${p.lon?.toFixed(4)}` : "Not present"} mono />
                    <Row k="Software" v={p.software ?? "—"} />
                    <Row k="EXIF status" v={<Tag tone={p.exif_status === "present" ? "verified" : "missing"}>{p.exif_status}</Tag>} />
                  </div>
                </div>
                <div className="mt-2 space-y-0.5 border-t pt-2">
                  <Row k="SHA-256" v={p.sha256 ? `${p.sha256.slice(0, 20)}…` : "—"} mono />
                  <Row k="Perceptual hash" v={p.phash} mono />
                </div>
                {p.flags.length > 0 && (
                  <div className="mt-3 space-y-2">
                    {p.flags.filter((f) => !f.startsWith("duplicate_of")).map((f) => (
                      <div key={f} className="rounded-md border border-risk-line bg-risk-bg px-3 py-2 text-[12px]">
                        <div className="font-medium text-risk">{FLAG_TEXT[f] ?? f}</div>
                        {f.startsWith("taken_before") && (
                          <div className="mt-1 grid grid-cols-2 gap-2 font-mono text-[11px] text-zinc-300">
                            <div><div className="text-zinc-500">{f === "taken_before_policy" ? "Policy start" : "Reported incident"}</div>{f === "taken_before_policy" ? policyStart : incidentDate}</div>
                            <div><div className="text-zinc-500">Image EXIF</div>{p.taken_at}</div>
                          </div>
                        )}
                        {f === "gps_far_from_incident" && <div className="mt-1 text-zinc-300"><MapPin size={11} className="mr-1 inline" />{p.km_from_incident} km from the reported location</div>}
                      </div>
                    ))}
                    {dup && (
                      <div className="rounded-md border border-risk-line bg-risk-bg px-3 py-2 text-[12px]">
                        <div className="flex items-center gap-1.5 font-medium text-risk"><Fingerprint size={12} /> Matches a photo on an earlier claim</div>
                        <div className="mt-0.5 text-zinc-300">Perceptual-hash match against the internal claims photo index:{" "}
                          <span className="font-mono">{dup.split(":")[1]}</span>. Visual similarity survives re-compression and new EXIF data.</div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </article>
          );
        })}
      </div>
      <Panel title="Reverse image search (web)">
        <div className="flex items-start gap-3">
          <Globe2 size={18} className="mt-0.5 text-zinc-500" />
          <div className="text-[12.5px]">
            <div className="flex items-center gap-2"><span className="font-medium">External provider</span><Tag>Not configured</Tag></div>
            <p className="mt-1 text-zinc-400">No web reverse-image provider is connected, so no web matches are shown. Matching above uses ClaimPilot&apos;s
              internal index of previously submitted claim photos only. See <Link href="/settings" className="text-info hover:underline">Settings</Link>.</p>
          </div>
        </div>
      </Panel>
    </div>
  );
}
