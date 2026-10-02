"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { LIBRARY_BATCH_SIZE, LibraryPager, type LibraryLoadState } from "../library-view-logic";
import { api, type LibraryNode, type LibraryPage } from "./types-and-api";

export function useLibraryItems(endpoint: string | null) {
  const [snapshot, setSnapshot] = useState<{ endpoint: string | null; state: LibraryLoadState<LibraryNode> } | null>(null);
  const pager = useRef<LibraryPager<LibraryNode> | null>(null);
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!endpoint) return;
    const next = new LibraryPager<LibraryNode>((page, signal) => api<LibraryPage>(`${endpoint}&page=${page}&page_size=${LIBRARY_BATCH_SIZE}`, { signal, cache: "no-store" }), state => setSnapshot({ endpoint, state }));
    pager.current = next;
    void next.load();
    return () => { next.reset(); if (pager.current === next) pager.current = null; };
  }, [endpoint]);
  const state = snapshot?.endpoint === endpoint ? snapshot.state : null;
  const loadMore = useCallback(() => { void pager.current?.load(); }, []);
  const reload = useCallback(() => { pager.current?.reset(); void pager.current?.load(); }, []);
  const refreshDuringSync = useCallback(() => { if (!pager.current?.state.error) void pager.current?.refresh(); }, []);
  useEffect(() => {
    const target = sentinel.current;
    if (!target || !state?.hasMore || state.loading || state.error) return;
    const observer = new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting)) loadMore(); }, { rootMargin: "300px" });
    observer.observe(target);
    return () => observer.disconnect();
  }, [state, loadMore]);
  return { items: state?.items ?? [], loading: Boolean(endpoint) && (!state || state.loading && state.items.length === 0),
    loadingMore: Boolean(state?.loading && state.items.length > 0), hasMore: state?.hasMore ?? false,
    error: state?.error ?? null, sentinel, loadMore, reload, refreshDuringSync };
}
