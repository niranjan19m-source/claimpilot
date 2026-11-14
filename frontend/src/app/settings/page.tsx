"use client";

import { ErrorState, PageHeader, Panel, SkeletonRows, Tag, Tone } from "@/components/common";
import { useApi } from "@/hooks/use-api";
import { SystemStatus, titleCase } from "@/lib/api";

type Settings = { llm_provider: string; primary_model: string; fast_model: string; anthropic_key_configured: boolean; max_tool_calls: number;
  demo_pace_seconds: number; network_enabled: boolean; queues: Record<string, string> };
const STATE_TONE: Record<string, Tone> = { connected: "verified", online: "verified", mock: "info", degraded: "missing", not_configured: "neutral", disabled: "neutral", unavailable: "risk" };
const LABEL: Record<string, string> = { policy_database: "Policy database", llm_provider: "LLM provider", weather_api: "Weather API (Open-Meteo)",
  geocoder: "Geocoder (OpenStreetMap Nominatim)", vehicle_registry: "Vehicle registry", reverse_image_search: "Reverse image search" };

export default function SettingsPage() {
  const s = useApi<Settings>("/api/settings");
  const st = useApi<SystemStatus>("/api/status", 30000);
  if (s.error && !s.data) return <ErrorState message={s.error} onRetry={s.reload} />;
  if (!s.data || !st.data) return <SkeletonRows rows={8} />;
  const c = s.data;
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Settings" description="Runtime configuration as reported by the backend. Secrets are never sent to the browser; the API only reports whether a key is configured." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Agent">
          <dl className="space-y-2 text-[13px]">
            {[["Mode", st.data.agent.mode === "llm" ? "LLM agent" : "Deterministic (rules + tools)"], ["LLM provider", c.llm_provider === "none" ? "None configured" : "Anthropic"],
              ["Primary model", c.primary_model], ["Intake model", c.fast_model], ["Anthropic API key", c.anthropic_key_configured ? "Configured (hidden)" : "Not set"],
              ["Tool budget per investigation", String(c.max_tool_calls)], ["Demo pacing", `${c.demo_pace_seconds}s per tool`], ["External network", c.network_enabled ? "Enabled" : "Disabled (cache only)"]].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4"><dt className="text-zinc-500">{k}</dt><dd className="text-right font-mono text-[12px] text-zinc-200">{v}</dd></div>))}
          </dl>
        </Panel>
        <Panel title="Connected services">
          <ul className="space-y-2.5 text-[13px]">{Object.entries(st.data.services).map(([k, v]) => (
            <li key={k}><div className="flex items-center justify-between gap-3"><span>{LABEL[k] ?? k}</span><Tag tone={STATE_TONE[v.state]}>{titleCase(v.state)}</Tag></div>
              <div className="text-[11.5px] text-zinc-500">{v.detail}</div></li>))}</ul>
        </Panel>
        <Panel title="How to change configuration" className="lg:col-span-2">
          <p className="mb-3 text-[13px] text-zinc-400">Configuration is read from environment variables when the backend starts. Keys are deliberately not editable from the browser.</p>
          <pre className="overflow-x-auto rounded-lg border bg-sunken p-3 font-mono text-[12px] leading-relaxed text-zinc-300">{`export ANTHROPIC_API_KEY=sk-ant-...         # enables the LLM agent
export CLAIMPILOT_MODEL=claude-opus-5-5      # planner / investigator / vision
export CLAIMPILOT_FAST_MODEL=claude-haiku-5-5
export CLAIMPILOT_MAX_TOOL_CALLS=18
export CLAIMPILOT_PACE=0.45                  # deterministic-mode demo pacing
export CLAIMPILOT_ALLOW_NETWORK=1            # Open-Meteo + Nominatim
./start.sh`}</pre>
        </Panel>
        <Panel title="Routing queues" className="lg:col-span-2">
          <div className="flex flex-wrap gap-2">{Object.entries(c.queues).map(([k, v]) => <Tag key={k}>{v}</Tag>)}</div>
        </Panel>
      </div>
    </div>
  );
}
