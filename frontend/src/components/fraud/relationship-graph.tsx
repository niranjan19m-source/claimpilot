"use client";

import {
  Background, Controls, type Edge, Handle, type Node, type NodeProps, Position, ReactFlow, useEdgesState, useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Building2, CreditCard, FileText, Hospital, Phone, User, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { EmptyState, Tag } from "@/components/common";
import type { ClaimRelationship, GraphNode, ToolResult } from "@/lib/api";
import { cn } from "@/lib/utils";

const KIND: Record<string, { label: string; icon: React.ElementType; field: string }> = {
  claim: { label: "Claim", icon: FileText, field: "" },
  person: { label: "Person", icon: User, field: "customer_id" },
  phone: { label: "Phone", icon: Phone, field: "contact_phone" },
  bank: { label: "Bank account", icon: CreditCard, field: "bank_account" },
  garage: { label: "Garage", icon: Building2, field: "garage_id" },
  hospital: { label: "Hospital", icon: Hospital, field: "hospital_id" },
};
const FLAGGED = new Set(["fraud_confirmed", "repudiated_fraud"]);
const mask = (kind: string, v: string) => (kind === "phone" || kind === "bank" ? `••••${v.slice(-4)}` : v);

type Status = "flagged" | "unverified" | "neutral" | "self";
type NodeData = { g: GraphNode; status: Status; linkedFlagged: number };

function EntityNode({ data, selected }: NodeProps<Node<NodeData>>) {
  const k = KIND[data.g.kind] ?? KIND.claim;
  const Icon = k.icon;
  const ring = { flagged: "ring-rose-500/70 bg-rose-500/15 text-rose-200", unverified: "ring-amber-400/60 bg-amber-400/10 text-amber-100",
    neutral: "ring-white/15 bg-zinc-900 text-zinc-200", self: "ring-indigo-400 bg-indigo-500/20 text-white" }[data.status];
  return (
    <div className={cn("flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] ring-1 shadow-sm", ring, selected && "outline-2 outline-indigo-300")}>
      <Handle type="target" position={Position.Top} className="!h-1 !w-1 !border-0 !bg-transparent" />
      <Icon size={12} />
      <span className="font-mono">{data.g.self ? "THIS CLAIM" : mask(data.g.kind, data.g.label)}</span>
      <Handle type="source" position={Position.Bottom} className="!h-1 !w-1 !border-0 !bg-transparent" />
    </div>
  );
}
const nodeTypes = { entity: EntityNode };

/** Radial layout: this claim at the centre, rings by graph distance. Deterministic. */
function layout(nodes: GraphNode[], edges: ClaimRelationship[]) {
  const adj = new Map<string, string[]>();
  for (const e of edges) { adj.set(e.source, [...(adj.get(e.source) ?? []), e.target]); adj.set(e.target, [...(adj.get(e.target) ?? []), e.source]); }
  const root = nodes.find((n) => n.self)?.id ?? nodes[0]?.id;
  const depth = new Map<string, number>([[root, 0]]);
  const q = [root];
  while (q.length) { const n = q.shift()!; for (const m of adj.get(n) ?? []) if (!depth.has(m)) { depth.set(m, depth.get(n)! + 1); q.push(m); } }
  const rings = new Map<number, string[]>();
  for (const n of nodes) { const d = depth.get(n.id) ?? 4; rings.set(d, [...(rings.get(d) ?? []), n.id]); }
  const pos = new Map<string, { x: number; y: number }>();
  for (const [d, ids] of rings) ids.forEach((id, i) => {
    const r = d * 210, a = (2 * Math.PI * i) / ids.length + d * 0.35;
    pos.set(id, { x: Math.cos(a) * r, y: Math.sin(a) * r * 0.75 });
  });
  return pos;
}

export function RelationshipGraph({ entry }: { entry?: ToolResult | null }) {
  const graph = entry?.data?.graph as { nodes: GraphNode[]; edges: ClaimRelationship[] } | undefined;
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [highlight, setHighlight] = useState(true);
  const [sel, setSel] = useState<{ type: "node" | "edge"; id: string } | null>(null);

  const status = useMemo(() => {
    const m = new Map<string, NodeData>();
    if (!graph) return m;
    const nb = new Map<string, string[]>();
    for (const e of graph.edges) { nb.set(e.source, [...(nb.get(e.source) ?? []), e.target]); nb.set(e.target, [...(nb.get(e.target) ?? []), e.source]); }
    const byId = Object.fromEntries(graph.nodes.map((n) => [n.id, n]));
    for (const n of graph.nodes) {
      const linkedFlagged = (nb.get(n.id) ?? []).filter((x) => FLAGGED.has(byId[x]?.outcome ?? "")).length;
      const s: Status = n.self ? "self" : FLAGGED.has(n.outcome ?? "") ? "flagged" : n.outcome === "under_investigation" ? "unverified"
        : n.kind !== "claim" && linkedFlagged > 0 ? "unverified" : "neutral";
      m.set(n.id, { g: n, status: s, linkedFlagged });
    }
    return m;
  }, [graph]);

  const initial = useMemo(() => {
    if (!graph) return { nodes: [] as Node<NodeData>[], edges: [] as Edge[] };
    const pos = layout(graph.nodes, graph.edges);
    const nodes: Node<NodeData>[] = graph.nodes.map((n) => ({ id: n.id, type: "entity", position: pos.get(n.id) ?? { x: 0, y: 0 }, data: status.get(n.id)! }));
    const edges: Edge[] = graph.edges.map((e, i) => {
      const hot = [e.source, e.target].some((id) => status.get(id)?.status === "flagged");
      return { id: `e${i}`, source: e.source, target: e.target, type: "straight", data: { hot },
        style: { stroke: hot ? "rgb(244 63 94 / 0.75)" : "rgb(255 255 255 / 0.16)", strokeWidth: hot ? 1.6 : 1 } };
    });
    return { nodes, edges };
  }, [graph, status]);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<NodeData>>(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initial.edges);
  useEffect(() => { setNodes(initial.nodes); setEdges(initial.edges); }, [initial, setNodes, setEdges]);
  useEffect(() => {
    setNodes((ns) => ns.map((n) => ({ ...n, hidden: hidden.has(n.data.g.kind) && !n.data.g.self })));
    setEdges((es) => es.map((e) => {
      const hot = (e.data as any)?.hot;
      return { ...e, style: { stroke: hot && highlight ? "rgb(244 63 94 / 0.75)" : "rgb(255 255 255 / 0.16)", strokeWidth: hot && highlight ? 1.6 : 1 } };
    }));
  }, [hidden, highlight, setNodes, setEdges]);

  if (!graph) return <EmptyState title="Link analysis not run" body="Relationship mapping runs on standard and deep investigations. This claim had a light-touch plan." />;

  const byId = Object.fromEntries(graph.nodes.map((n) => [n.id, n]));
  const selNode = sel?.type === "node" ? status.get(sel.id) : null;
  const selEdge = sel?.type === "edge" ? edges.find((e) => e.id === sel.id) : null;
  const neighbours = (id: string) => graph.edges.flatMap((e) => (e.source === id ? [e.target] : e.target === id ? [e.source] : [])).map((x) => byId[x]).filter(Boolean);
  const kinds = [...new Set(graph.nodes.map((n) => n.kind))];

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
      <div className="overflow-hidden rounded-xl border bg-sunken">
        <div className="flex flex-wrap items-center gap-2 border-b bg-card/60 px-3 py-2 text-[11.5px]">
          <span className="text-zinc-500">Show:</span>
          {kinds.filter((k) => k !== "claim").map((k) => (
            <button key={k} onClick={() => setHidden((h) => { const n = new Set(h); if (n.has(k)) n.delete(k); else n.add(k); return n; })} aria-pressed={!hidden.has(k)}
              className={cn("rounded-md px-2 py-0.5 ring-1", hidden.has(k) ? "text-zinc-600 ring-white/5" : "text-zinc-200 ring-white/15")}>{KIND[k]?.label ?? k}</button>
          ))}
          <label className="ml-auto flex items-center gap-1.5 text-zinc-400"><input type="checkbox" checked={highlight} onChange={(e) => setHighlight(e.target.checked)} /> Highlight links to flagged claims</label>
        </div>
        <div style={{ height: 520 }}>
          <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} nodeTypes={nodeTypes}
            onNodeClick={(_, n) => setSel({ type: "node", id: n.id })} onEdgeClick={(_, e) => setSel({ type: "edge", id: e.id })}
            fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.2} proOptions={{ hideAttribution: true }} colorMode="dark">
            <Background gap={22} size={1} color="rgb(255 255 255 / 0.05)" />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        <div className="flex flex-wrap gap-3 border-t px-3 py-2 text-[11px] text-zinc-500">
          <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-indigo-400" />This claim</span>
          <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-rose-500" />Previously flagged (fraud-repudiated)</span>
          <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-amber-400" />Unverified / linked to a flagged claim</span>
          <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-zinc-500" />No adverse record</span>
        </div>
      </div>

      <aside className="rounded-xl border bg-card p-4 text-[12.5px]">
        {!sel ? (
          <div className="space-y-2 text-zinc-400">
            <div className="text-[13px] font-medium text-zinc-200">Inspect a relationship</div>
            <p>Click a node to see its linked claims, or an edge to see the record that creates the link.</p>
            <p className="text-[11.5px] text-zinc-500">Every link comes from a claim record field (phone, bank account, person, garage, hospital).
              A shared identifier is a reason to look closer. It does not prove wrongdoing.</p>
            <div className="grid grid-cols-3 gap-2 pt-2 text-center">
              <div className="rounded-md bg-raised p-2"><div className="text-[18px] font-semibold">{entry?.data.cluster_claims}</div><div className="text-[10.5px] text-zinc-500">linked claims</div></div>
              <div className="rounded-md bg-raised p-2"><div className="text-[18px] font-semibold">{entry?.data.cluster_people}</div><div className="text-[10.5px] text-zinc-500">people</div></div>
              <div className="rounded-md bg-raised p-2"><div className="text-[18px] font-semibold text-risk">{entry?.data.confirmed_fraud}</div><div className="text-[10.5px] text-zinc-500">flagged</div></div>
            </div>
          </div>
        ) : (
          <div>
            <div className="mb-2 flex items-center justify-between"><span className="text-[11px] uppercase tracking-[0.1em] text-zinc-500">{sel.type === "node" ? "Entity" : "Relationship"}</span>
              <button onClick={() => setSel(null)} aria-label="Close details" className="text-zinc-500 hover:text-zinc-200"><X size={14} /></button></div>
            {selNode && (
              <div className="space-y-2">
                <div className="flex items-center gap-2"><span className="font-mono text-[13px]">{selNode.g.self ? "This claim" : mask(selNode.g.kind, selNode.g.label)}</span>
                  <Tag tone={selNode.status === "flagged" ? "risk" : selNode.status === "unverified" ? "missing" : "neutral"}>{KIND[selNode.g.kind]?.label}</Tag></div>
                {selNode.g.outcome && <div className="text-zinc-400">Recorded outcome: <b className="text-zinc-200">{selNode.g.outcome.replace(/_/g, " ")}</b></div>}
                {selNode.linkedFlagged > 0 && <div className="text-missing">Directly linked to {selNode.linkedFlagged} fraud-repudiated claim(s).</div>}
                <div className="pt-1 text-[11px] uppercase tracking-[0.1em] text-zinc-500">Connected ({neighbours(sel.id).length})</div>
                <ul className="max-h-64 space-y-1 overflow-y-auto scroll-thin">
                  {neighbours(sel.id).map((n) => (
                    <li key={n.id} className="flex items-center justify-between gap-2 rounded bg-raised px-2 py-1">
                      <span className="font-mono text-[11.5px]">{n.self ? "This claim" : mask(n.kind, n.label)}</span>
                      {n.kind === "claim" && !n.self ? (n.outcome && FLAGGED.has(n.outcome) ? <Tag tone="risk">flagged</Tag> : <Link className="text-[11px] text-info hover:underline" href={`/claims/${n.label}`}>{n.outcome?.replace(/_/g, " ") ?? "view"}</Link>)
                        : <span className="text-[10.5px] text-zinc-500">{KIND[n.kind]?.label}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {selEdge && (() => {
              const a = byId[selEdge.source], b = byId[selEdge.target];
              const claim = a?.kind === "claim" ? a : b, ent = a?.kind === "claim" ? b : a;
              return (
                <div className="space-y-2">
                  <div className="text-zinc-200">{claim?.self ? "This claim" : `Claim ${claim?.label}`} ↔ {KIND[ent?.kind ?? ""]?.label} <span className="font-mono">{ent && mask(ent.kind, ent.label)}</span></div>
                  <div className="rounded-md border bg-raised p-2.5 text-[12px] text-zinc-400">
                    <div className="text-[10.5px] uppercase tracking-[0.1em] text-zinc-500">Evidence</div>
                    Claim record field <code className="text-zinc-300">{KIND[ent?.kind ?? ""]?.field}</code> on {claim?.self ? "this claim" : claim?.label} contains this {KIND[ent?.kind ?? ""]?.label.toLowerCase()}.
                    {claim?.outcome && <div className="mt-1">Recorded outcome of that claim: <b className="text-zinc-300">{claim.outcome.replace(/_/g, " ")}</b>.</div>}
                  </div>
                  <p className="text-[11px] text-zinc-500">Source: claims database (synthetic). The link is factual; what it means is for the investigator to decide.</p>
                </div>
              );
            })()}
          </div>
        )}
      </aside>
    </div>
  );
}
