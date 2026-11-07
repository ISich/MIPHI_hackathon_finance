import { useCallback, useEffect, useRef, useState } from "react";

export interface Loadable<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/**
 * Loads data for a given key. Responses for a stale key (user switched to
 * another Run meanwhile) are dropped, so they never overwrite the current view.
 */
export function useApi<T>(key: string | null, fn: () => Promise<T>): Loadable<T> {
  const [state, setState] = useState<{ key: string | null; data?: T; error?: unknown; loading: boolean }>({
    key,
    loading: key !== null,
  });
  const [nonce, setNonce] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (key === null) return;
    let alive = true;
    setState((s) => ({ key, data: s.key === key ? s.data : undefined, loading: true }));
    fnRef.current().then(
      (data) => alive && setState({ key, data, loading: false }),
      (error) => alive && setState({ key, error, loading: false }),
    );
    return () => {
      alive = false;
    };
  }, [key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const current = state.key === key;
  return {
    data: current ? state.data : undefined,
    error: current ? state.error : undefined,
    loading: key !== null && (!current || state.loading),
    reload,
  };
}

/**
 * Calls `tick` every `intervalMs` while `active`. Ticks never overlap; the
 * loop stops on unmount or when `active` becomes false.
 */
export function usePolling(active: boolean, intervalMs: number, tick: () => Promise<void>, deps: unknown[]): void {
  const tickRef = useRef(tick);
  tickRef.current = tick;
  useEffect(() => {
    if (!active) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const loop = async () => {
      try {
        await tickRef.current();
      } finally {
        if (!stopped) timer = setTimeout(loop, intervalMs);
      }
    };
    void loop();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, intervalMs, ...deps]);
}
