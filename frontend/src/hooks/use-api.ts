"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

/** Fetch JSON with loading/error state and optional polling. Keeps the last good
 *  data on transient errors so panels don't flash empty during a blip. */
export function useApi<T>(path: string | null, intervalMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!path);
  const alive = useRef(true);

  const reload = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api<T>(path);
      if (alive.current) { setData(d); setError(null); }
    } catch (e: any) {
      if (alive.current) setError(e.message ?? String(e));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    alive.current = true;
    setLoading(!!path);
    reload();
    if (!intervalMs || !path) return () => { alive.current = false; };
    const t = setInterval(reload, intervalMs);
    return () => { alive.current = false; clearInterval(t); };
  }, [path, intervalMs, reload]);

  return { data, error, loading, reload, setData };
}
