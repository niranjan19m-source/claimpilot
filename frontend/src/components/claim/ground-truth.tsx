"use client";

import { Download, FileText, Image as ImageIcon, Loader2, Minus, Plus, RotateCcw, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { EmptyState, Panel, Tag } from "@/components/common";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { API, ClaimDetail, ClaimDocument, dateTime, fileUrl, titleCase } from "@/lib/api";
import { cn } from "@/lib/utils";

const MAX_MB = 15;
const ALLOWED = [".pdf", ".jpg", ".jpeg", ".png", ".webp", ".txt"];

/** LEFT PANE — original claim material, shown separately from anything the agent derived. */
export function GroundTruthPane({ detail, onUploaded }: { detail: ClaimDetail; onUploaded: () => void }) {
  const docs = detail.documents;
  const [sel, setSel] = useState<number | null>(docs[0]?.id ?? null);
  const [zoom, setZoom] = useState(1);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (!docs.some((d) => d.id === sel)) setSel(docs[0]?.id ?? null); }, [docs, sel]);
  useEffect(() => setZoom(1), [sel]);
  const doc = docs.find((d) => d.id === sel);

  const upload = async (files: File[]) => {
    const bad = files.find((f) => !ALLOWED.some((x) => f.name.toLowerCase().endsWith(x)) || f.size > MAX_MB * 1e6);
    if (bad) { toast.error(`${bad.name}: allowed types ${ALLOWED.join(", ")} up to ${MAX_MB} MB`); return; }
    setBusy(true);
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    try {
      const r = await fetch(`${API}/api/claims/${detail.claim.id}/documents`, { method: "POST", body: fd });
      if (!r.ok) throw new Error((await r.json()).detail ?? r.statusText);
      const j = await r.json();
      toast.success(j.resumed ? "Uploaded — agent resumed and is re-planning" : `Uploaded ${j.saved.length} file(s)`);
      onUploaded();
    } catch (e: any) { toast.error(`Upload failed: ${e.message}`); }
    finally { setBusy(false); if (input.current) input.current.value = ""; }
  };

  const sample = async () => {
    const r = await fetch(`${API}/api/scenarios/${detail.claim.id}/upload-sample`);
    if (!r.ok) { toast.error("No sample document for this claim"); return; }
    await upload([new File([await r.blob()], "FIR_0871_2026.pdf", { type: "application/pdf" })]);
  };

  return (
    <Panel title="Ground truth · original material" bodyClass="p-0"
      action={<Button size="sm" variant="outline" onClick={() => input.current?.click()} disabled={busy}>
        {busy ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />} Upload</Button>}>
      <input ref={input} type="file" multiple accept={ALLOWED.join(",")} className="hidden" onChange={(e) => upload(Array.from(e.target.files ?? []))} />
      {detail.claim.status === "awaiting_documents" && (
        <div className="m-3 rounded-md border border-missing-line bg-missing-bg p-3 text-[12px] text-missing">
          The agent is paused waiting for claimant documents. Uploading resumes the investigation.
          {detail.claim.id === "CLM-2611-1005" && <Button size="sm" variant="outline" className="mt-2 w-full" onClick={sample} disabled={busy}>Simulate claimant uploading FIR</Button>}
        </div>
      )}
      {docs.length === 0 ? <div className="p-3"><EmptyState title="No documents uploaded" body="Upload the claim form, photos and supporting PDFs." /></div> : (
        <>
          <ScrollArea className="border-b">
            <div role="tablist" aria-label="Documents" className="flex gap-1 p-2">
              {docs.map((d) => (
                <button key={d.id} role="tab" aria-selected={d.id === sel} onClick={() => setSel(d.id)}
                  className={cn("flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px]",
                    d.id === sel ? "bg-white/[0.07] text-white ring-1 ring-white/10" : "text-zinc-400 hover:bg-white/[0.04]")}>
                  {d.kind === "photo" ? <ImageIcon size={13} /> : <FileText size={13} />}{d.kind === "photo" ? d.filename : d.label}
                </button>
              ))}
            </div>
          </ScrollArea>
          {doc && <DocumentViewer doc={doc} zoom={zoom} setZoom={setZoom} />}
        </>
      )}
    </Panel>
  );
}

function DocumentViewer({ doc, zoom, setZoom }: { doc: ClaimDocument; zoom: number; setZoom: (z: number) => void }) {
  const isImg = doc.kind === "photo" || doc.mime.startsWith("image/");
  const isPdf = doc.mime === "application/pdf" || doc.filename.toLowerCase().endsWith(".pdf");
  const fields = doc.meta?.fields;
  return (
    <div>
      <div className="flex items-center justify-between gap-2 px-3 py-2 text-[11.5px]">
        <div className="min-w-0">
          <div className="truncate font-medium text-zinc-200">{doc.filename}</div>
          <div className="text-zinc-500">{titleCase(doc.kind)} · {doc.mime} · uploaded {dateTime(doc.created_at)}</div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {isImg && <>
            <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => setZoom(Math.max(0.5, zoom - 0.25))} aria-label="Zoom out"><Minus size={13} /></Button>
            <span className="w-9 text-center font-mono text-[10.5px] text-zinc-500">{Math.round(zoom * 100)}%</span>
            <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => setZoom(Math.min(3, zoom + 0.25))} aria-label="Zoom in"><Plus size={13} /></Button>
            <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => setZoom(1)} aria-label="Reset zoom"><RotateCcw size={12} /></Button>
          </>}
          <Button size="icon" variant="ghost" className="h-7 w-7" asChild aria-label="Download">
            <a href={fileUrl(doc.id)} download={doc.filename}><Download size={13} /></a>
          </Button>
        </div>
      </div>
      <div className="mx-3 overflow-auto rounded-lg border bg-sunken scroll-thin" style={{ height: 380 }}>
        {isImg ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={fileUrl(doc.id)} alt={`Claim photo ${doc.filename}`} className="origin-top-left transition-transform"
            style={{ transform: `scale(${zoom})`, width: "100%" }} />
        ) : isPdf ? (
          <iframe src={`${fileUrl(doc.id)}#toolbar=0&view=FitH`} title={doc.filename} className="h-full w-full bg-white" />
        ) : (
          <div className="p-4 text-[12px] text-zinc-400">Preview not available for this file type. Use download.</div>
        )}
      </div>
      <div className="p-3">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-zinc-500">Processing</span>
          {isImg ? <Tag tone="info">Metadata read by forensics</Tag> : fields && Object.keys(fields).length ? <Tag tone="verified">Fields extracted</Tag>
            : <Tag>Text extracted</Tag>}
        </div>
        {fields && Object.keys(fields).length > 0 && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-md border bg-raised p-2.5 text-[11.5px]">
            {Object.entries(fields).filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && !v.length)).slice(0, 8).map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-zinc-500">{titleCase(k)}</dt>
                <dd className="truncate text-zinc-300">{Array.isArray(v) ? `${v.length} line items` : String(v)}</dd>
              </div>
            ))}
          </dl>
        )}
        <p className="mt-2 text-[10.5px] text-zinc-600">Fields above are machine-extracted from this file; the original is shown as received.</p>
      </div>
    </div>
  );
}
