"use client";

import {
  ColumnDef, SortingState, flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, useReactTable,
} from "@tanstack/react-table";
import { ArrowUpDown, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { EmptyState, ErrorState, PageHeader, SkeletonRows, Tag, coverageTone, fraudLabel, fraudTone, severityTone, statusTone } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/hooks/use-api";
import { ClaimRow, QUEUE_LABEL, STATUS_LABEL, inr, titleCase } from "@/lib/api";

function sortable(label: string) {
  function SortHeader({ column }: any) {
    return (
      <button className="inline-flex items-center gap-1 hover:text-zinc-200" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
        {label}<ArrowUpDown size={11} />
      </button>
    );
  }
  return SortHeader;
}

export default function ClaimsQueue() {
  const router = useRouter();
  const { data, error, loading, reload } = useApi<ClaimRow[]>("/api/claims", 5000);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");

  const columns = useMemo<ColumnDef<ClaimRow>[]>(() => [
    { accessorKey: "id", header: sortable("Claim"), cell: ({ row }) => <span className="font-mono text-[12px]">{row.original.id}</span> },
    { accessorKey: "claimant", header: "Claimant" },
    { accessorKey: "claim_type", header: "Type", cell: ({ row }) => `${titleCase(row.original.line)} · ${titleCase(row.original.claim_type)}` },
    { accessorKey: "incident_date", header: sortable("Loss date"), cell: ({ getValue }) => <span className="tabular">{String(getValue())}</span> },
    { accessorKey: "city", header: "City" },
    { accessorKey: "amount_claimed", header: sortable("Amount"), cell: ({ getValue }) => <span className="tabular">{inr(getValue() as number)}</span> },
    { accessorKey: "fraud_score", header: sortable("Fraud risk"), cell: ({ row }) => row.original.fraud_score == null ? <span className="text-zinc-600">—</span> :
      <Tag tone={fraudTone(row.original.fraud_score)}>{fraudLabel(row.original.fraud_score)} · {Math.round(row.original.fraud_score)}</Tag> },
    { accessorKey: "severity", header: "Severity", cell: ({ row }) => row.original.severity ? <Tag tone={severityTone(row.original.severity)}>{titleCase(row.original.severity)}</Tag> : <span className="text-zinc-600">—</span> },
    { accessorKey: "coverage_status", header: "Coverage", cell: ({ row }) => row.original.coverage_status ? <Tag tone={coverageTone(row.original.coverage_status)}>{titleCase(row.original.coverage_status)}</Tag> : <span className="text-zinc-600">—</span> },
    { accessorKey: "confidence", header: sortable("Confidence"), cell: ({ getValue }) => getValue() == null ? <span className="text-zinc-600">—</span> : `${Math.round((getValue() as number) * 100)}%` },
    { accessorKey: "route", header: "Route", cell: ({ row }) => row.original.route ? QUEUE_LABEL[row.original.route] : <span className="text-zinc-600">—</span> },
    { accessorKey: "status", header: "Status", cell: ({ row }) => <Tag tone={statusTone(row.original.status)}>{STATUS_LABEL[row.original.status] ?? row.original.status}</Tag> },
    { accessorKey: "handler_name", header: "Handler", cell: ({ getValue }) => (getValue() as string) ?? <span className="text-zinc-600">—</span> },
  ], []);

  const rows = useMemo(() => (data ?? []).filter((c) => status === "all" || c.status === status), [data, status]);
  const table = useReactTable({
    data: rows, columns, state: { sorting, globalFilter: q }, onSortingChange: setSorting, onGlobalFilterChange: setQ,
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(), getFilteredRowModel: getFilteredRowModel(),
  });

  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader title="Claims queue" description="All open claims with the agent's assessment. Click a row to open the adjuster workspace."
        actions={<Link href="/claims/new"><Button><Plus size={14} /> New claim</Button></Link>} />
      <div className="mb-3 flex flex-wrap gap-2">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search any column…" className="h-8 w-64 text-[12.5px]" aria-label="Search claims" />
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="h-8 w-48 text-[12.5px]" aria-label="Status filter"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">All statuses</SelectItem>{Object.entries(STATUS_LABEL).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      {error && !data ? <ErrorState title="Backend unavailable" message={error} onRetry={reload} /> : loading && !data ? <SkeletonRows rows={8} /> : (
        <div className="overflow-hidden rounded-xl border bg-card">
          <Table>
            <TableHeader>{table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id} className="hover:bg-transparent">{hg.headers.map((h) => <TableHead key={h.id} className="h-10 whitespace-nowrap text-[11.5px] text-zinc-500">{flexRender(h.column.columnDef.header, h.getContext())}</TableHead>)}</TableRow>
            ))}</TableHeader>
            <TableBody>
              {table.getRowModel().rows.length === 0 ? (
                <TableRow><TableCell colSpan={columns.length}><EmptyState title="No claims match" body="Clear the search or status filter." /></TableCell></TableRow>
              ) : table.getRowModel().rows.map((r) => (
                <TableRow key={r.id} tabIndex={0} className="cursor-pointer text-[12.5px]" onClick={() => router.push(`/claims/${r.original.id}`)}
                  onKeyDown={(e) => e.key === "Enter" && router.push(`/claims/${r.original.id}`)}>
                  {r.getVisibleCells().map((cell) => <TableCell key={cell.id} className="whitespace-nowrap py-2.5">{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>)}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
