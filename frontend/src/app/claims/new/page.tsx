"use client";

import { Loader2, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Card, SectionTitle } from "@/components/legacy";
import { API, READ_ONLY, READ_ONLY_MSG, api } from "@/lib/api";

const MOTOR_TYPES = ["collision", "windshield", "theft", "flood", "storm", "hailstorm", "fire", "vandalism"];
const input = "h-10 w-full rounded-lg border border-border-strong bg-card px-3 text-sm outline-none focus:border-indigo-400";

export default function NewClaim() {
  const router = useRouter();
  const [f, setF] = useState({
    policy_no: "MOT-77006", claim_type: "collision", incident_date: "2026-11-12", incident_time: "18:30",
    location: "Banjara Hills Road No. 12", city: "Hyderabad", amount_claimed: "45000", injury: "none",
    third_party_injury: false, insured_member: "", contact_phone: "",
    description: "Another car reversed into my parked car outside a restaurant. Rear bumper cracked and tail lamp broken.",
  });
  const [files, setFiles] = useState<File[]>([]);
  const [policy, setPolicy] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = (k: string, v: unknown) => setF((s) => ({ ...s, [k]: v }));

  const lookup = async () => {
    try { const p = await api<any>(`/api/policies/${f.policy_no}`); setPolicy(p);
      if (p.line === "health") set("claim_type", "hospitalization"); } catch { setPolicy({ error: true }); }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    const fd = new FormData();
    Object.entries(f).forEach(([k, v]) => fd.append(k, String(v)));
    files.forEach((x) => fd.append("files", x));
    try {
      const r = await fetch(`${API}/api/claims`, { method: "POST", body: fd });
      if (!r.ok) throw new Error((await r.json()).detail ?? r.statusText);
      const { id } = await r.json();
      router.push(`/investigations/${id}`);
    } catch (e: any) { setErr(e.message); setBusy(false); }
  };

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight">First notice of loss</h1>
      <p className="mt-1 text-sm text-muted-foreground">Submit a claim. The agent starts triage the moment it lands.</p>
      <form onSubmit={submit} className="mt-6 space-y-5">
        <Card>
          <SectionTitle>Policy</SectionTitle>
          <div className="flex gap-2">
            <input className={input} value={f.policy_no} onChange={(e) => set("policy_no", e.target.value)} onBlur={lookup} placeholder="Policy number" />
            <Button variant="secondary" onClick={lookup}>Look up</Button>
          </div>
          {policy && (policy.error ? <div className="mt-2 text-xs text-risk">Policy not found. The agent will still triage and flag it.</div> :
            <div className="mt-2 text-xs text-muted-foreground">{policy.product} · {policy.status} · {policy.start_date} → {policy.end_date}
              {policy.vehicle && ` · ${policy.vehicle}`}{policy.members?.length ? ` · members: ${policy.members.join(", ")}` : ""}</div>)}
          <div className="mt-3 text-xs text-muted-foreground">Try: MOT-77001 (Bengaluru), MOT-77006 (Hyderabad), HLT-88008 (Mumbai health), MOT-77002 (Pune).</div>
        </Card>
        <Card>
          <SectionTitle>Incident</SectionTitle>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="text-[13px]"><span className="mb-1 block text-muted-foreground">Type of loss</span>
              <select className={input} value={f.claim_type} onChange={(e) => set("claim_type", e.target.value)}>
                {[...MOTOR_TYPES, "hospitalization"].map((t) => <option key={t} value={t}>{t}</option>)}
              </select></label>
            <label className="text-[13px]"><span className="mb-1 block text-muted-foreground">Amount claimed (₹)</span>
              <input className={input} type="number" value={f.amount_claimed} onChange={(e) => set("amount_claimed", e.target.value)} /></label>
            <label className="text-[13px]"><span className="mb-1 block text-muted-foreground">Date of loss</span>
              <input className={input} type="date" value={f.incident_date} onChange={(e) => set("incident_date", e.target.value)} /></label>
            <label className="text-[13px]"><span className="mb-1 block text-muted-foreground">Time</span>
              <input className={input} type="time" value={f.incident_time} onChange={(e) => set("incident_time", e.target.value)} /></label>
            <label className="text-[13px]"><span className="mb-1 block text-muted-foreground">Location</span>
              <input className={input} value={f.location} onChange={(e) => set("location", e.target.value)} /></label>
            <label className="text-[13px]"><span className="mb-1 block text-muted-foreground">City</span>
              <input className={input} value={f.city} onChange={(e) => set("city", e.target.value)} /></label>
            <label className="text-[13px]"><span className="mb-1 block text-muted-foreground">Injury (insured / driver)</span>
              <select className={input} value={f.injury} onChange={(e) => set("injury", e.target.value)}>
                {["none", "minor", "serious", "fatal"].map((t) => <option key={t}>{t}</option>)}</select></label>
            <label className="text-[13px]"><span className="mb-1 block text-muted-foreground">Patient name (health)</span>
              <input className={input} value={f.insured_member} onChange={(e) => set("insured_member", e.target.value)} /></label>
          </div>
          <label className="mt-4 flex items-center gap-2 text-[13px]">
            <input type="checkbox" checked={f.third_party_injury} onChange={(e) => set("third_party_injury", e.target.checked)} /> A third party was injured
          </label>
          <label className="mt-4 block text-[13px]"><span className="mb-1 block text-muted-foreground">What happened?</span>
            <textarea className="h-28 w-full resize-none rounded-lg border border-border-strong px-3 py-2 text-sm outline-none focus:border-indigo-400"
              value={f.description} onChange={(e) => set("description", e.target.value)} /></label>
        </Card>
        <Card>
          <SectionTitle>Documents &amp; photos</SectionTitle>
          <label className="flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-border-strong px-4 py-8 text-center hover:bg-raised">
            <Upload size={20} className="text-muted-foreground" />
            <span className="mt-2 text-sm">Drop or choose files</span>
            <span className="text-xs text-muted-foreground">Photos (JPEG with EXIF), estimates, FIR, bills, discharge summary (PDF)</span>
            <input type="file" multiple className="hidden" onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
          </label>
          {files.length > 0 && <ul className="mt-3 space-y-1 text-[13px]">{files.map((x) => <li key={x.name} className="font-mono text-xs">{x.name}</li>)}</ul>}
        </Card>
        {err && <div className="text-sm text-risk">{err}</div>}
        <div className="flex justify-end">
          {READ_ONLY && <span className="mr-3 self-center text-[12.5px] text-missing">{READ_ONLY_MSG}</span>}<Button type="submit" disabled={busy || READ_ONLY}>{busy && <Loader2 size={15} className="animate-spin" />} Submit and start triage</Button>
        </div>
      </form>
    </div>
  );
}
