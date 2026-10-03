"use client";

import { useEffect, useState } from "react";
import { getApi } from "@/lib/api";

export function useResource<T>(path: string | null) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ path: string | null; loading: boolean; data: T | null; error: string | null }>({ path, loading: Boolean(path), data: null, error: null });
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    getApi<T>(path, controller.signal).then(
      (data) => setState({ path, loading: false, data, error: null }),
      (error: unknown) => { if (!controller.signal.aborted) setState({ path, loading: false, data: null, error: error instanceof Error ? error.message : "Falha inesperada." }); },
    );
    return () => controller.abort();
  }, [path, revision]);
  const current = state.path === path ? state : { path, loading: Boolean(path), data: null, error: null };
  return { ...current, reload: () => { setState({ path, loading: true, data: null, error: null }); setRevision((n) => n + 1); } };
}
