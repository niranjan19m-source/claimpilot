"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API, AgentEvent, ClaimDetail, api } from "@/lib/api";

/** Events that change persisted claim state, so the detail record is refetched. */
const REFRESH_ON = new Set(["assessment", "routing", "report", "action", "interrupt", "run_completed", "paused",
  "error", "resume", "run_started", "document_received"]);

export type StreamState = "connecting" | "live" | "reconnecting";

/** Claim detail + the live agent event stream (Server-Sent Events).
 *  Reconnects with backoff and resumes from the last event id, so nothing is lost or duplicated. */
export function useClaimStream(id: string | null) {
  const [detail, setDetail] = useState<ClaimDetail | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [stream, setStream] = useState<StreamState>("connecting");
  const lastId = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(() => {
    if (!id) return;
    api<ClaimDetail>(`/api/claims/${id}`).then((d) => { setDetail(d); setError(null); }).catch((e) => setError(e.message));
  }, [id]);

  const scheduleRefresh = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(refresh, 150);
  }, [refresh]);

  useEffect(() => {
    if (!id) return;
    lastId.current = 0;
    setEvents([]);
    refresh();
    let es: EventSource | null = null;
    let closed = false;
    let attempt = 0;
    const connect = () => {
      setStream(attempt ? "reconnecting" : "connecting");
      es = new EventSource(`${API}/api/claims/${id}/stream?after=${lastId.current}`);
      es.onopen = () => { attempt = 0; setStream("live"); };
      es.onmessage = (m) => {
        const ev: AgentEvent = JSON.parse(m.data);
        if (ev.id <= lastId.current) return;
        lastId.current = ev.id;
        setEvents((prev) => [...prev, ev]);
        if (REFRESH_ON.has(ev.type)) scheduleRefresh();
      };
      es.onerror = () => {
        es?.close();
        if (closed) return;
        attempt += 1;
        setStream("reconnecting");
        setTimeout(connect, Math.min(8000, 800 * 2 ** attempt));
      };
    };
    connect();
    return () => { closed = true; es?.close(); if (timer.current) clearTimeout(timer.current); };
  }, [id, refresh, scheduleRefresh]);

  /** Drop events from a previous run (the server clears the log on re-run; ids stay monotonic). */
  const resetEvents = useCallback(() => setEvents([]), []);
  return { detail, events, error, stream, refresh, resetEvents };
}
