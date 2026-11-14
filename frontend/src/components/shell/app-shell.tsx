"use client";

import {
  Activity, BarChart3, Bell, BookOpenText, ChevronsLeft, ChevronsRight, CircleDot, FileSearch, FlaskConical,
  Gauge, History, LayoutGrid, Menu, Network, Radar, Search, Settings, ShieldAlert, Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Tag } from "@/components/common";
import {
  CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from "@/components/ui/command";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useApi } from "@/hooks/use-api";
import { ClaimRow, SNAPSHOT, STATUS_LABEL, SystemStatus, inr, titleCase } from "@/lib/api";
import { CURRENT_USER } from "@/lib/user";
import { cn } from "@/lib/utils";

export const NAV = [
  { href: "/", label: "Overview", icon: Gauge },
  { href: "/claims", label: "Claims Queue", icon: LayoutGrid },
  { href: "/investigations", label: "Live Investigations", icon: Radar },
  { href: "/evidence", label: "Evidence Explorer", icon: FileSearch },
  { href: "/fraud", label: "Fraud Intelligence", icon: ShieldAlert },
  { href: "/policies", label: "Policy Library", icon: BookOpenText },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/audit", label: "Audit Trail", icon: History },
  { href: "/settings", label: "Settings", icon: Settings },
];
const MORE = [
  { href: "/evals", label: "Evaluation", icon: FlaskConical },
  { href: "/handlers", label: "Handlers", icon: Users },
  { href: "/architecture", label: "How it works", icon: Network },
];

function isActive(path: string, href: string) {
  if (href === "/") return path === "/";
  if (href === "/claims") return path === "/claims" || (path.startsWith("/claims/") && !path.startsWith("/claims/new"));
  return path.startsWith(href);
}

function titleFor(path: string) {
  if (path.startsWith("/claims/new")) return "New claim";
  if (path.startsWith("/claims/")) return "Claim workspace";
  if (path.startsWith("/investigations/")) return "Live investigation";
  return [...NAV, ...MORE].find((n) => isActive(path, n.href))?.label ?? "ClaimPilot";
}

function NavList({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const path = usePathname();
  const item = (n: (typeof NAV)[number]) => {
    const active = isActive(path, n.href);
    const link = (
      <Link key={n.href} href={n.href} onClick={onNavigate} aria-current={active ? "page" : undefined}
        className={cn("group flex h-9 items-center gap-2.5 rounded-md px-2.5 text-[13px] transition-colors",
          active ? "bg-sidebar-accent font-medium text-white" : "text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-white",
          collapsed && "justify-center px-0")}>
        <n.icon size={16} className={cn("shrink-0", active ? "text-indigo-300" : "text-zinc-500 group-hover:text-zinc-300")} />
        {!collapsed && <span className="truncate">{n.label}</span>}
        {active && !collapsed && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-indigo-400" />}
      </Link>
    );
    return collapsed ? (
      <Tooltip key={n.href}><TooltipTrigger asChild>{link}</TooltipTrigger><TooltipContent side="right">{n.label}</TooltipContent></Tooltip>
    ) : link;
  };
  return (
    <nav aria-label="Main" className="flex-1 space-y-0.5 overflow-y-auto p-2.5 scroll-thin">
      {NAV.map(item)}
      <div className={cn("px-2.5 pb-1 pt-4 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600", collapsed && "sr-only")}>More</div>
      {MORE.map(item)}
    </nav>
  );
}

function Brand({ collapsed }: { collapsed: boolean }) {
  return (
    <Link href="/" className={cn("flex h-14 shrink-0 items-center gap-2.5 border-b border-sidebar-border px-4", collapsed && "justify-center px-0")}>
      <div className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-indigo-500 text-white shadow-[0_0_0_1px_rgba(255,255,255,0.12)_inset]">
        <Activity size={15} strokeWidth={2.5} />
      </div>
      {!collapsed && (
        <div className="leading-tight">
          <div className="text-[14px] font-semibold tracking-tight text-white">ClaimPilot</div>
          <div className="truncate text-[10.5px] text-zinc-500">Claims intelligence</div>
        </div>
      )}
    </Link>
  );
}

function Profile({ collapsed }: { collapsed: boolean }) {
  return (
    <div className={cn("flex items-center gap-2.5 border-t border-sidebar-border p-3", collapsed && "justify-center")}>
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-zinc-800 text-[12px] font-semibold text-zinc-200">{CURRENT_USER.initials}</div>
      {!collapsed && (
        <div className="min-w-0 leading-tight">
          <div className="truncate text-[13px] font-medium text-zinc-200">{CURRENT_USER.name}</div>
          <div className="truncate text-[11px] text-zinc-500">{CURRENT_USER.role}</div>
        </div>
      )}
    </div>
  );
}

const STATE_DOT: Record<string, string> = {
  connected: "bg-emerald-400", online: "bg-emerald-400", mock: "bg-sky-400", degraded: "bg-amber-400",
  not_configured: "bg-zinc-500", disabled: "bg-zinc-500", unavailable: "bg-rose-500",
};
const SERVICE_LABEL: Record<string, string> = {
  policy_database: "Policy database", llm_provider: "LLM provider", weather_api: "Weather API (Open-Meteo)",
  geocoder: "Geocoder (OpenStreetMap)", vehicle_registry: "Vehicle registry", reverse_image_search: "Reverse image search",
};

function SystemIndicator() {
  const { data, error } = useApi<SystemStatus>("/api/status", 30000);
  const down = !!error && !data;
  if (SNAPSHOT) return (
    <Tooltip>
      <TooltipTrigger className="flex h-8 items-center gap-2 rounded-md border px-2.5 text-[12px]" aria-label="Hosted demo status">
        <span className="h-2 w-2 rounded-full bg-amber-400" /><span className="hidden sm:inline">Recorded run</span>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">Static, read-only replay of a real backend run. No live agent or external services are called from this site.</TooltipContent>
    </Tooltip>
  );
  const degraded = data && Object.values(data.services).some((s) => s.state === "unavailable" || s.state === "degraded");
  return (
    <Popover>
      <PopoverTrigger className="flex h-8 items-center gap-2 rounded-md border px-2.5 text-[12px] hover:bg-accent" aria-label="System status">
        <span className={cn("h-2 w-2 rounded-full", down ? "bg-rose-500" : degraded ? "bg-amber-400" : data ? "bg-emerald-400" : "bg-zinc-500")} />
        <span className="hidden sm:inline">{down ? "Backend offline" : !data ? "Checking…" : degraded ? "Partially degraded" : "Agent online"}</span>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <div className="border-b px-3.5 py-2.5 text-[12px] font-semibold">System status</div>
        {down ? <div className="p-3.5 text-[13px] text-risk">Cannot reach the API at port 8000. Start the backend.</div> : data && (
          <ul className="divide-y text-[12.5px]">
            <li className="flex items-center justify-between gap-3 px-3.5 py-2">
              <span>Agent</span>
              <span className="flex items-center gap-1.5 text-muted-foreground"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                {data.agent.mode === "llm" ? "LLM agent" : "Deterministic rules"}</span>
            </li>
            {Object.entries(data.services).map(([k, s]) => (
              <li key={k} className="px-3.5 py-2">
                <div className="flex items-center justify-between gap-3">
                  <span>{SERVICE_LABEL[k] ?? k}</span>
                  <span className="flex items-center gap-1.5 text-muted-foreground"><span className={cn("h-1.5 w-1.5 rounded-full", STATE_DOT[s.state])} />{titleCase(s.state)}</span>
                </div>
                <div className="mt-0.5 text-[11px] text-subtle-foreground">{s.detail}</div>
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}

function ModelIndicator() {
  const { data } = useApi<SystemStatus>("/api/status", 60000);
  if (!data) return null;
  return (
    <Tooltip>
      <TooltipTrigger className="hidden items-center gap-1.5 rounded-md border px-2.5 py-1.5 font-mono text-[11px] text-muted-foreground lg:flex">
        <CircleDot size={11} className={data.agent.mode === "llm" ? "text-emerald-400" : "text-amber-400"} />
        {data.agent.model ?? "rules-engine"}
      </TooltipTrigger>
      <TooltipContent>{data.agent.mode === "llm" ? `Primary ${data.agent.model}, intake ${data.agent.fast_model}` : "No ANTHROPIC_API_KEY: deterministic planner and investigator; same tools, scoring and gates."}</TooltipContent>
    </Tooltip>
  );
}

function DemoBadge() {
  const { data } = useApi<SystemStatus>("/api/status", 60000);
  if (data?.data.source !== "synthetic") return null;
  return (
    <Tooltip>
      <TooltipTrigger asChild><span><Tag tone="missing" className="font-semibold tracking-wide">DEMO DATA</Tag></span></TooltipTrigger>
      <TooltipContent className="max-w-xs">{data.data.detail}. Agent runs, tool calls and the weather API are real executions against this synthetic book.</TooltipContent>
    </Tooltip>
  );
}

function Notifications() {
  const router = useRouter();
  const { data } = useApi<ClaimRow[]>("/api/claims", 8000);
  const items = (data ?? []).filter((c) => c.status === "awaiting_review" || c.status === "awaiting_documents" || c.status === "error");
  return (
    <Popover>
      <PopoverTrigger className="relative grid h-8 w-8 place-items-center rounded-md border hover:bg-accent" aria-label={`Notifications (${items.length})`}>
        <Bell size={15} />
        {items.length > 0 && <span className="absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full bg-rose-500 px-1 text-[10px] font-semibold text-white">{items.length}</span>}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <div className="border-b px-3.5 py-2.5 text-[12px] font-semibold">Needs attention</div>
        {items.length === 0 ? <div className="p-4 text-[13px] text-muted-foreground">Nothing is waiting on a person.</div> : (
          <ul className="max-h-80 divide-y overflow-y-auto scroll-thin">
            {items.map((c) => (
              <li key={c.id}>
                <button onClick={() => router.push(`/claims/${c.id}`)} className="w-full px-3.5 py-2.5 text-left hover:bg-accent">
                  <div className="flex items-center justify-between gap-2 text-[12.5px]">
                    <span className="font-mono">{c.id}</span>
                    <Tag tone={c.status === "error" ? "risk" : "missing"}>{STATUS_LABEL[c.status]}</Tag>
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-muted-foreground">{titleCase(c.claim_type)} · {inr(c.amount_claimed)} · {c.queue_label ?? "—"}</div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}

function GlobalSearch() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const { data } = useApi<ClaimRow[]>(open ? "/api/claims" : null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen((o) => !o); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const go = (href: string) => { setOpen(false); router.push(href); };
  return (
    <>
      <button onClick={() => setOpen(true)} className="flex h-8 w-full max-w-sm items-center gap-2 rounded-md border bg-raised px-2.5 text-[12.5px] text-muted-foreground hover:border-border-strong">
        <Search size={14} /> <span className="flex-1 text-left">Search claims, pages…</span>
        <kbd className="hidden rounded border px-1.5 font-mono text-[10px] sm:inline">⌘K</kbd>
      </button>
      <CommandDialog open={open} onOpenChange={setOpen} title="Search" description="Search claims and pages">
        <CommandInput placeholder="Claim ID, city, claim type, page…" />
        <CommandList>
          <CommandEmpty>No results.</CommandEmpty>
          <CommandGroup heading="Claims">
            {(data ?? []).map((c) => (
              <CommandItem key={c.id} value={`${c.id} ${c.city} ${c.claim_type} ${c.line}`} onSelect={() => go(`/claims/${c.id}`)}>
                <span className="font-mono text-[12px]">{c.id}</span>
                <span className="text-muted-foreground">{titleCase(c.claim_type)} · {c.city} · {inr(c.amount_claimed)}</span>
              </CommandItem>
            ))}
          </CommandGroup>
          <CommandGroup heading="Pages">
            {[...NAV, ...MORE].map((n) => (
              <CommandItem key={n.href} value={n.label} onSelect={() => go(n.href)}><n.icon size={14} /> {n.label}</CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      </CommandDialog>
    </>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    try { setCollapsed(localStorage.getItem("cp.sidebar") === "1"); } catch {}
  }, []);
  const toggle = () => setCollapsed((c) => { try { localStorage.setItem("cp.sidebar", c ? "0" : "1"); } catch {} return !c; });
  const title = useMemo(() => titleFor(path), [path]);

  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-primary focus:px-3 focus:py-1.5">Skip to content</a>
      <aside className={cn("sticky top-0 hidden h-screen shrink-0 flex-col border-r border-sidebar-border bg-sidebar transition-[width] duration-200 lg:flex",
        collapsed ? "w-[60px]" : "w-60")}>
        <Brand collapsed={collapsed} />
        <NavList collapsed={collapsed} />
        <button onClick={toggle} className="mx-2.5 mb-2 flex h-8 items-center justify-center gap-2 rounded-md text-[12px] text-zinc-500 hover:bg-sidebar-accent hover:text-zinc-300"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
          {collapsed ? <ChevronsRight size={15} /> : <><ChevronsLeft size={15} /> Collapse</>}
        </button>
        <Profile collapsed={collapsed} />
      </aside>

      <Sheet open={mobile} onOpenChange={setMobile}>
        <SheetContent side="left" className="w-64 bg-sidebar p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <div className="flex h-full flex-col"><Brand collapsed={false} /><NavList collapsed={false} onNavigate={() => setMobile(false)} /><Profile collapsed={false} /></div>
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/85 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/70 sm:px-6">
          <button className="grid h-8 w-8 place-items-center rounded-md border lg:hidden" onClick={() => setMobile(true)} aria-label="Open navigation"><Menu size={16} /></button>
          <div className="hidden min-w-0 shrink-0 text-[14px] font-semibold md:block">{title}</div>
          <div className="flex min-w-0 flex-1 justify-center px-2"><GlobalSearch /></div>
          <div className="flex items-center gap-2">
            <DemoBadge />
            <ModelIndicator />
            <SystemIndicator />
            <Notifications />
            <DropdownMenu>
              <DropdownMenuTrigger className="grid h-8 w-8 place-items-center rounded-full bg-zinc-800 text-[11px] font-semibold" aria-label="Profile menu">{CURRENT_USER.initials}</DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel><div className="text-[13px]">{CURRENT_USER.name}</div><div className="text-[11px] font-normal text-muted-foreground">{CURRENT_USER.role} · demo identity</div></DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild><Link href="/settings">Settings</Link></DropdownMenuItem>
                <DropdownMenuItem asChild><Link href="/audit">My decisions (audit)</Link></DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        {SNAPSHOT && (
          <div role="note" className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 border-b border-missing-line bg-missing-bg px-4 py-2 text-center text-[12.5px] text-amber-100">
            <b className="font-semibold text-missing">Hosted demo.</b>
            Every claim here was investigated by the real ClaimPilot agent; this site replays that recorded run on synthetic data, so actions are read-only.
            <a href="https://github.com/niranjan19m-source/claimpilot" className="font-medium text-missing underline underline-offset-2">Source on GitHub</a>
            <span className="text-zinc-600">·</span>
            <a href={`${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/about/`} className="font-medium text-missing underline underline-offset-2">About the project</a>
          </div>
        )}
        <main id="main" className="canvas-grid min-w-0 flex-1 px-4 py-6 sm:px-6">{children}</main>
      </div>
    </div>
  );
}
